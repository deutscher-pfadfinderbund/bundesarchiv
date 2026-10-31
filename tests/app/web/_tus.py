"""The chunked upload as its client drives it (ADR 0026): create, pieces, finish."""

import base64
from pathlib import Path
from typing import Any

from django.test import Client, override_settings
from django.urls import resolve, reverse

TUS = {"Tus-Resumable": "1.0.0"}
PIECE = "application/offset+octet-stream"


def staging_at(root: Path) -> override_settings:
    return override_settings(BUNDESARCHIV_UPLOAD_STAGING_ROOT=str(root))


def metadata(**pairs: str) -> str:
    return ",".join(
        f"{key} {base64.b64encode(value.encode()).decode()}" for key, value in pairs.items()
    )


def create(client: Client, ulid: str, length: int, filename: str = "scan.pdf") -> Any:
    return client.post(
        reverse("article-tus-create", args=[ulid]),
        headers={
            **TUS,
            "Upload-Length": str(length),
            "Upload-Metadata": metadata(filename=filename),
        },
    )


def upload_id(created: Any) -> str:
    return str(resolve(created["Location"]).kwargs["upload_id"])


def upload_url(ulid: str, upload: str) -> str:
    return reverse("article-tus-upload", args=[ulid, upload])


def patch(client: Client, ulid: str, upload: str, offset: int, body: bytes) -> Any:
    return client.generic(
        "PATCH",
        upload_url(ulid, upload),
        body,
        content_type=PIECE,
        headers={**TUS, "Upload-Offset": str(offset)},
    )


def staged(client: Client, ulid: str, data: bytes, length: int | None = None) -> str:
    """An upload of ``length`` bytes (all of ``data`` by default) holding ``data``; its id."""
    created = create(client, ulid, len(data) if length is None else length)
    assert created.status_code == 201
    upload = upload_id(created)
    assert patch(client, ulid, upload, 0, data).status_code == 204
    return upload


def finish(client: Client, ulid: str, upload: str) -> Any:
    return client.post(reverse("article-media-upload", args=[ulid]), {"upload_id": upload})
