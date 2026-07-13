"""The cataloging-form parse/validate layer + the ``catalog_form`` save controller (Part 4.7).

Two halves, split so the leak-sensitive validation is pure and unit-testable and the ONE
Conflict-catch site (ADR 0013) is a thin shell:

- ``parse_edit_form`` — a total function over a QueryDict-shaped mapping: it either builds a valid
  ``Article`` (ready for ``save_article``) or returns a ``FormErrors`` map keyed by field name with
  the verbatim German strings (spec §3). It owns the ``"" → None`` boundary for EVERY optional
  scalar (spec §8) and the GROUPS-iff-gruppen invariant. IO-free, request-free.
- ``save_catalog_form`` — the thin controller that is the ONLY place ``Conflict`` is caught for a
  form save (ADR 0013): it calls ``save_article(store, article, expected_version)`` directly (never
  ``update()``), and on ``Conflict`` re-loads the winner and returns a ``ConflictOutcome`` carrying
  the current version + winner article so the view re-renders the "Inzwischen geändert" panel with
  the archivist's just-submitted values preserved and a refreshed ``expected_version``. If that
  re-load instead finds the article gone (a stale save racing a hard delete, not a concurrent edit),
  it returns ``DeletedOutcome`` so the view collapses to the byte-identical 404 instead of a 500.

The Django coupling is a single ``getlist`` helper so the parser can be driven by a plain dict in
tests and a ``QueryDict`` in the view without knowing which it holds.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from bundesarchiv.app import articles
from bundesarchiv.app.result import SaveResult
from bundesarchiv.app.web import vocab
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Lifecycle,
    MediaRef,
    Ulid,
    Version,
)
from bundesarchiv.persistence.errors import ArchiveError, Conflict
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

#: A field-name → verbatim German error map (spec §3). Empty means the form validated.
type FormErrors = dict[str, str]

# The Sichtbarkeit select values → the audience rung they set. The empty value ("") is the inherit
# default (audience=None, ADR 0001) and is handled before this map is consulted.
_SICHTBARKEIT_TIER: dict[str, AudienceTier] = {
    "public": AudienceTier.PUBLIC,
    "members": AudienceTier.MEMBERS,
    "groups": AudienceTier.GROUPS,
}


@dataclass(frozen=True, slots=True)
class ParseResult:
    """The outcome of parsing an edit-form POST. Exactly one of ``article`` / ``errors`` is
    meaningful: a non-empty ``errors`` means the form did not validate and ``article is None``.
    ``expected_version`` always carries the form's hidden version (0 if absent) so the view can
    re-seed it on a re-render and pass it to the CAS save on success."""

    article: Article | None
    errors: FormErrors
    expected_version: Version


@runtime_checkable
class _HasGetlist(Protocol):
    """Structural stand-in for ``QueryDict.getlist`` — keeps this module Django-import-free while
    letting the multi-value read stay fully typed (no ``getattr``/``Any`` escape hatch)."""

    def getlist(self, key: str, /) -> list[str]: ...


def _getlist(post: Mapping[str, object], key: str) -> list[str]:
    """Read a multi-valued form field as a list of strings, working for both a Django ``QueryDict``
    (``.getlist``) and a plain ``dict[str, list[str]]`` (tests). An absent key yields ``[]``."""
    if isinstance(post, _HasGetlist):
        return list(post.getlist(key))
    value = post.get(key)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(v) for v in value]
    return [str(value)]


def _get(post: Mapping[str, object], key: str) -> str:
    """The first value of a form field as a string, or ``""`` if absent (never ``None``)."""
    values = _getlist(post, key)
    return values[0] if values else ""


def _none_if_blank(raw: str) -> str | None:
    """The ``"" → None`` boundary for an optional scalar: a blank or whitespace-only value becomes
    ``None``; otherwise the stripped value. Pinned by the leak-sensitive form contract (spec §8)."""
    stripped = raw.strip()
    return stripped or None


def parse_edit_form(
    post: Mapping[str, object],
    *,
    ulid: Ulid,
    collections: Sequence[Ulid],
    current_media: tuple[MediaRef, ...] = (),
    current_lifecycle: Lifecycle = Lifecycle.DRAFT,
) -> ParseResult:
    """Parse + validate an edit-form POST into an ``Article`` (with the given ``ulid``) or a field
    error map. Total: malformed input never raises, it becomes a field error. ``collections`` is the
    set of collection ULIDs the archivist may file into — a value outside it is rejected exactly like
    an empty one (no existence oracle on collections either).

    ``current_media`` is the article's media as stored: the metadata save PRESERVES it (never wipes
    it) and only updates each entry's caption from the form's ``caption[<hash>]`` field (spec §6.3 —
    captions ride the metadata CAS save; reorder/remove/upload are separate structural POSTs).
    ``current_lifecycle`` is preserved so a metadata save never silently changes published state (the
    lifecycle transition is its own CAS route)."""
    errors: FormErrors = {}
    expected_version = parse_version(_get(post, "expected_version"))

    title = _get(post, "title").strip()
    if not title:
        errors["title"] = "Titel ist erforderlich."

    collection_id = _get(post, "collection_id").strip()
    if collection_id not in collections:
        errors["collection_id"] = "Bitte einen Bestand wählen."

    media_type = _none_if_blank(_get(post, "media_type"))
    if media_type is None or media_type not in vocab.media_types():
        errors["media_type"] = "Medienart ist erforderlich."
        media_type = None  # invalid value never reaches the built Article (select tampering)

    document_type = _none_if_blank(_get(post, "document_type"))
    if document_type is not None and not vocab.is_valid_pair(media_type, document_type):
        errors["document_type"] = (
            "Bitte zuerst eine Medienart wählen."
            if media_type is None
            else f'Dieser Dokumenttyp gehört nicht zu „{media_type}".'
        )

    date, date_error = _parse_date(_get(post, "date"))
    if date_error is not None:
        errors["date"] = date_error

    audience, audience_error = _parse_audience(_get(post, "sichtbarkeit"), _get(post, "gruppen"))
    if audience_error is not None:
        errors["gruppen"] = audience_error

    custom, custom_error = _parse_custom(
        _getlist(post, "custom_key"), _getlist(post, "custom_value")
    )
    if custom_error is not None:
        errors["custom"] = custom_error

    if errors:
        return ParseResult(article=None, errors=errors, expected_version=expected_version)

    article = Article(
        ulid=ulid,
        title=title,
        collection_id=collection_id,
        body=_get(post, "body"),  # body stays a str ("" → "")
        lifecycle=current_lifecycle,  # a metadata save never changes lifecycle (its own CAS route)
        audience=audience,
        ref_code=_none_if_blank(_get(post, "ref_code")),
        media_type=media_type,
        document_type=document_type,
        tags=_parse_tags(_get(post, "tags")),
        physical_location=_none_if_blank(_get(post, "physical_location")),
        media=_apply_captions(post, current_media),  # preserve media; update captions (spec §6.3)
        date=date,
        creator=_none_if_blank(_get(post, "creator")),
        subject_place=_none_if_blank(_get(post, "subject_place")),
        custom=custom,
    )
    return ParseResult(article=article, errors={}, expected_version=expected_version)


def _apply_captions(
    post: Mapping[str, object], current_media: tuple[MediaRef, ...]
) -> tuple[MediaRef, ...]:
    """Return ``current_media`` with each entry's caption replaced by the form's ``caption[<hash>]``
    value (``"" → None``, spec §6.3/§8). Order is preserved (reorder is a separate structural POST);
    an absent field leaves the caption unchanged (defensive — the form always renders one per row)."""
    updated: list[MediaRef] = []
    for ref in current_media:
        field = f"caption[{ref.content_hash}]"
        if field in post:
            updated.append(replace(ref, caption=_none_if_blank(_get(post, field))))
        else:
            updated.append(ref)
    return tuple(updated)


def parse_version(raw: str) -> Version:
    """The hidden ``expected_version`` → int (0 if absent/garbage). A garbage version simply loses the
    CAS check on save (the store's real version won't match), so it need not be a field error. Public
    so the view's no-JS custom-row re-render path reads the SAME parse (no second copy)."""
    try:
        return int(raw)
    except ValueError:
        return 0


def _parse_tags(raw: str) -> tuple[str, ...]:
    """Comma-separated Schlagworte → a tuple, trimming each and dropping empties."""
    return tuple(t for part in raw.split(",") if (t := part.strip()))


def _parse_date(raw: str) -> tuple[EdtfDate | None, str | None]:
    """The Datierung field: ``"" → None`` (no date), else an ``EdtfDate`` or the verbatim-prefixed
    German error. The EDTF value object's ValueError message is the plain-German parser reason."""
    value = raw.strip()
    if not value:
        return None, None
    try:
        return EdtfDate(value), None
    except ValueError as err:
        return None, f"Datierung: {err}."


def _parse_audience(sichtbarkeit: str, gruppen: str) -> tuple[Audience | None, str | None]:
    """The Sichtbarkeit group: empty → inherit (``audience=None``); otherwise the chosen rung. The
    GROUPS rung REQUIRES at least one group (the model's GROUPS-iff invariant, server-enforced);
    groups named on a non-GROUPS rung are dropped (naming them there is a silent over-exposure the
    model forbids)."""
    tier = _SICHTBARKEIT_TIER.get(sichtbarkeit)
    if tier is None:
        return None, None  # empty / unknown → inherit default (ADR 0001)
    if tier is not AudienceTier.GROUPS:
        return Audience(tier=tier), None
    groups = tuple(g for part in gruppen.split(",") if (g := part.strip()))
    if not groups:
        return None, "Bitte mindestens eine Gruppe angeben."
    return Audience(tier=AudienceTier.GROUPS, groups=groups), None


def _parse_custom(
    keys: Sequence[str], values: Sequence[str]
) -> tuple[tuple[tuple[str, str], ...], str | None]:
    """The custom bag (Gruppe 7): pair keys with values, drop rows where either cell is blank (the
    always-one-empty-row add affordance leaves a trailing blank pair), and reject a key that collides
    with a predefined Article field (``Article.__post_init__`` raises; caught → the verbatim error).
    ``"" → None`` on each value is implicit: a blank value drops the whole row (spec §8)."""
    rows: list[tuple[str, str]] = []
    for key, value in zip(keys, values, strict=False):
        name, val = key.strip(), value.strip()
        if not name or not val:
            continue  # incomplete row → dropped (spec §3/§8)
        rows.append((name, val))
    try:
        # Round-trip through Article so the reserved-key collision + normalization is the SAME rule
        # the domain enforces (no second copy of the reserved-name set here).
        normalized = Article(ulid="X", title="x", collection_id="x", custom=tuple(rows)).custom
    except ValueError:
        return (), "Bezeichnung ist reserviert."
    return normalized, None


# --- the ONE Conflict catch site (ADR 0013) ----------------------------------------


@dataclass(frozen=True, slots=True)
class SavedOutcome:
    """A successful CAS save: the new version + whether the synchronous index update took (ADR 0014,
    surfaced as the index-lag hinweis by the view)."""

    result: SaveResult


@dataclass(frozen=True, slots=True)
class ConflictOutcome:
    """A losing CAS save (a concurrent write won): the winner's article at its NEW version, so the
    view re-renders the "Inzwischen geändert" panel with a neutral field diff and a refreshed
    ``expected_version``. No retry, no auto-merge (ADR 0013) — the archivist re-applies."""

    winner: Article
    current_version: Version
    submitted: Article


@dataclass(frozen=True, slots=True)
class DeletedOutcome:
    """The article was hard-deleted between the view's initial load and this save: the CAS check
    reads the store's version as 0 (``_current_version`` on a missing article) and raises
    ``Conflict``, but the Conflict handler's re-load then finds nothing at all — a stale save racing
    a deletion, not a concurrent edit. The view maps this to the byte-identical 404 (existence-hiding:
    the article no longer exists, so it must be indistinguishable from one that never did)."""


type SaveOutcome = SavedOutcome | ConflictOutcome | DeletedOutcome


def save_catalog_form(
    store: ObjectStore, article: Article, expected_version: Version
) -> SaveOutcome:
    """The ONLY site that catches ``Conflict`` for a form save (ADR 0013). Calls ``save_article``
    directly (never the retrying ``update()``): on success returns a ``SavedOutcome``; on ``Conflict``
    re-loads the winner at its current version and returns a ``ConflictOutcome`` carrying both the
    winner and the archivist's submitted article, so the view preserves the just-typed values and
    refreshes ``expected_version`` to the current version (the next Speichern then wins). If that
    re-load instead finds the article hard-deleted (the Conflict was a deletion, not a concurrent
    edit), returns ``DeletedOutcome`` so the view 404s instead of letting the load failure propagate."""
    try:
        result = articles.save_article(store, article, expected_version)
    except Conflict:
        try:
            stored = ArticleRepository(store).load(article.ulid)
        except ArchiveError:
            return DeletedOutcome()
        return ConflictOutcome(
            winner=stored.article, current_version=stored.version, submitted=article
        )
    return SavedOutcome(result=result)


def new_draft(store: ObjectStore, *, title: str, collection_id: Ulid) -> Ulid:
    """The minimal create step (spec §2): mint a DRAFT with just Titel + Bestand via the create path
    and return its ulid so the view can 302 to ``/bearbeiten``. Everything else is filled in on the
    edit form."""
    return articles.create_article(store, title=title, collection_id=collection_id).ulid
