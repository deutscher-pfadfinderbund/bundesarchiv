"""WebDAV ObjectStore adapter — the Nextcloud backend (ADR 0005, ADR 0019).

How each port operation maps onto WebDAV is the table "Mapping to the storage port" in
`docs/nextcloud-webdav-notes.md`. The adapter sits on an injected `httpx.Client` whose
`base_url` is the storage root. Every request goes through `_request`, which keeps raw
transport failures (a down/slow mirror is the expected failure mode) from crossing the port
as anything but `ArchiveError`.
"""

import io
import itertools
import random
import time
from collections.abc import Buffer, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

import httpx

from bundesarchiv.persistence.errors import AlreadyExists, ArchiveError, Busy, NotFound
from bundesarchiv.persistence.objectstore import (
    ObjectEntry,
    is_reserved,
    validate_key,
    validate_prefix,
)

_CHUNK = 1024 * 1024  # 1 MiB streaming chunk for put_large
_RETRY_DELAYS = (0.25, 0.5, 1.0, 2.0)  # seconds before each retry; 5 attempts in all
_DAV = "{DAV:}"  # ElementTree Clark notation for the DAV: namespace
_PROPFIND = (
    b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop>'
    b"<resourcetype/><getcontentlength/><getetag/></prop></propfind>"
)


@dataclass(frozen=True, slots=True)
class _Resource:
    """One `<response>` of a multistatus body."""

    href: str
    collection: bool
    size: str | None
    etag: str | None


class WebDavObjectStore:
    """Stores each blob as a WebDAV resource under the client's `base_url`. Owns the client's
    lifetime: call `close()` when done with the store."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self._root_path = urlsplit(str(client.base_url)).path

    def close(self) -> None:
        self._client.close()

    def read(self, key: str) -> bytes:
        with self.open_stream(key) as stream:
            return stream.read()

    def open_stream(self, key: str) -> BinaryIO:
        validate_key(key)
        return io.BufferedReader(_retrying(lambda: self._open_once(key)))

    def _open_once(self, key: str) -> _Body:
        resp = self._request("GET", self._url(key), stream=True)
        # A blob's answer carries its ETag. Nextcloud answers a GET of a collection with 200,
        # an HTML placeholder and no ETag, so a 200 alone does not mean a blob.
        if resp.status_code == httpx.codes.OK and "ETag" in resp.headers:
            return _Body(resp)
        resp.close()
        if resp.status_code == httpx.codes.NOT_FOUND:
            raise NotFound(key)  # a file that appears right after is a later write, not this one
        # Anything else: classify via the same resourcetype probe exists()/delete() use, so
        # absent-vs-collection-vs-error never hinges on a server-specific answer.
        if resp.status_code == httpx.codes.LOCKED or self._is_file(key):
            self._ensure(resp)  # a real blob but no usable answer -> Busy or ArchiveError
        raise NotFound(key)  # absent, or the key names a collection -> no blob here

    def write_atomic(self, key: str, data: bytes) -> str:
        return self._put(key, data, create=False)

    def put_large(self, key: str, stream: BinaryIO, size: int) -> str:
        # `size` is a hint for backends that need it (e.g. chunked upload); the body
        # is streamed straight through here, so it is unused.
        return self._put(key, stream, create=False)

    def create(self, key: str, data: bytes) -> str:
        return self._put(key, data, create=True)

    def create_large(self, key: str, stream: BinaryIO, size: int) -> str:
        return self._put(key, stream, create=True)

    def list(self, prefix: str = "") -> Iterable[str]:
        return [entry.key for entry in self.list_entries(prefix)]

    def list_entries(self, prefix: str = "") -> Iterable[ObjectEntry]:
        folder = prefix.rpartition("/")[0]
        if folder:
            try:
                validate_key(folder)
            except ArchiveError:
                return []  # no stored key has an invalid segment
        return _retrying(lambda: self._entries(folder, prefix))

    def exists(self, key: str) -> bool:
        validate_key(key)
        return _retrying(lambda: self._is_file(key))

    def delete(self, key: str) -> None:
        validate_key(key)
        # Never recursively delete a collection: a directory-prefix key has no blob.
        _retrying(lambda: self._delete_once(key, collection=False))

    def delete_prefix(self, prefix: str) -> None:
        validate_prefix(prefix)
        _retrying(lambda: self._delete_once(prefix, collection=True))

    def _delete_once(self, path: str, *, collection: bool) -> None:
        """`DELETE` `path` if it is a resource of the given kind; else a no-op."""
        resources = self._propfind(path, "0")
        if not resources or resources[0].collection is not collection:
            return
        resp = self._request("DELETE", self._url(path))
        if resp.status_code != httpx.codes.NOT_FOUND:
            self._ensure(resp, httpx.codes.OK, httpx.codes.NO_CONTENT)

    def _put(self, key: str, source: bytes | BinaryIO, *, create: bool) -> str:
        """One `PUT` of `source`, retried while busy; `create` makes it `If-None-Match: *`."""
        validate_key(key)
        headers = {"If-None-Match": "*"} if create else {}
        body, delays = _replayable(source)

        def attempt() -> str:
            self._mkcol_parents(key)
            resp = self._request("PUT", self._url(key), content=body(), headers=headers)
            if create and resp.status_code == httpx.codes.PRECONDITION_FAILED:
                raise AlreadyExists(key)
            _refuse_missing_parent(resp)
            self._ensure(resp, httpx.codes.CREATED, httpx.codes.NO_CONTENT, httpx.codes.OK)
            if (etag := resp.headers.get("ETag")) is None:
                raise ArchiveError(f"WebDAV PUT {key!r} was answered without an ETag")
            return _version(etag)

        return _retrying(attempt, delays)

    def _mkcol_parents(self, key: str) -> None:
        ancestors = key.split("/")[:-1]
        for prefix in itertools.accumulate(ancestors, lambda acc, segment: f"{acc}/{segment}"):
            resp = self._request("MKCOL", self._url(prefix))
            _refuse_missing_parent(resp)
            # 201 created; 405 already exists.
            self._ensure(resp, httpx.codes.CREATED, httpx.codes.METHOD_NOT_ALLOWED)

    def _entries(self, folder: str, prefix: str) -> Iterable[ObjectEntry]:
        files = (
            (self._href_to_key(resource.href), resource)
            for resource in self._propfind(folder, "infinity")
            if not resource.collection
        )
        return sorted(
            (
                _entry(key, resource)
                for key, resource in files
                if key.startswith(prefix) and not is_reserved(key)
            ),
            key=lambda entry: entry.key,
        )

    def _is_file(self, key: str) -> bool:
        resources = self._propfind(key, "0")
        return bool(resources) and not resources[0].collection

    def _propfind(self, path: str, depth: str) -> tuple[_Resource, ...]:
        resp = self._request(
            "PROPFIND", self._url(path), headers={"Depth": depth}, content=_PROPFIND
        )
        if resp.status_code == httpx.codes.NOT_FOUND:
            return ()
        self._ensure(resp, httpx.codes.MULTI_STATUS)
        return tuple(_parse_multistatus(resp.content))

    def _url(self, key: str) -> str:
        return "/".join(quote(segment, safe="") for segment in key.split("/"))

    def _href_to_key(self, href: str) -> str:
        path = urlsplit(href).path
        rel = path.removeprefix(self._root_path)
        return "/".join(unquote(seg) for seg in rel.strip("/").split("/") if seg)

    def _request(
        self, method: str, url: str, *, stream: bool = False, **kwargs: Any
    ) -> httpx.Response:
        # Redirects are never followed, whatever the injected client's policy: a GET of a
        # collection must not chase its redirect and hand back an HTML listing as blob bytes.
        try:
            request = self._client.build_request(method, url, **kwargs)
            return self._client.send(request, stream=stream, follow_redirects=False)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # A down/slow/unreachable/misbehaving mirror is an expected failure mode (ADR 0005);
            # surface ANY httpx error (transport, decoding, redirects, status, bad URL) as
            # ArchiveError, never a raw httpx exception past the port.
            raise ArchiveError(f"WebDAV {method} {url}: {exc}") from exc

    def _ensure(self, resp: httpx.Response, *ok: int) -> None:
        if resp.status_code in ok:
            return
        failure = f"WebDAV {resp.request.method} {resp.request.url} -> {resp.status_code}"
        if resp.status_code == httpx.codes.LOCKED:
            raise Busy(failure)
        raise ArchiveError(failure)


class _Body(io.RawIOBase):
    """The body of a streamed `GET`, handed out as it arrives; closing it closes the response."""

    def __init__(self, resp: httpx.Response) -> None:
        self._resp = resp
        self._chunks = resp.iter_bytes()
        self._pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        try:
            while not self._pending:
                if (chunk := next(self._chunks, None)) is None:
                    return 0
                self._pending = chunk
        except httpx.HTTPError as exc:
            raise ArchiveError(f"WebDAV GET {self._resp.request.url}: {exc}") from exc
        view = memoryview(buffer).cast("B")
        size = min(len(view), len(self._pending))
        view[:size] = self._pending[:size]
        self._pending = self._pending[size:]
        return size

    def close(self) -> None:
        self._resp.close()
        super().close()


class _ParentNotVisible(ArchiveError):
    """A `404`/`409` on `PUT`/`MKCOL`: retried, but once the retries are spent it is not
    contention (a missing root, a file where a folder should be), so not `Busy`."""


def _retrying[T](attempt: Callable[[], T], delays: tuple[float, ...] | None = None) -> T:
    """Run `attempt`, again after each of `delays` (default `_RETRY_DELAYS`) while it raises
    `Busy` or `_ParentNotVisible`; the last attempt's error reaches the caller."""
    for delay in _RETRY_DELAYS if delays is None else delays:
        try:
            return attempt()
        except Busy, _ParentNotVisible:
            time.sleep(delay * random.uniform(0.5, 1.5))  # jitter: contenders spread out
    return attempt()


def _replayable(
    source: bytes | BinaryIO,
) -> tuple[Callable[[], bytes | Iterator[bytes]], tuple[float, ...]]:
    """A body factory for each attempt, and the retry delays it allows, as
    `ObjectStore.put_large` promises."""
    if isinstance(source, bytes):
        return (lambda: source), _RETRY_DELAYS
    if not source.seekable():
        return (lambda: _iter_chunks(source)), ()
    start = source.tell()

    def rewound() -> Iterator[bytes]:
        source.seek(start)
        return _iter_chunks(source)

    return rewound, _RETRY_DELAYS


def _refuse_missing_parent(resp: httpx.Response) -> None:
    # A parent the adapter created a moment ago can still be invisible to the next request.
    if resp.status_code in (httpx.codes.NOT_FOUND, httpx.codes.CONFLICT):
        failure = f"WebDAV {resp.request.method} {resp.request.url} -> {resp.status_code}"
        raise _ParentNotVisible(failure)


def _version(etag: str) -> str:
    return etag.strip('"')  # Nextcloud quotes both the header and getetag; wsgidav only one


def _entry(key: str, resource: _Resource) -> ObjectEntry:
    if resource.size is None or resource.etag is None:
        raise ArchiveError(f"WebDAV listing of {key!r} lacks its size or ETag")
    return ObjectEntry(key, int(resource.size), _version(resource.etag))


def _iter_chunks(stream: BinaryIO) -> Iterator[bytes]:
    while chunk := stream.read(_CHUNK):
        yield chunk


def _parse_multistatus(body: bytes) -> Iterator[_Resource]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        # A malformed multistatus body is a misbehaving mirror — ArchiveError, not a raw
        # xml.etree.ParseError escaping past the port.
        raise ArchiveError(f"WebDAV: malformed multistatus body: {exc}") from exc
    for response in root.iterfind(f"{_DAV}response"):
        href = response.findtext(f"{_DAV}href")
        if href is None:
            continue
        collection = response.find(f"{_DAV}propstat/{_DAV}prop/{_DAV}resourcetype/{_DAV}collection")
        yield _Resource(
            href,
            collection is not None,
            _prop(response, "getcontentlength"),
            _prop(response, "getetag"),
        )


def _prop(response: ElementTree.Element, name: str) -> str | None:
    # A server may list a property it lacks as an empty element in a 404 propstat.
    found = response.iterfind(f"{_DAV}propstat/{_DAV}prop/{_DAV}{name}")
    return next((element.text for element in found if element.text), None)
