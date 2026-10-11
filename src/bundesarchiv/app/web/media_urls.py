"""The public wire URLs of a media file and its derived versions; a leaf, so a row or a card links
a file without importing the view stack."""


def media_url(ulid: str, content_hash: str) -> str:
    """The wire URL of a blob: ``/media/<ulid>/<content_hash>`` (the ``media`` route). Distinct from
    ``ArticleRepository.media_key``, which names the blob in the store."""
    return f"/media/{ulid}/{content_hash}"


def thumbnail_url(ulid: str, content_hash: str) -> str:
    """The wire URL of a blob's thumbnail (the ``media-thumb`` route)."""
    return f"{media_url(ulid, content_hash)}/thumb"


def display_url(ulid: str, content_hash: str) -> str:
    """The wire URL of an image's display version (the ``media-display`` route)."""
    return f"{media_url(ulid, content_hash)}/display"
