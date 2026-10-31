"""The staging store of chunked uploads (ADR 0026): what lands, what is refused, who sees it."""

import io
import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

import pytest
from django.test import override_settings

from bundesarchiv.app import tasks
from bundesarchiv.app.upload_staging import STALE_AFTER_SECONDS, Key, Refused, Staging, Upload

_ARTICLE = "01KX7YT9E3VX0CP3A5Q49RZMVH"
_UPLOAD = Upload(_ARTICLE, "anna", "scan.pdf", "application/pdf", 6)


def _staged(root: Path, upload: Upload = _UPLOAD) -> tuple[Staging, Key]:
    staging = Staging(root)
    return staging, Key(staging.create(upload), upload.owner, upload.article)


def _bytes(root: Path, key: Key) -> bytes:
    return (root / key.upload_id / "data").read_bytes()


@pytest.mark.parametrize(
    "filename",
    [
        "a,b.pdf",
        '"quoted" \\ back.pdf',
        "",
        "   lead and trail   ",
        "Ümläut 日本 \N{EMOJI MODIFIER FITZPATRICK TYPE-1-2}.pdf",
        "100%.pdf",
        "line\nbreak\x00nul.pdf",
        "../../escape",
    ],
)
def test_an_upload_reads_back_as_it_was_staged(tmp_path: Path, filename: str) -> None:
    upload = Upload(_ARTICLE, "an,na \N{EN DASH}", filename, None, 0)
    staging, key = _staged(tmp_path, upload)
    assert staging.status(key) == (upload, 0)


def test_pieces_append_in_order_up_to_the_length(tmp_path: Path) -> None:
    staging, key = _staged(tmp_path)
    assert staging.append(key, 0, io.BytesIO(b"abc"), 3) == 3
    assert staging.append(key, 3, io.BytesIO(b"def"), 3) == 6
    assert staging.status(key) == (_UPLOAD, 6)
    assert _bytes(tmp_path, key) == b"abcdef"


@pytest.mark.parametrize("offset", [0, 2, 4])
def test_an_append_at_another_offset_writes_nothing(tmp_path: Path, offset: int) -> None:
    staging, key = _staged(tmp_path)
    staging.append(key, 0, io.BytesIO(b"abc"), 3)
    assert staging.append(key, offset, io.BytesIO(b"x"), 1) is Refused.OFFSET
    assert _bytes(tmp_path, key) == b"abc"


def test_an_append_past_the_length_writes_nothing(tmp_path: Path) -> None:
    staging, key = _staged(tmp_path)
    staging.append(key, 0, io.BytesIO(b"abc"), 3)
    assert staging.append(key, 3, io.BytesIO(b"defg"), 4) is Refused.TOO_LONG
    assert _bytes(tmp_path, key) == b"abc"


def test_a_source_that_ends_early_leaves_what_it_gave(tmp_path: Path) -> None:
    staging, key = _staged(tmp_path)
    assert staging.append(key, 0, io.BytesIO(b"ab"), 5) == 2
    assert staging.status(key) == (_UPLOAD, 2)


class _Held:
    """A source whose first read waits until released, so its append holds the upload."""

    def __init__(self, data: bytes) -> None:
        self.inside = threading.Event()
        self.release = threading.Event()
        self._data = io.BytesIO(data)

    def read(self, size: int, /) -> bytes:
        self.inside.set()
        assert self.release.wait(5)
        return self._data.read(size)


def test_two_appends_racing_at_one_offset_land_once(tmp_path: Path) -> None:
    staging, key = _staged(tmp_path)
    first = _Held(b"aaa")
    results: dict[str, int | Refused] = {}
    second_done = threading.Event()

    def run_first() -> None:
        results["first"] = staging.append(key, 0, first, 3)

    def run_second() -> None:
        results["second"] = Staging(tmp_path).append(key, 0, io.BytesIO(b"bbb"), 3)
        second_done.set()

    threads = [threading.Thread(target=run_first), threading.Thread(target=run_second)]
    threads[0].start()
    assert first.inside.wait(5)
    threads[1].start()
    assert not second_done.wait(0.2), "the second append ran while the first held the upload"
    first.release.set()
    for thread in threads:
        thread.join(5)
    assert results == {"first": 3, "second": Refused.OFFSET}
    assert _bytes(tmp_path, key) == b"aaa"


@pytest.mark.parametrize(
    "key",
    [
        Key("unknown", "anna", _ARTICLE),
        Key("0" * 32, "anna", _ARTICLE),
    ],
)
def test_an_unknown_upload_is_absent(tmp_path: Path, key: Key) -> None:
    staging, _ = _staged(tmp_path)
    assert staging.status(key) is None
    assert staging.append(key, 0, io.BytesIO(b"a"), 1) is Refused.ABSENT
    assert not staging.discard(key)


def test_an_upload_is_its_owners_on_its_article_alone(tmp_path: Path) -> None:
    staging, key = _staged(tmp_path)
    for other in (
        Key(key.upload_id, "bert", key.article),
        Key(key.upload_id, key.owner, "01KX7YT9E3VX0CP3A5Q49RZMWK"),
    ):
        assert staging.status(other) is None
        assert staging.append(other, 0, io.BytesIO(b"abc"), 3) is Refused.ABSENT
        with staging.claim(other) as claimed:
            assert claimed is None
        assert not staging.discard(other)
    assert staging.status(key) == (_UPLOAD, 0)


@pytest.mark.parametrize(
    "upload_id", ["../outside", "..", "OUTSIDE", "A" * 32, "a" * 31, "a" * 33, f"{'a' * 32}\n"]
)
def test_a_malformed_id_never_becomes_a_path(tmp_path: Path, upload_id: str) -> None:
    """A folder of the right shape waits wherever a malformed id could point."""
    root = tmp_path / "staging"
    root.mkdir()
    for target in {root / upload_id, (root / upload_id).resolve()}:
        target.mkdir(parents=True, exist_ok=True)
        (target / "meta.json").write_text(json.dumps(asdict(_UPLOAD)))
        (target / "data").write_bytes(b"")
    staging, key = Staging(root), Key(upload_id, _UPLOAD.owner, _UPLOAD.article)
    assert staging.status(key) is None
    assert not staging.discard(key)


def test_a_claim_removes_the_upload_only_when_told(tmp_path: Path) -> None:
    staging, key = _staged(tmp_path)
    staging.append(key, 0, io.BytesIO(b"abcdef"), 6)
    for _ in range(2):
        with staging.claim(key) as claimed:
            assert claimed is not None
            assert (claimed[0], claimed[1].read()) == (_UPLOAD, b"abcdef")
    with staging.claim(key) as claimed:
        assert claimed is not None
        claimed[2]()
    assert staging.status(key) is None
    assert not (tmp_path / key.upload_id).exists()


def test_an_incomplete_upload_cannot_be_claimed(tmp_path: Path) -> None:
    staging, key = _staged(tmp_path)
    staging.append(key, 0, io.BytesIO(b"abc"), 3)
    with staging.claim(key) as claimed:
        assert claimed is None
    assert staging.status(key) == (_UPLOAD, 3)


def test_a_discard_removes_the_upload(tmp_path: Path) -> None:
    staging, key = _staged(tmp_path)
    assert staging.discard(key)
    assert staging.status(key) is None
    assert not (tmp_path / key.upload_id).exists()


def _age(path: Path, now: int, hours: int) -> None:
    then = now - hours * 60 * 60
    os.utime(path, (then, then))


def test_the_hourly_sweep_removes_a_day_untouched_and_keeps_the_rest(tmp_path: Path) -> None:
    staging, old = _staged(tmp_path)
    _, recent = _staged(tmp_path)
    now = int(time.time())
    _age(tmp_path / old.upload_id / "data", now, 25)
    _age(tmp_path / recent.upload_id / "data", now, 23)
    with override_settings(BUNDESARCHIV_UPLOAD_STAGING_ROOT=str(tmp_path)):
        tasks.sweep.func(now)
    assert sorted(p.name for p in tmp_path.iterdir()) == [recent.upload_id]
    assert staging.status(recent) == (_UPLOAD, 0)


def test_the_sweep_removes_what_a_crashed_create_left_once_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def crash(*_: object) -> None:
        raise OSError("crash")

    with monkeypatch.context() as patched:
        patched.setattr(os, "rename", crash)
        with pytest.raises(OSError):
            Staging(tmp_path).create(_UPLOAD)
    (rest,) = tmp_path.iterdir()
    now = int(time.time())
    Staging(tmp_path).sweep(now - STALE_AFTER_SECONDS)
    assert rest.exists()
    _age(rest, now, 25)
    Staging(tmp_path).sweep(now - STALE_AFTER_SECONDS)
    assert list(tmp_path.iterdir()) == []
