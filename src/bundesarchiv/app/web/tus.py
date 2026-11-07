"""The chunked upload's protocol, tus 1.0.0 core and creation (ADR 0026): what a request asks,
read from its method and headers alone, and the answers the protocol gives."""

import base64
import binascii
import functools
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from django.utils.http import parse_header_parameters

from bundesarchiv.app import media
from bundesarchiv.app.upload_staging import Refused

VERSION = "1.0.0"

_PIECE = "application/offset+octet-stream"

_DIGITS = re.compile(r"[0-9]+")


@dataclass(frozen=True, slots=True)
class Create:
    """Stage a file of ``length`` bytes; ``filetype`` as the client named it."""

    length: int
    filename: str
    filetype: str | None


@dataclass(frozen=True, slots=True)
class Head:
    """Ask an upload's offset."""


@dataclass(frozen=True, slots=True)
class Append:
    """Append the body, ``size`` bytes, at ``offset``."""

    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class Delete:
    """Drop an upload."""


@dataclass(frozen=True, slots=True)
class Refusal:
    """A request the protocol refuses by its headers, answered with ``status``."""

    status: int

    def response(self) -> HttpResponse:
        headers = {"Tus-Version": VERSION} if self == UNSUPPORTED else None
        return HttpResponse(status=self.status, headers=headers)


#: Another protocol version, or none.
UNSUPPORTED = Refusal(412)

_MALFORMED = Refusal(400)

type Request = Create | Head | Append | Delete | Refusal


def read(method: str | None, headers: Mapping[str, str]) -> Request | None:
    """What a request asks; None for a method tus does not speak. ``headers`` as Django's
    ``request.headers`` gives them, ``Content-Type`` and ``Content-Length`` included."""
    if method is None or (reader := _READERS.get(method)) is None:
        return None
    if headers.get("Tus-Resumable") != VERSION:
        return UNSUPPORTED
    return reader(headers)


def _create(headers: Mapping[str, str]) -> Create | Refusal:
    length = _count(headers.get("Upload-Length"))
    metadata = _metadata(headers.get("Upload-Metadata", ""))
    filename = metadata.get("filename")
    if length is None or filename is None:
        return _MALFORMED
    return Create(length, filename, metadata.get("filetype"))


def _append(headers: Mapping[str, str]) -> Append | Refusal:
    content_type, _ = parse_header_parameters(headers.get("Content-Type", ""))
    if content_type != _PIECE:
        return Refusal(415)
    offset = _count(headers.get("Upload-Offset"))
    size = _count(headers.get("Content-Length"))
    if offset is None or size is None:
        return _MALFORMED
    return Append(offset, size)


_READERS: dict[str, Callable[[Mapping[str, str]], Request]] = {
    "POST": _create,
    "PATCH": _append,
    "HEAD": lambda _: Head(),
    "DELETE": lambda _: Delete(),
}


def _count(raw: str | None) -> int | None:
    """A header's non-negative integer, ASCII digits only; None for any other shape. Beyond 19
    digits it is past every length and offset here and reads as 10**19 (``int`` refuses past
    4300 digits)."""
    if raw is None or not _DIGITS.fullmatch(raw):
        return None
    digits = raw.lstrip("0")
    return int(digits or "0") if len(digits) <= 19 else 10**19


def _metadata(raw: str) -> dict[str, str]:
    """``Upload-Metadata``'s comma-separated ``key base64-value`` pairs (a key alone: an empty
    value), each value decoded as UTF-8; empty when any pair is malformed or a key repeats."""
    pairs: dict[str, str] = {}
    for item in raw.split(","):
        key, _, value = item.strip().partition(" ")
        if not key or key in pairs:
            return {}
        try:
            pairs[key] = base64.b64decode(value, validate=True).decode()
        except binascii.Error, UnicodeDecodeError:
            return {}
    return pairs


_INADMISSIBLE = {media.Refusal.NAMELESS: 400, media.Refusal.TOO_LARGE: 413}

_APPEND_REFUSED = {Refused.OFFSET: 409, Refused.TOO_LONG: 413}


def refused(admission: media.Refusal) -> HttpResponse:
    """A create's answer for a file the archive does not admit."""
    return HttpResponse(status=_INADMISSIBLE[admission])


def created(location: str) -> HttpResponse:
    return HttpResponse(status=201, headers={"Location": location})


def appended(outcome: int | Literal[Refused.OFFSET, Refused.TOO_LONG]) -> HttpResponse:
    """A PATCH's answer: the offset after the piece, or why the piece was refused."""
    if isinstance(outcome, int):
        return HttpResponse(status=204, headers={"Upload-Offset": str(outcome)})
    return HttpResponse(status=_APPEND_REFUSED[outcome])


def progress(offset: int, length: int) -> HttpResponse:
    """A HEAD's answer."""
    headers = {"Upload-Offset": str(offset), "Upload-Length": str(length)}
    return HttpResponse(status=200, headers={**headers, "Cache-Control": "no-store"})


def versioned(view: Callable[..., HttpResponseBase]) -> Callable[..., HttpResponseBase]:
    """Every answer of ``view`` names the protocol version, its 404 included."""

    @functools.wraps(view)
    def answered(request: HttpRequest, **kwargs: str) -> HttpResponseBase:
        response = view(request, **kwargs)
        response["Tus-Resumable"] = VERSION
        return response

    return answered
