"""What a media file is, and which files are derived from it, decided from its ``MediaRef`` alone."""

from enum import Enum, StrEnum, auto
from pathlib import PurePosixPath

from bundesarchiv.domain.models import MediaRef


class FileKind(StrEnum):
    """The closed set of kinds a record's files are counted by, in the order a summary lists them."""

    IMAGE = "image"
    PDF = "pdf"
    VIDEO = "video"
    AUDIO = "audio"
    OTHER = "other"


class Derived(Enum):
    """A file made from a media file, outside the canonical archive."""

    TILE = auto()
    DISPLAY = auto()
    PAGE_TEXT = auto()


#: A fixed table, not ``mimetypes``: constructing its ``MimeTypes`` runs ``mimetypes.init()``, which
#: reads the host's mime.types files, and the domain does no IO. The values are the stdlib's built-in
#: ones.
_MIME_BY_EXTENSION = {
    **dict.fromkeys((".jpg", ".jpeg", ".jpe"), "image/jpeg"),
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    **dict.fromkeys((".tif", ".tiff"), "image/tiff"),
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".avif": "image/avif",
    ".jp2": "image/jp2",
    ".jpm": "image/jpm",
    ".jpx": "image/jpx",
    ".ico": "image/vnd.microsoft.icon",
    ".emf": "image/emf",
    ".wmf": "image/wmf",
    ".fits": "image/fits",
    ".g3": "image/g3fax",
    ".ief": "image/ief",
    ".t38": "image/t38",
    ".tfx": "image/tiff-fx",
    ".pbm": "image/x-portable-bitmap",
    ".pgm": "image/x-portable-graymap",
    ".pnm": "image/x-portable-anymap",
    ".ppm": "image/x-portable-pixmap",
    ".ras": "image/x-cmu-raster",
    ".rgb": "image/x-rgb",
    ".xbm": "image/x-xbitmap",
    ".xpm": "image/x-xpixmap",
    ".xwd": "image/x-xwindowdump",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    **dict.fromkeys((".mov", ".qt"), "video/quicktime"),
    ".avi": "video/vnd.avi",
    ".mkv": "video/matroska",
    ".mk3d": "video/matroska-3d",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    **dict.fromkeys((".mpeg", ".mpg", ".mpe", ".m1v", ".mpa"), "video/mpeg"),
    ".wmv": "video/x-ms-wmv",
    ".movie": "video/x-sgi-movie",
    **dict.fromkeys((".mp3", ".mp2"), "audio/mpeg"),
    ".wav": "audio/vnd.wave",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    **dict.fromkeys((".aac", ".adts", ".loas", ".ass"), "audio/aac"),
    **dict.fromkeys((".aif", ".aiff", ".aifc"), "audio/x-aiff"),
    **dict.fromkeys((".au", ".snd"), "audio/basic"),
    **dict.fromkeys((".3gp", ".3gpp"), "audio/3gpp"),
    **dict.fromkeys((".3g2", ".3gpp2"), "audio/3gpp2"),
    ".mka": "audio/matroska",
    ".weba": "audio/webm",
    ".ra": "audio/x-pn-realaudio",
    ".txt": "text/plain",
    ".csv": "text/csv",
    **dict.fromkeys((".html", ".htm"), "text/html"),
    ".rtf": "text/rtf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".zip": "application/zip",
}
_KIND_BY_MAJOR = {"image": FileKind.IMAGE, "video": FileKind.VIDEO, "audio": FileKind.AUDIO}

#: A PDF opens in a new tab, so only an image has a display version; text is read from PDFs only
#: (ADR 0023).
_DERIVED: dict[FileKind, frozenset[Derived]] = {
    FileKind.IMAGE: frozenset({Derived.TILE, Derived.DISPLAY}),
    FileKind.PDF: frozenset({Derived.TILE, Derived.PAGE_TEXT}),
}


def mime_type(ref: MediaRef) -> str:
    """One file's MIME type: as recorded, else the one its name's extension implies; ``""`` when
    neither says."""
    return (
        ref.media_type or _MIME_BY_EXTENSION.get(PurePosixPath(ref.filename).suffix.lower(), "")
    ).lower()


def file_kind(ref: MediaRef) -> FileKind:
    """The kind of one file by its ``mime_type``; anything unrecognised is ``OTHER``."""
    mime = mime_type(ref)
    if mime == "application/pdf":
        return FileKind.PDF
    return _KIND_BY_MAJOR.get(mime.partition("/")[0], FileKind.OTHER)


def derivations(ref: MediaRef) -> frozenset[Derived]:
    """The files made from ``ref``'s file, by its kind."""
    return _DERIVED.get(file_kind(ref), frozenset())
