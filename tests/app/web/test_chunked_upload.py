"""The chunked upload over HTTP (ADR 0026): tus 1.0.0 pieces into staging, the finish into the
Article, every miss the plain 404."""

import base64
import fcntl
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from django.test import Client
from tests.app.web._asserts import assert_denied
from tests.app.web._fixtures import DRAFT_ULID, PUBLISHED_ULID, Corpus, client_as
from tests.app.web._tus import (
    PIECE,
    TUS,
    create,
    finish,
    metadata,
    patch,
    staged,
    staging_at,
    upload_id,
    upload_url,
)

from bundesarchiv.app import articles as article_services
from bundesarchiv.app import tasks
from bundesarchiv.app.result import Conflicted
from bundesarchiv.app.upload_staging import Key, Staging
from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer

_ANNA = Archivist("anna")
_DATA = b"%PDF-1.4 zwei Stuecke"


@pytest.fixture
def staging_root(corpus: Corpus, tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "staging"
    with staging_at(root):
        yield root


def _staged_ids(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def _media(corpus: Corpus) -> tuple[Any, ...]:
    return corpus.articles.load(DRAFT_ULID).article.media


#: Django masks its CSRF token anew on every render.
_CSRF_TOKEN = re.compile(rb'(X-CSRFToken": "|name="csrfmiddlewaretoken" value=")[^"]+')


def _masked(page: bytes) -> bytes:
    return _CSRF_TOKEN.sub(rb"\1", page)


def _freed(root: Path, upload: str) -> bool:
    return (root / upload / "data").stat().st_size == 0


# --- the round trip -------------------------------------------------------------------------


def test_pieces_in_then_the_finish_stores_the_file_and_frees_the_staging(
    corpus: Corpus, staging_root: Path
) -> None:
    client = client_as(_ANNA)
    created = client.post(
        f"/articles/{DRAFT_ULID}/media/uploads",
        headers={
            **TUS,
            "Upload-Length": str(len(_DATA)),
            "Upload-Metadata": metadata(filename="Brief, 1962.pdf", filetype="application/pdf"),
        },
    )
    assert created.status_code == 201
    upload = upload_id(created)
    first = patch(client, DRAFT_ULID, upload, 0, _DATA[:8])
    assert (first.status_code, first["Upload-Offset"]) == (204, "8")
    head = client.head(upload_url(DRAFT_ULID, upload), headers=TUS)
    assert (head.status_code, head["Upload-Offset"], head["Upload-Length"]) == (
        200,
        "8",
        str(len(_DATA)),
    )
    assert head["Cache-Control"] == "no-store"
    rest = patch(client, DRAFT_ULID, upload, 8, _DATA[8:])
    assert (rest.status_code, rest["Upload-Offset"]) == (204, str(len(_DATA)))
    assert all(r["Tus-Resumable"] == "1.0.0" for r in (created, first, head, rest))

    finished = finish(client, DRAFT_ULID, upload)

    assert finished.status_code == 200
    ref = _media(corpus)[-1]
    assert (ref.filename, ref.media_type) == ("Brief, 1962.pdf", "application/pdf")
    with corpus.articles.open_media(DRAFT_ULID, ref) as stored:
        assert stored.read() == _DATA
    assert _freed(staging_root, upload)


def test_a_repeated_finish_answers_as_the_first_and_saves_nothing(
    corpus: Corpus, staging_root: Path
) -> None:
    """The first answer was lost on the way (ADR 0026 "Finish per file")."""
    client = client_as(_ANNA)
    upload = staged(client, DRAFT_ULID, _DATA)
    version = corpus.articles.load(DRAFT_ULID).version
    first = finish(client, DRAFT_ULID, upload, expected_version=str(version))
    keys = corpus.articles.keys_for(DRAFT_ULID)

    again = finish(client, DRAFT_ULID, upload, expected_version=str(version))

    assert (first.status_code, again.status_code) == (200, 200)
    assert _masked(again.content) == _masked(first.content)
    assert corpus.articles.keys_for(DRAFT_ULID) == keys
    assert [ref.filename for ref in _media(corpus)] == ["scan.pdf"]


def test_a_finished_upload_resumes_straight_to_the_finish(
    corpus: Corpus, staging_root: Path
) -> None:
    client = client_as(_ANNA)
    upload = staged(client, DRAFT_ULID, _DATA)
    assert finish(client, DRAFT_ULID, upload).status_code == 200
    head = client.head(upload_url(DRAFT_ULID, upload), headers=TUS)
    assert (head.status_code, head["Upload-Offset"], head["Upload-Length"]) == (
        200,
        str(len(_DATA)),
        str(len(_DATA)),
    )
    assert patch(client, DRAFT_ULID, upload, 0, _DATA).status_code == 409
    assert _freed(staging_root, upload)


def test_two_uploads_of_one_file_list_it_once(corpus: Corpus, staging_root: Path) -> None:
    client = client_as(_ANNA)
    for _ in range(2):
        assert finish(client, DRAFT_ULID, staged(client, DRAFT_ULID, _DATA)).status_code == 200
    assert [ref.filename for ref in _media(corpus)] == ["scan.pdf"]


def test_the_finish_of_an_incomplete_upload_saves_nothing(
    corpus: Corpus, staging_root: Path
) -> None:
    client = client_as(_ANNA)
    upload = staged(client, DRAFT_ULID, _DATA[:8], length=len(_DATA))
    keys = corpus.articles.keys_for(DRAFT_ULID)
    assert_denied(finish(client, DRAFT_ULID, upload))
    assert corpus.articles.keys_for(DRAFT_ULID) == keys
    assert _staged_ids(staging_root) == [upload]


def test_a_finish_that_saves_nothing_keeps_the_upload_for_the_next_finish(
    corpus: Corpus, staging_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Article goes to the Papierkorb while the finish waits on the upload's lock."""
    client = client_as(_ANNA)
    upload = staged(client, DRAFT_ULID, _DATA)
    flock = fcntl.flock

    def deleted_meanwhile(file: Any, operation: int) -> None:
        flock(file, operation)
        stored = corpus.articles.load(DRAFT_ULID)
        corpus.articles.mark_deleted(stored.article, stored.version, changed_by="bert")

    with monkeypatch.context() as patched:
        patched.setattr(fcntl, "flock", deleted_meanwhile)
        assert_denied(finish(client, DRAFT_ULID, upload))
    assert _staged_ids(staging_root) == [upload]
    stored = corpus.articles.load(DRAFT_ULID)
    corpus.articles.save(replace(stored.article, deleted=None), stored.version, changed_by="bert")

    assert finish(client, DRAFT_ULID, upload).status_code == 200
    assert [ref.filename for ref in _media(corpus)] == ["scan.pdf"]
    assert _freed(staging_root, upload)


def test_a_finish_that_loses_every_save_race_answers_for_a_repeat(
    corpus: Corpus, staging_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lost race is no landed file: the client sends the finish again (ADR 0026)."""
    client = client_as(_ANNA)
    upload = staged(client, DRAFT_ULID, _DATA)
    with monkeypatch.context() as patched:
        patched.setattr(article_services, "update_article", lambda *_, **__: Conflicted())
        assert finish(client, DRAFT_ULID, upload).status_code == 503
    assert _media(corpus) == ()

    assert finish(client, DRAFT_ULID, upload).status_code == 200
    assert [ref.filename for ref in _media(corpus)] == ["scan.pdf"]
    assert _freed(staging_root, upload)


@pytest.mark.parametrize("finished", [False, True])
def test_a_delete_drops_the_upload(corpus: Corpus, staging_root: Path, finished: bool) -> None:
    client = client_as(_ANNA)
    upload = staged(client, DRAFT_ULID, _DATA)
    if finished:
        assert finish(client, DRAFT_ULID, upload).status_code == 200
    assert client.delete(upload_url(DRAFT_ULID, upload), headers=TUS).status_code == 204
    assert _staged_ids(staging_root) == []


def test_a_filetype_that_is_no_media_type_is_dropped(corpus: Corpus, staging_root: Path) -> None:
    """It is served back as a Content-Type header, where a line break would break every answer."""
    client = client_as(_ANNA)
    created = client.post(
        f"/articles/{DRAFT_ULID}/media/uploads",
        headers={
            **TUS,
            "Upload-Length": "0",
            "Upload-Metadata": metadata(filename="a.pdf", filetype="text/html\r\nX-Evil: 1"),
        },
    )
    staged_upload = Staging(staging_root).status(Key(upload_id(created), "anna", DRAFT_ULID))
    assert staged_upload is not None and staged_upload[0].media_type is None


# --- every invalid header shape answers its tus status and stores nothing --------------------


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


_FILENAME = metadata(filename="scan.pdf")


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        pytest.param({"Upload-Length": "6", "Upload-Metadata": _FILENAME}, 412, id="no-version"),
        pytest.param(
            {**TUS, "Tus-Resumable": "0.2.2", "Upload-Length": "6", "Upload-Metadata": _FILENAME},
            412,
            id="old-version",
        ),
        *(
            pytest.param({**TUS, "Upload-Length": length, "Upload-Metadata": _FILENAME}, 400, id=k)
            for k, length in {
                "length-empty": "",
                "length-signed": "-6",
                "length-plus": "+6",
                "length-fraction": "6.0",
                "length-hex": "0x6",
                "length-spaced": "6 ",
                "length-two": "6, 6",
                "length-arabic-digits": "\N{ARABIC-INDIC DIGIT SIX}",
            }.items()
        ),
        pytest.param({**TUS, "Upload-Metadata": _FILENAME}, 400, id="length-missing"),
        pytest.param(
            {**TUS, "Upload-Length": "9" * 5000, "Upload-Metadata": _FILENAME},
            413,
            id="length-overflow",
        ),
        pytest.param(
            {**TUS, "Upload-Length": str(4 * 1024**3 + 1), "Upload-Metadata": _FILENAME},
            413,
            id="length-over-ceiling",
        ),
        *(
            pytest.param({**TUS, "Upload-Length": "6", "Upload-Metadata": meta}, 400, id=k)
            for k, meta in {
                "metadata-empty": "",
                "metadata-bad-base64": "filename !!!",
                "metadata-unpadded": f"filename {_b64(b'scan.pdf').rstrip('=')}",
                "metadata-not-utf8": f"filename {_b64(b'\xff\xfe')}",
                "metadata-no-filename": f"filetype {_b64(b'application/pdf')}",
                "metadata-filename-twice": f"{_FILENAME},{_FILENAME}",
                "metadata-trailing-comma": f"{_FILENAME},",
                "filename-cleans-to-nothing": f"filename {_b64(b' . ')}",
                "filename-empty": "filename",
            }.items()
        ),
        pytest.param({**TUS, "Upload-Length": "6"}, 400, id="metadata-missing"),
    ],
)
def test_a_create_with_an_invalid_header_stages_nothing(
    corpus: Corpus, staging_root: Path, headers: dict[str, str], status: int
) -> None:
    response = client_as(_ANNA).post(f"/articles/{DRAFT_ULID}/media/uploads", headers=headers)
    assert response.status_code == status
    assert _staged_ids(staging_root) == []


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        pytest.param({"headers": {"Upload-Offset": "3"}}, 412, id="no-version"),
        pytest.param({"content_type": "application/octet-stream"}, 415, id="content-type"),
        pytest.param({"headers": TUS}, 400, id="offset-missing"),
        *(
            pytest.param({"headers": {**TUS, "Upload-Offset": offset}}, 400, id=k)
            for k, offset in {
                "offset-signed": "-3",
                "offset-fraction": "3.0",
                "offset-word": "drei",
                "offset-empty": "",
            }.items()
        ),
        pytest.param({"CONTENT_LENGTH": "viele"}, 400, id="content-length-word"),
        pytest.param({"headers": {**TUS, "Upload-Offset": "0"}}, 409, id="offset-behind"),
        pytest.param({"headers": {**TUS, "Upload-Offset": "4"}}, 409, id="offset-ahead"),
        pytest.param({"headers": {**TUS, "Upload-Offset": "9" * 5000}}, 409, id="offset-overflow"),
        pytest.param({"body": b"defg"}, 413, id="past-the-length"),
    ],
)
def test_a_refused_piece_leaves_the_bytes_as_they_were(
    corpus: Corpus, staging_root: Path, kwargs: dict[str, Any], status: int
) -> None:
    client = client_as(_ANNA)
    upload = staged(client, DRAFT_ULID, b"abc", length=6)
    request: dict[str, Any] = {
        "body": b"def",
        "content_type": PIECE,
        "headers": {**TUS, "Upload-Offset": "3"},
        **kwargs,
    }
    url = upload_url(DRAFT_ULID, upload)
    extra = {k: v for k, v in request.items() if k.isupper()}
    response = client.generic(
        "PATCH",
        url,
        request["body"],
        content_type=request["content_type"],
        headers=request["headers"],
        **extra,
    )
    assert response.status_code == status
    assert client.head(url, headers=TUS)["Upload-Offset"] == "3"
    assert patch(client, DRAFT_ULID, upload, 3, b"def").status_code == 204
    assert finish(client, DRAFT_ULID, upload).status_code == 200
    with corpus.articles.open_media(DRAFT_ULID, _media(corpus)[-1]) as stored:
        assert stored.read() == b"abcdef"


# --- the deny contract: every miss is the plain 404 and changes nothing ------------------------


def _head(client: Client, ulid: str, upload: str) -> Any:
    return client.head(upload_url(ulid, upload), headers=TUS)


def _patch(client: Client, ulid: str, upload: str) -> Any:
    return patch(client, ulid, upload, len(_DATA), b"")


def _delete(client: Client, ulid: str, upload: str) -> Any:
    return client.delete(upload_url(ulid, upload), headers=TUS)


#: Each answers the owner on its Article something other than the 404 (200, 204, 204, 200).
_PROBES: dict[str, Callable[[Client, str, str], Any]] = {
    "HEAD": _head,
    "PATCH": _patch,
    "DELETE": _delete,
    "finish": finish,
}


def _assert_tus_denied(response: Any, method: str) -> None:
    if method == "HEAD":  # a HEAD answer has no body to carry the 404 page
        assert (response.status_code, response.content) == (404, b"")
    else:
        assert_denied(response, method)


_MISSES: dict[str, tuple[Viewer | None, str, Callable[[str], str]]] = {
    "anonymous": (None, DRAFT_ULID, str),
    "public": (Public(), DRAFT_ULID, str),
    "member": (Member(groups=("vorstand",)), DRAFT_ULID, str),
    "foreign-owner": (Archivist("bert"), DRAFT_ULID, str),
    "foreign-article": (_ANNA, PUBLISHED_ULID, str),
    "unknown-id": (_ANNA, DRAFT_ULID, lambda _: "0" * 32),
    "malformed-upper": (_ANNA, DRAFT_ULID, str.upper),
    "malformed-long": (_ANNA, DRAFT_ULID, lambda u: f"{u}0"),
    "malformed-short": (_ANNA, DRAFT_ULID, lambda u: u[:-1]),
    "malformed-dots": (_ANNA, DRAFT_ULID, lambda _: ".."),
    "malformed-article": (_ANNA, "not-a-ulid", str),
}


@pytest.mark.parametrize("method", _PROBES)
@pytest.mark.parametrize("miss", _MISSES)
def test_a_miss_is_the_plain_404_and_changes_nothing(
    corpus: Corpus, staging_root: Path, miss: str, method: str
) -> None:
    upload = staged(client_as(_ANNA), DRAFT_ULID, _DATA)
    viewer, ulid, address = _MISSES[miss]
    keys = corpus.articles.keys_for(DRAFT_ULID)
    _assert_tus_denied(_PROBES[method](client_as(viewer), ulid, address(upload)), method)
    assert corpus.articles.keys_for(DRAFT_ULID) == keys
    assert _head(client_as(_ANNA), DRAFT_ULID, upload)["Upload-Offset"] == str(len(_DATA))


@pytest.mark.parametrize("method", _PROBES)
@pytest.mark.parametrize("miss", _MISSES)
def test_a_miss_on_a_finished_upload_is_the_plain_404_and_changes_nothing(
    corpus: Corpus, staging_root: Path, miss: str, method: str
) -> None:
    client = client_as(_ANNA)
    upload = staged(client, DRAFT_ULID, _DATA)
    assert finish(client, DRAFT_ULID, upload).status_code == 200
    viewer, ulid, address = _MISSES[miss]
    keys = corpus.articles.keys_for(DRAFT_ULID)
    _assert_tus_denied(_PROBES[method](client_as(viewer), ulid, address(upload)), method)
    assert corpus.articles.keys_for(DRAFT_ULID) == keys
    assert _head(client, DRAFT_ULID, upload)["Upload-Offset"] == str(len(_DATA))


@pytest.mark.parametrize("viewer", [None, Public(), Member(groups=("vorstand",)), Archivist()])
def test_a_create_by_a_non_archivist_or_on_an_absent_article_stages_nothing(
    corpus: Corpus, staging_root: Path, viewer: Viewer | None
) -> None:
    ulid = "01KX7YT9E3VX0CP3A5Q49RZMZZ" if isinstance(viewer, Archivist) else DRAFT_ULID
    assert_denied(create(client_as(viewer), ulid, 6))
    assert _staged_ids(staging_root) == []


@pytest.mark.parametrize("finished", [False, True])
@pytest.mark.parametrize("method", _PROBES)
def test_an_expired_upload_is_the_plain_404(
    corpus: Corpus, staging_root: Path, method: str, finished: bool
) -> None:
    upload = staged(client_as(_ANNA), DRAFT_ULID, _DATA)
    if finished:
        assert finish(client_as(_ANNA), DRAFT_ULID, upload).status_code == 200
    now = int(time.time())
    a_day_ago = now - 25 * 60 * 60
    for path in (staging_root / upload).iterdir():
        os.utime(path, (a_day_ago, a_day_ago))
    tasks.sweep.func(now)
    keys = corpus.articles.keys_for(DRAFT_ULID)
    _assert_tus_denied(_PROBES[method](client_as(_ANNA), DRAFT_ULID, upload), method)
    assert corpus.articles.keys_for(DRAFT_ULID) == keys


# --- nginx: the tus routes sit behind the gate, with a body bound for one piece ---------------


def test_the_tus_location_gates_both_routes_and_takes_one_piece() -> None:
    conf = (Path(__file__).parents[3] / "deploy/nginx/nginx.conf").read_text()
    found = re.search(r'location ~ "(\^/[^"]*media/uploads[^"]*)" \{([^}]*)\}', conf)
    assert found is not None
    regex = re.compile(found[1].replace("(?<", "(?P<"))
    upload = "0123456789abcdef0123456789abcdef"
    assert regex.match(f"/articles/{DRAFT_ULID}/media/uploads")
    assert regex.match(f"/articles/{DRAFT_ULID}/media/uploads/{upload}")
    assert not regex.match(f"/articles/{DRAFT_ULID}/media/upload")
    assert "auth_request /_upload_gate;" in found[2]
    assert "client_max_body_size 16m;" in found[2]
