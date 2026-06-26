"""Article identity primitives (ADR 0006).

A ULID is an Article's stable identity and its only key segment — `articles/<ulid>/`.
A slug is a *display* helper (human-readable filenames, UI), never part of the
canonical key: a title-derived slug would change when the title changes and so cannot
carry identity. These are pure functions; minting a ULID at Article creation is a
caller concern (Part 2), so they live in `domain`, not the persistence layer.
"""

import re
import unicodedata

from ulid import ULID

from bundesarchiv.domain.models import Ulid


def new_ulid() -> Ulid:
    """Mint a fresh ULID (26-char Crockford base32, lexicographically sortable)."""
    return str(ULID())


def is_valid_ulid(value: str) -> bool:
    """True if `value` is a well-formed ULID. Total: returns False (never raises) for
    a non-str too, so an untyped caller (e.g. a README field parsed to None) is safe."""
    try:
        ULID.from_str(value)
    except ValueError, TypeError:
        return False
    return True


def slugify(text: str) -> str:
    """A lowercase ASCII slug for display/filenames (NOT a key segment).

    Decomposes accents to their base letter (ä→a, é→e), drops anything non-ASCII,
    lowercases, and joins runs of [a-z0-9] with single hyphens. Lossy by design for
    characters with no ASCII base (e.g. ß is dropped); the canonical identity is the
    ULID, so loss here is cosmetic.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return "-".join(filter(None, re.split(r"[^a-z0-9]+", ascii_text)))
