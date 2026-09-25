"""The bulk-edit (Sammelbearbeitung) core: field allowlist, per-article application, and the CAS
loop's write-time guards (spec §0/§1/§3/§4).

Two layers, split so the leak-sensitive rules are pure and unit-testable and the apply loop is a thin
shell over the real ``update_article`` service:

- ``ALLOWED_FIELDS`` / ``is_allowed_field`` — the fixed 9-field allowlist (spec §1). ``audience``,
  ``lifecycle``, ``sichtbarkeit`` are deliberately ABSENT (visibility changes must pass the per-item
  over-exposure gate, spec §0.7); an unknown ``feld`` mutates nothing.
- ``apply_field`` — apply one allowed field to one Article, pure: ``"" → None`` for scalars; a
  custom-bag key upserts (or removes on empty); setting ``media_type`` clears a now-orphaned
  ``document_type`` (spec §3). Custom writes rebuild through the Article constructor so the domain's
  sort/dedupe/reserved-key guard is the single rule (no second copy).
- ``feldwahl_context`` — the Feld chooser's render context, every part of it derived from ``FIELDS``
  (options, the ``data-bulk-wert`` tokens). The workbench drawer and the confirm page's error mode
  render ONE partial from it, so a new field reaches both surfaces at once.
- ``document_type_fits_all`` — Dokumenttyp-alone is validated against EVERY article's CURRENT
  media_type before any write; one mismatch rejects the whole apply (all-or-nothing, fail-closed).
- ``apply_bulk`` — per selected ulid independently, through ``app.articles.update_article`` with NO
  retries: bulk never carries a stale version (the archivist never opened these records), so the
  service's fresh load IS the apply-time version, but a field overwrite is not idempotent-safe, so a
  lost race must reach the human rather than be re-applied to the winner. A ``document_type`` apply
  re-checks ``vocab.is_valid_pair`` against the FRESHLY-LOADED media_type (the confirm page validated
  a possibly-stale one; a mismatch here is a concurrent modification, not a rules bug) and refuses.
  That refusal, a lost race, and any other ``ArchiveError`` the save raises all bucket ``conflicted``;
  an article the service cannot load buckets ``missing``. The loop NEVER aborts early; every attempted
  ulid lands in exactly one bucket (``saved + conflicted + missing == distinct auswahl``).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from bundesarchiv.app import articles
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import Conflicted, Missing, Updated
from bundesarchiv.app.web import vocab
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.domain.models import Article, Ulid
from bundesarchiv.persistence.errors import ArchiveError


@dataclass(frozen=True, slots=True)
class BulkField:
    """One bulk-editable field's metadata — the SINGLE source everything else derives from, so the
    allowlist, the German label, the drawer widget, and the POST value-input name can never drift
    apart (spec §1). ``value_input`` is the form field the drawer posts the value under (the no-JS
    drawer renders every widget; the server reads the one matching the chosen field). ``is_custom``
    routes writes through the custom bag."""

    target: str
    label: str
    value_input: str
    is_custom: bool


#: The 9 bulk-editable fields in spec §1 order — the ONE source of truth. audience / lifecycle /
#: sichtbarkeit are deliberately absent (visibility must pass the per-item over-exposure gate, §0.7).
#: The plain scalars + custom keys share the one text widget (wert_text); the three selects have
#: their own. Everything below (ALLOWED_FIELDS, labels, options, value-input map) derives from this.
FIELDS: tuple[BulkField, ...] = (
    BulkField("physical_location", "Standort", "wert_text", False),
    BulkField("creator", "Autor", "wert_text", False),
    BulkField("subject_place", "Ort", "wert_text", False),
    BulkField("media_type", "Medienart", "wert_media_type", False),
    BulkField("document_type", "Dokumenttyp", "wert_document_type", False),
    BulkField("Quelle", "Quelle", "wert_text", True),
    BulkField("collection_id", "Sammlungsteil", "wert_collection_id", False),
    BulkField("Querverweis", "Querverweis", "wert_text", True),
    BulkField("Besitzer", "Besitzer", "wert_text", True),
)

_BY_TARGET: dict[str, BulkField] = {f.target: f for f in FIELDS}

#: The full 9-field allowlist, derived from FIELDS. An unknown ``feld`` is refused, ZERO mutation
#: (spec §6.3).
ALLOWED_FIELDS: frozenset[str] = frozenset(_BY_TARGET)

#: The custom-bag targets (written through the Article constructor so the reserved-key guard +
#: sort/dedupe stay the domain's rule), derived from FIELDS.
_CUSTOM_FIELDS: frozenset[str] = frozenset(f.target for f in FIELDS if f.is_custom)


#: The Feld ``<select>``'s options: the placeholder first (empty, server-rejected with "Bitte ein
#: Feld wählen."), then every field in spec §1 order.
_FELD_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", "— Feld wählen —"),
    *((f.target, f.label) for f in FIELDS),
)

#: value_input → the space-separated targets that widget serves, the chooser's ``data-bulk-wert``
#: tokens (layouts.css matches them to show exactly one widget). Derived, never typed out.
_WIDGET_TARGETS: dict[str, str] = {
    value_input: " ".join(f.target for f in FIELDS if f.value_input == value_input)
    for value_input in dict.fromkeys(f.value_input for f in FIELDS)
}


def feldwahl_context(
    bestand: BestandChooser, *, feld: str = "", wert: str = ""
) -> dict[str, object]:
    """The whole Feld-chooser context behind ``workbench/_feldwahl.html`` (spec §2 C) — ONE builder
    for the workbench bulk bar and the confirm page's error mode, so the two renders cannot drift.
    ``feld``/``wert`` are the submitted pair to re-echo verbatim (empty for a fresh chooser);
    ``bestand`` supplies the Sammlungsteil widget's options."""
    return {
        "feldwahl_feld": feld,
        "feldwahl_wert": wert,
        "feldwahl_feld_options": _FELD_OPTIONS,
        "feldwahl_targets": _WIDGET_TARGETS,
        "feldwahl_media_type_options": vocab.media_type_options(),
        "feldwahl_document_type_groups": vocab.grouped_document_type_options(),
        "feldwahl_collection_options": bestand.options(),
    }


def label_of(feld: str) -> str:
    """The German label for a field target (confirm/result pages show the label, not the key)."""
    f = _BY_TARGET.get(feld)
    return f.label if f is not None else feld


def value_input_of(feld: str) -> str:
    """The POST field name the drawer posts this field's value under (spec §2 C). Unknown → the text
    input (harmless; an unknown feld is refused before the value is read)."""
    f = _BY_TARGET.get(feld)
    return f.value_input if f is not None else "wert_text"


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


def field_display(feld: str, wert: str, bestand: BestandChooser) -> str:
    """The confirm/result page's human display of the new value (spec §2 D): a collection shows its
    NAME (not the ulid); an emptied scalar shows ``(geleert)``; else the value verbatim. The Signatur
    field is not bulk-editable, so no ``.c-sig`` rendering is needed here."""
    if not wert.strip():
        return "(geleert)"
    if feld == "collection_id":
        return bestand.name_of(wert) or wert
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


class _Unfit(Exception):
    """The freshly-loaded media_type no longer admits the Dokumenttyp being applied (spec §3) — a
    concurrent modification since the confirm page validated, so this article is refused unsaved."""


@dataclass
class _FieldApplication:
    """The transform ``update_article`` calls, remembering the article it was handed. The buckets are
    built from that pre-image: a ``conflicted`` row shows the record as it stood, and the cleared-
    Dokumenttyp note is a before/after comparison (spec §4)."""

    feld: str
    wert: str
    loaded: Article | None = None

    def __call__(self, article: Article) -> Article:
        self.loaded = article
        mutated = apply_field(article, self.feld, self.wert)
        if self.feld == "document_type" and not vocab.is_valid_pair(
            article.media_type, mutated.document_type
        ):
            raise _Unfit
        return mutated


def apply_bulk(
    archive: Archive, ulids: Sequence[Ulid], feld: str, wert: str, *, changed_by: str
) -> BulkOutcome:
    """Apply ``feld=wert`` to each of ``ulids`` independently (spec §4), each through
    ``update_article`` with NO retries — a lost race must reach the human, not be re-applied to the
    winner. A refused pair (spec §3), a lost race and any other ``ArchiveError`` from the save all
    bucket ``conflicted`` without writing; an article the service cannot load buckets ``missing``.
    The loop never aborts early; every DISTINCT ulid lands in exactly one bucket. Caller has already
    validated the field + dependent pair against its OWN load; this re-validates against the current
    store state and executes."""
    saved = 0
    conflicted: list[BulkRow] = []
    missing: list[Ulid] = []
    doctype_cleared: list[BulkRow] = []
    index_lagged = False
    for ulid in dict.fromkeys(ulids):  # distinct, order-preserving
        mutation = _FieldApplication(feld, wert)
        try:
            outcome = articles.update_article(
                archive, ulid, mutation, changed_by=changed_by, retries=0
            )
        except _Unfit, ArchiveError:
            outcome = Conflicted()  # refused pair, or a save failure the service does not own
        loaded = mutation.loaded
        if isinstance(outcome, Missing) or loaded is None:  # loaded is None iff nothing was loaded
            missing.append(ulid)
            continue
        row = BulkRow(ulid=ulid, ref_code=loaded.ref_code or "", title=loaded.title)
        match outcome:
            case Conflicted():
                conflicted.append(row)
            case Updated(article=written, index_updated=index_updated):
                saved += 1
                if feld == "media_type" and (
                    loaded.document_type is not None and written.document_type is None
                ):
                    doctype_cleared.append(row)
                index_lagged = index_lagged or not index_updated
    return BulkOutcome(
        saved=saved,
        conflicted=tuple(conflicted),
        missing=tuple(missing),
        doctype_cleared=tuple(doctype_cleared),
        index_lagged=index_lagged,
    )
