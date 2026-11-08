"""The tus request grammar (ADR 0026): the header shapes a client can send, read without a
client or a corpus; a refusal the HTTP suite sends is proven there alone."""

import base64
from collections.abc import Callable

import pytest
from tests.app.web._tus import PIECE, TUS, metadata

from bundesarchiv.app.web import tus


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


_FILENAME = metadata(filename="scan.pdf")
_CREATE = {**TUS, "Upload-Length": "6", "Upload-Metadata": _FILENAME}
_APPEND = {**TUS, "Content-Type": PIECE, "Upload-Offset": "3", "Content-Length": "3"}
_MALFORMED = tus.Refusal(400)


@pytest.mark.parametrize(
    ("method", "headers", "read"),
    [
        pytest.param("POST", _CREATE, tus.Create(6, "scan.pdf", None), id="create"),
        pytest.param(
            "POST",
            {**_CREATE, "Upload-Metadata": metadata(filename="a.pdf", filetype="application/pdf")},
            tus.Create(6, "a.pdf", "application/pdf"),
            id="create-filetype",
        ),
        pytest.param("PATCH", _APPEND, tus.Append(3, 3), id="append"),
        pytest.param(
            "PATCH",
            {**_APPEND, "Content-Type": f"{PIECE}; charset=utf-8"},
            tus.Append(3, 3),
            id="append-type-parameter",
        ),
        pytest.param("HEAD", TUS, tus.Head(), id="head"),
        pytest.param("DELETE", TUS, tus.Delete(), id="delete"),
        pytest.param("GET", TUS, None, id="get"),
        pytest.param("OPTIONS", TUS, None, id="options"),
        pytest.param(None, TUS, None, id="no-method"),
        *(
            pytest.param(
                method, {**TUS, **headers, "Tus-Resumable": version}, tus.UNSUPPORTED, id=k
            )
            for method, headers in {
                "POST": _CREATE,
                "PATCH": _APPEND,
                "HEAD": {},
                "DELETE": {},
            }.items()
            for k, version in {
                f"{method}-old-version": "0.2.2",
                f"{method}-empty-version": "",
            }.items()
        ),
        pytest.param(
            "PATCH",
            {k: v for k, v in _APPEND.items() if k != "Content-Type"},
            tus.Refusal(415),
            id="content-type-missing",
        ),
        pytest.param(
            "POST",
            {k: v for k, v in _CREATE.items() if k != "Upload-Metadata"},
            _MALFORMED,
            id="metadata-missing",
        ),
        pytest.param(
            "PATCH",
            {k: v for k, v in _APPEND.items() if k != "Content-Length"},
            _MALFORMED,
            id="content-length-missing",
        ),
        *(
            pytest.param("POST", {**_CREATE, "Upload-Metadata": meta}, _MALFORMED, id=k)
            for k, meta in {
                "metadata-empty": "",
                "metadata-bad-base64": "filename !!!",
                "metadata-unpadded": f"filename {_b64(b'scan.pdf').rstrip('=')}",
                "metadata-not-utf8": f"filename {_b64(b'\xff\xfe')}",
                "metadata-no-filename": f"filetype {_b64(b'application/pdf')}",
                "metadata-filename-twice": f"{_FILENAME},{_FILENAME}",
                "metadata-trailing-comma": f"{_FILENAME},",
            }.items()
        ),
        pytest.param(
            "POST",
            {**_CREATE, "Upload-Metadata": "filename"},
            tus.Create(6, "", None),
            id="filename-key-alone",
        ),
        pytest.param(
            "POST",
            {**_CREATE, "Upload-Metadata": f"  {_FILENAME} , filetype {_b64(b'text/plain')}"},
            tus.Create(6, "scan.pdf", "text/plain"),
            id="metadata-spaced-pairs",
        ),
    ],
)
def test_a_request_reads_as_what_its_method_and_headers_ask(
    method: str | None, headers: dict[str, str], read: tus.Request | None
) -> None:
    assert tus.read(method, headers) == read


#: Each number header, in the request that carries it.
_COUNTS: dict[str, tuple[str, dict[str, str], Callable[[int], tus.Request]]] = {
    "Upload-Length": ("POST", _CREATE, lambda n: tus.Create(n, "scan.pdf", None)),
    "Upload-Offset": ("PATCH", _APPEND, lambda n: tus.Append(n, 3)),
    "Content-Length": ("PATCH", _APPEND, lambda n: tus.Append(3, n)),
}


@pytest.mark.parametrize("header", _COUNTS)
@pytest.mark.parametrize(
    "raw",
    [
        "",
        "-6",
        "+6",
        "6.0",
        "0x6",
        "6 ",
        " 6",
        "6, 6",
        "sechs",
        "\N{ARABIC-INDIC DIGIT SIX}",
        "\N{FULLWIDTH DIGIT SIX}",
    ],
)
def test_a_number_header_of_any_other_shape_than_digits_is_malformed(header: str, raw: str) -> None:
    method, headers, _ = _COUNTS[header]
    assert tus.read(method, {**headers, header: raw}) == _MALFORMED


@pytest.mark.parametrize("header", _COUNTS)
@pytest.mark.parametrize(
    ("raw", "count"),
    [
        ("0", 0),
        ("000", 0),
        ("0006", 6),
        ("9" * 19, 10**19 - 1),
        ("1" + "0" * 19, 10**19),
        ("9" * 5000, 10**19),
    ],
)
def test_a_number_header_reads_as_its_count_capped_past_every_length(
    header: str, raw: str, count: int
) -> None:
    method, headers, expected = _COUNTS[header]
    assert tus.read(method, {**headers, header: raw}) == expected(count)


@pytest.mark.parametrize(
    "filename",
    [
        "Brief, 1962.pdf",
        "a b.pdf",
        " leading and trailing ",
        "100%.pdf",
        "%2C.pdf",
        "Grüße \N{EN DASH} ß.pdf",
        "\N{CJK UNIFIED IDEOGRAPH-6587}.pdf",
        "=.pdf",
        ",",
        " ",
        "",
    ],
)
def test_a_filename_the_client_encodes_reads_back_unchanged(filename: str) -> None:
    headers = {**_CREATE, "Upload-Metadata": metadata(filename=filename, filetype="a, b")}
    assert tus.read("POST", headers) == tus.Create(6, filename, "a, b")


def test_the_unsupported_version_answer_names_the_one_spoken() -> None:
    response = tus.UNSUPPORTED.response()
    assert (response.status_code, response["Tus-Version"]) == (412, tus.VERSION)
    assert not tus.Refusal(400).response().has_header("Tus-Version")
