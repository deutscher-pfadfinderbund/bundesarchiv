"""The bulk-edit (Sammelbearbeitung) core: field allowlist, per-article application, and the ONE
bulk Conflict catch (spec §0/§1/§3/§4).

Two layers, split so the leak-sensitive rules are pure and unit-testable and the CAS loop is a thin
shell over the real ``save_article`` service:

- ``ALLOWED_FIELDS`` / ``is_allowed_field`` — the fixed 9-field allowlist (spec §1). ``audience``,
  ``lifecycle``, ``sichtbarkeit`` are deliberately ABSENT (visibility changes must pass the per-item
  over-exposure gate, spec §0.7); an unknown ``feld`` mutates nothing.
- ``apply_field`` — apply one allowed field to one Article, pure: ``"" → None`` for scalars; a
  custom-bag key upserts (or removes on empty); setting ``media_type`` clears a now-orphaned
  ``document_type`` (spec §3). Custom writes rebuild through the Article constructor so the domain's
  sort/dedupe/reserved-key guard is the single rule (no second copy).
- ``document_type_fits_all`` — Dokumenttyp-alone is validated against EVERY article's CURRENT
  media_type before any write; one mismatch rejects the whole apply (all-or-nothing, fail-closed).
- ``apply_bulk`` — per selected ulid independently: fresh load at CURRENT version (bulk never carries
  stale versions — the archivist never opened these), apply the field, ``save_article`` at the loaded
  version. ``Conflict`` → bucket ``conflicted`` (NO retry — a field overwrite is not idempotent-safe,
  the human re-applies). Load failure → bucket ``missing``. The loop NEVER aborts early; every
  attempted ulid lands in exactly one bucket (``saved + conflicted + missing == distinct auswahl``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from bundesarchiv.app import articles
from bundesarchiv.app.web import vocab
from bundesarchiv.domain.models import Article, Ulid
from bundesarchiv.persistence.errors import ArchiveError, Conflict
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

#: The predefined Article scalar/collection fields bulk-editable (spec §1). NOT audience/lifecycle.
_PREDEFINED_FIELDS: frozenset[str] = frozenset(
    {
        "physical_location",
        "creator",
        "subject_place",
        "media_type",
        "document_type",
        "collection_id",
    }
)

#: The custom-bag keys bulk-editable (spec §1). Written through the Article constructor so the
#: reserved-key guard + sort/dedupe stay the domain's rule.
_CUSTOM_FIELDS: frozenset[str] = frozenset({"Quelle", "Querverweis", "Besitzer"})

#: The full 9-field allowlist. An unknown ``feld`` is refused with ZERO mutation (spec §6.3).
ALLOWED_FIELDS: frozenset[str] = _PREDEFINED_FIELDS | _CUSTOM_FIELDS


def is_allowed_field(feld: str) -> bool:
    """Whether ``feld`` may be bulk-edited (spec §0.7/§6.3). The allowlist is the ONLY gate — a value
    like ``lifecycle`` / ``audience`` / ``ulid`` / ``__class__`` is refused, mutating nothing."""
    return feld in ALLOWED_FIELDS


def apply_field(article: Article, feld: str, wert: str) -> Article:
    """Return ``article`` with the one allowed ``feld`` set to ``wert`` (pure — the frozen source is
    untouched). Scalars empty to ``None`` (``"" → None``); a custom-bag key upserts, or is removed on
    empty; setting ``media_type`` clears an orphaned ``document_type`` (spec §3). Caller must have
    checked ``is_allowed_field`` first."""
    if feld in _CUSTOM_FIELDS:
        return _apply_custom(article, feld, wert)
    value = wert.strip() or None
    # Explicit per-field replace (not a **dict splat) so each write is statically typed — the same
    # discipline project() uses; a dynamic splat into replace() type-checks as Any and would let a
    # wrong field through. media_type additionally clears an orphaned document_type (spec §3).
    match feld:
        case "physical_location":
            return replace(article, physical_location=value)
        case "creator":
            return replace(article, creator=value)
        case "subject_place":
            return replace(article, subject_place=value)
        case "document_type":
            return replace(article, document_type=value)
        case "collection_id":
            # collection_id is required (never None); an empty value is rejected upstream, but guard.
            return replace(article, collection_id=value or article.collection_id)
        case "media_type":
            return _apply_media_type(article, value)
        case _:  # unreachable — caller checked is_allowed_field; belt-and-braces no-op
            return article


def _apply_custom(article: Article, key: str, wert: str) -> Article:
    """Upsert (or remove on empty) one custom-bag key, rebuilding through the Article constructor so
    the domain's sort/dedupe/reserved-key guard is the single rule (spec §1)."""
    value = wert.strip()
    custom = {k: v for k, v in article.custom if k != key}
    if value:
        custom[key] = value
    return replace(article, custom=tuple(custom.items()))


def _apply_media_type(article: Article, media_type: str | None) -> Article:
    """Set ``media_type``, clearing ``document_type`` IFF the existing pair becomes invalid (spec §3 —
    never leave an ``is_valid_pair``-invalid state)."""
    document_type = article.document_type
    if not vocab.is_valid_pair(media_type, document_type):
        document_type = None
    return replace(article, media_type=media_type, document_type=document_type)


def document_type_fits_all(document_type: str, articles_: Sequence[Article]) -> bool:
    """Whether ``document_type`` is valid against EVERY article's CURRENT media_type (spec §3,
    Dokumenttyp-alone). One mismatch → False (the whole apply is rejected, all-or-nothing)."""
    return all(vocab.is_valid_pair(a.media_type, document_type) for a in articles_)


def field_display(feld: str, wert: str, collection_names: Mapping[str, str]) -> str:
    """The confirm/result page's human display of the new value (spec §2 D): a collection shows its
    NAME (not the ulid); an emptied scalar shows ``(geleert)``; else the value verbatim. The Signatur
    field is not bulk-editable, so no ``.c-sig`` rendering is needed here."""
    if not wert.strip():
        return "(geleert)"
    if feld == "collection_id":
        return collection_names.get(wert, wert)
    return wert


# --- the CAS loop + buckets (spec §4) ----------------------------------------------


@dataclass(frozen=True, slots=True)
class BulkRow:
    """One article's identity for the result buckets — its ulid + the marks the result page shows
    (ref_code for the ``.c-sig``, title). Captured at load time (a missing article has no row)."""

    ulid: Ulid
    ref_code: str
    title: str


@dataclass(frozen=True, slots=True)
class BulkOutcome:
    """The result of a bulk apply (spec §4). ``saved`` is a COUNT (the count carries the successes,
    signals-once); ``conflicted``/``missing`` are the actionable rows; ``doctype_cleared`` names the
    articles whose orphaned document_type was cleared; ``index_lagged`` aggregates any
    index_updated=False (one quiet lag note). Invariant: ``saved + len(conflicted) + len(missing) ==
    distinct auswahl`` (property-tested)."""

    saved: int
    conflicted: tuple[BulkRow, ...]
    missing: tuple[Ulid, ...]
    doctype_cleared: tuple[BulkRow, ...]
    index_lagged: bool


def apply_bulk(store: ObjectStore, ulids: Sequence[Ulid], feld: str, wert: str) -> BulkOutcome:
    """Apply ``feld=wert`` to each of ``ulids`` independently (spec §4). Per ulid: fresh load at the
    CURRENT version, apply the field, ``save_article`` at the loaded version. ``Conflict`` → the
    ``conflicted`` bucket (NO retry). A load failure → the ``missing`` bucket. The loop never aborts
    early; every DISTINCT ulid lands in exactly one bucket. Caller has already validated the field +
    dependent pair; this only executes and reports."""
    repo = ArticleRepository(store)
    saved = 0
    conflicted: list[BulkRow] = []
    missing: list[Ulid] = []
    doctype_cleared: list[BulkRow] = []
    index_lagged = False
    for ulid in dict.fromkeys(ulids):  # distinct, order-preserving
        try:
            stored = repo.load(ulid)
        except ArchiveError:
            missing.append(ulid)
            continue
        row = BulkRow(ulid=ulid, ref_code=stored.article.ref_code or "", title=stored.article.title)
        mutated = apply_field(stored.article, feld, wert)
        cleared = (
            feld == "media_type"
            and stored.article.document_type is not None
            and (mutated.document_type is None)
        )
        try:
            result = articles.save_article(store, mutated, stored.version)
        except Conflict:
            conflicted.append(row)
            continue
        saved += 1
        if cleared:
            doctype_cleared.append(row)
        if not result.index_updated:
            index_lagged = True
    return BulkOutcome(
        saved=saved,
        conflicted=tuple(conflicted),
        missing=tuple(missing),
        doctype_cleared=tuple(doctype_cleared),
        index_lagged=index_lagged,
    )
