"""WebDAV ObjectStore adapter — the Nextcloud mirror backend (ADR 0005).

Atomic create-or-replace is PUT-to-a-reserved-temp + MOVE onto the final key: the
WebDAV analogue of the local-FS temp+rename, so a reader sees the old object or the
new, never a partial. Parent collections are created with MKCOL on demand. The
adapter sits on an injected `httpx.Client` whose `base_url` is the storage root.

`list()` walks with PROPFIND Depth:1 rather than Depth:infinity — Nextcloud disables
infinity — recursing only into non-reserved collections. Every request goes through
`_request`, which keeps raw transport failures (a down/slow mirror is the expected
failure mode) from crossing the port as anything but `ArchiveError`.
"""

import enum
import uuid
from collections.abc import Iterable, Iterator
from typing import Any, BinaryIO
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

import httpx

from bundesarchiv.persistence.errors import ArchiveError, NotFound
from bundesarchiv.persistence.objectstore import is_reserved, validate_key

_CHUNK = 1024 * 1024  # 1 MiB streaming chunk for put_large
_DAV = "{DAV:}"  # ElementTree Clark notation for the DAV: namespace
_PROPFIND_RESOURCETYPE = (
    b'<?xml version="1.0"?><propfind xmlns="DAV:"><prop><resourcetype/></prop></propfind>'
)


class _Resource(enum.Enum):
    ABSENT = enum.auto()
    FILE = enum.auto()
    COLLECTION = enum.auto()


class WebDavObjectStore:
    """Stores each blob as a WebDAV resource under the client's `base_url`."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client
        self._root_path = urlsplit(str(client.base_url)).path

    def read(self, key: str) -> bytes:
        validate_key(key)
        resp = self._request("GET", self._url(key), follow_redirects=False)
        if resp.status_code == httpx.codes.OK:
            return resp.content
        # Non-200: classify via the same resourcetype probe exists()/delete() use, so
        # absent-vs-collection-vs-error never hinges on a server-specific redirect or
        # on the injected client's follow_redirects policy.
        if self._resourcetype(key) is _Resource.FILE:
            self._ensure(resp, httpx.codes.OK)  # a real blob but GET failed -> ArchiveError
        raise NotFound(key)  # absent, or the key names a collection -> no blob here

    def write_atomic(self, key: str, data: bytes) -> None:
        validate_key(key)
        self._put_then_move(key, data)

    def put_large(self, key: str, stream: BinaryIO, size: int) -> None:
        # `size` is a hint for backends that need it (e.g. chunked upload); the body
        # is streamed straight through here, so it is unused.
        validate_key(key)
        self._put_then_move(key, _iter_chunks(stream))

    def list(self, prefix: str = "") -> Iterable[str]:
        return sorted(key for key in self._walk("") if key.startswith(prefix))

    def exists(self, key: str) -> bool:
        validate_key(key)
        return self._resourcetype(key) is _Resource.FILE

    def delete(self, key: str) -> None:
        validate_key(key)
        # Never recursively delete a collection: a directory-prefix key has no blob.
        if self._resourcetype(key) is not _Resource.FILE:
            return  # absent or a collection — idempotent no-op
        resp = self._request("DELETE", self._url(key))
        if resp.status_code != httpx.codes.NOT_FOUND:
            self._ensure(resp, httpx.codes.OK, httpx.codes.NO_CONTENT)

    def _put_then_move(self, key: str, content: bytes | Iterator[bytes]) -> None:
        self._mkcol_parents(key)
        tmp = self._tmp_key(key)
        put = self._request("PUT", self._url(tmp), content=content)
        self._ensure(put, httpx.codes.CREATED, httpx.codes.NO_CONTENT, httpx.codes.OK)
        destination = str(self._client.base_url.join(self._url(key)))
        move = self._request(
            "MOVE", self._url(tmp), headers={"Destination": destination, "Overwrite": "T"}
        )
        self._ensure(move, httpx.codes.CREATED, httpx.codes.NO_CONTENT, httpx.codes.OK)

    def _mkcol_parents(self, key: str) -> None:
        prefix = ""
        for segment in key.split("/")[:-1]:
            prefix = f"{prefix}/{segment}" if prefix else segment
            resp = self._request("MKCOL", self._url(prefix))
            # 201 created; 405 already exists.
            self._ensure(resp, httpx.codes.CREATED, httpx.codes.METHOD_NOT_ALLOWED)

    def _tmp_key(self, key: str) -> str:
        parent, _, name = key.rpartition("/")
        tmp_name = f".tmp-{uuid.uuid4().hex}-{name}"
        return f"{parent}/{tmp_name}" if parent else tmp_name

    def _walk(self, collection: str) -> Iterator[str]:
        for child, is_collection in self._children(collection):
            if is_reserved(child):
                continue  # reserved keys (temp/lock/snapshots) are never listed
            if is_collection:
                yield from self._walk(child)
            else:
                yield child

    def _children(self, collection: str) -> Iterator[tuple[str, bool]]:
        resp = self._request(
            "PROPFIND",
            self._url(collection),
            headers={"Depth": "1"},
            content=_PROPFIND_RESOURCETYPE,
        )
        if resp.status_code == httpx.codes.NOT_FOUND:
            return
        self._ensure(resp, httpx.codes.MULTI_STATUS)
        for href, is_collection in _parse_multistatus(resp.content):
            key = self._href_to_key(href)
            if key != collection:  # skip the collection's own self-entry
                yield key, is_collection

    def _resourcetype(self, key: str) -> _Resource:
        resp = self._request(
            "PROPFIND", self._url(key), headers={"Depth": "0"}, content=_PROPFIND_RESOURCETYPE
        )
        if resp.status_code == httpx.codes.NOT_FOUND:
            return _Resource.ABSENT
        self._ensure(resp, httpx.codes.MULTI_STATUS)
        entries = list(_parse_multistatus(resp.content))
        if not entries:
            return _Resource.ABSENT  # a Depth:0 207 with no self-entry is anomalous
        return _Resource.COLLECTION if entries[0][1] else _Resource.FILE

    def _url(self, key: str) -> str:
        return "/".join(quote(segment, safe="") for segment in key.split("/"))

    def _href_to_key(self, href: str) -> str:
        path = urlsplit(href).path
        rel = path.removeprefix(self._root_path)
        return "/".join(unquote(seg) for seg in rel.strip("/").split("/") if seg)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            # A down/slow/unreachable mirror is an expected failure mode (ADR 0005);
            # surface it as ArchiveError, never a raw transport exception past the port.
            raise ArchiveError(f"WebDAV {method} {url}: {exc}") from exc

    def _ensure(self, resp: httpx.Response, *ok: int) -> None:
        if resp.status_code not in ok:
            raise ArchiveError(
                f"WebDAV {resp.request.method} {resp.request.url} -> {resp.status_code}"
            )


def _iter_chunks(stream: BinaryIO) -> Iterator[bytes]:
    while chunk := stream.read(_CHUNK):
        yield chunk


def _parse_multistatus(body: bytes) -> Iterator[tuple[str, bool]]:
    root = ElementTree.fromstring(body)
    for response in root.iterfind(f"{_DAV}response"):
        href = response.findtext(f"{_DAV}href")
        if href is None:
            continue
        collection = response.find(f"{_DAV}propstat/{_DAV}prop/{_DAV}resourcetype/{_DAV}collection")
        yield href, collection is not None
