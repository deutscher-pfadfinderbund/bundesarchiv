"""The cataloging-form views (Part 4.7 Slice A+B): create step + full edit form (no-JS baseline).

Two production routes, both archivist-gated to the media route's byte-identical 404 for anyone else
(existence-hiding — the cataloging surface must not be discoverable). Thin by design: the
leak-sensitive parsing + validation live in ``catalog`` (pure, unit-tested), the write services in
``app.articles``, and the ONE ADR-0013 ``Conflict`` catch site in ``catalog.save_catalog_form``.
These views only resolve the viewer, gate, marshal the form context, and render.

- ``article_create`` — ``GET/POST /artikel/neu``: GET renders the minimal create form (Titel +
  Bestand); POST creates a DRAFT via ``create_article`` and 302s to the edit form. Validation
  re-renders state B (verbatim errors, preserved values).
- ``article_edit`` — ``GET/POST /artikel/<ulid>/bearbeiten``: GET renders the full form seeded from
  the stored Article; POST parses + saves (CAS on ``expected_version``). A ``Conflict`` re-renders
  the "Inzwischen geändert" panel (state G) with the just-submitted values preserved.

The ``<ulid>`` is validated in-view via ``is_valid_ulid`` (never a route converter), so a malformed
value collapses to the same 404 as an absent one. ``neu`` is registered before ``<str:ulid>`` in
``urls.py`` so the literal path wins.
"""

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app.web import catalog, vocab
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Article, AudienceTier, Collection, Ulid
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

# The Sichtbarkeit select options: (value, caption). The empty value is the inherit default (ADR
# 0001); the rest map to the audience rungs. GROUPS is chosen together with the Gruppen field.
_SICHTBARKEIT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", "Vom Bestand erben"),
    ("public", "Öffentlich"),
    ("members", "Alle Mitglieder"),
    ("groups", "Gruppe(n)"),
)


def _canonical_store() -> ObjectStore:
    """The canonical files-store (ADR 0005), built per request from settings — the same construction
    the media/detail views use. Monkeypatchable in tests."""
    return LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))


def _is_archivist(request: HttpRequest) -> bool:
    """Whether the request's viewer is an Archivist — the gate for both cataloging routes."""
    return isinstance(viewer_of(request), Archivist)


def _collections(store: ObjectStore) -> tuple[Collection, ...]:
    """Every saved Collection (read-only, per request). An Archivist files into any of them, so the
    whole set is the Bestand option source; the parse layer rejects a value outside it."""
    return CollectionRepository(store).load_all()


def _collection_options(collections: tuple[Collection, ...]) -> tuple[tuple[str, str], ...]:
    """The Bestand select options: the placeholder first (empty value, server-rejected), then each
    collection as ``(ulid, name)`` in load order."""
    return (("", "— Bestand wählen —"), *((c.ulid, c.name) for c in collections))


# --- /artikel/neu — the create step (Slice A) --------------------------------------


def article_create(request: HttpRequest) -> HttpResponseBase:
    """``GET/POST /artikel/neu`` — the minimal create step. Archivist-only (non-archivist → the
    byte-identical 404, both methods). POST creates a DRAFT with just Titel + Bestand and 302s to the
    edit form; a validation failure re-renders state B with the verbatim error + preserved values."""
    if not _is_archivist(request):
        return _not_found()
    store = _canonical_store()
    collections = _collections(store)
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        collection_id = request.POST.get("collection_id", "").strip()
        errors = _create_errors(title, collection_id, collections)
        if not errors:
            ulid = catalog.new_draft(store, title=title, collection_id=collection_id)
            return HttpResponseRedirect(f"/artikel/{ulid}/bearbeiten")
        return render(
            request,
            "workbench/artikel_neu.html",
            _create_context(collections, title=title, collection_id=collection_id, errors=errors),
        )
    return render(
        request,
        "workbench/artikel_neu.html",
        _create_context(collections, title="", collection_id="", errors={}),
    )


def _create_errors(
    title: str, collection_id: str, collections: tuple[Collection, ...]
) -> catalog.FormErrors:
    """The two create-step validations (spec §2), verbatim strings — the same two rules the full
    parse layer applies, kept minimal here because the create step has only these two fields."""
    errors: catalog.FormErrors = {}
    if not title:
        errors["title"] = "Titel ist erforderlich."
    if collection_id not in {c.ulid for c in collections}:
        errors["collection_id"] = "Bitte einen Bestand wählen."
    return errors


def _create_context(
    collections: tuple[Collection, ...],
    *,
    title: str,
    collection_id: str,
    errors: catalog.FormErrors,
) -> dict[str, object]:
    """The create form's template context: preserved values, the Bestand options, field errors, and
    the server-computed autofocus target (Titel unless it already has a value)."""
    return {
        "title": title,
        "collection_id": collection_id,
        "collection_options": _collection_options(collections),
        "errors": errors,
        "autofocus": "collection_id" if title and "title" not in errors else "title",
    }


# --- /artikel/<ulid>/bearbeiten — the full edit form (Slice B) ---------------------


def article_edit(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /artikel/<ulid>/bearbeiten`` — the full edit form. Archivist-only (non-archivist,
    malformed, or absent ulid → the byte-identical 404, both methods). GET seeds the form from the
    stored Article; POST parses + saves under CAS. A ``Conflict`` re-renders state G with the
    just-submitted values preserved and a refreshed ``expected_version``."""
    if not _is_archivist(request) or not is_valid_ulid(ulid):
        return _not_found()
    store = _canonical_store()
    try:
        stored = ArticleRepository(store).load(ulid)
    except ArchiveError:
        return _not_found()  # absent/unreadable → the same 404 (existence-hiding)
    collections = _collections(store)
    if request.method == "POST":
        return _handle_edit_post(request, store, ulid, collections)
    context = _edit_context_from_article(
        stored.article, stored.version, collections, autofocus_first_empty=True
    )
    return render(request, "workbench/artikel_bearbeiten.html", context)


def _handle_edit_post(
    request: HttpRequest,
    store: ObjectStore,
    ulid: Ulid,
    collections: tuple[Collection, ...],
) -> HttpResponseBase:
    """Parse + save the edit POST. On a validation error re-render state F (first errored field
    autofocused). On success 302 to the read view. On ``Conflict`` re-render state G with the
    submitted values preserved (the ONE catch site is ``catalog.save_catalog_form``). A
    ``custom_entfernen`` submit is the no-JS custom-row removal — it re-renders the form with that
    row cleared, without saving (spec §5)."""
    if "custom_entfernen" in request.POST:
        return _rerender_with_custom_removed(request, ulid, collections)
    result = catalog.parse_edit_form(
        request.POST, ulid=ulid, collections=tuple(c.ulid for c in collections)
    )
    if result.article is None:
        context = _edit_context_from_post(
            request, ulid, result, collections, autofocus=_first_error_field(result.errors)
        )
        return render(request, "workbench/artikel_bearbeiten.html", context)
    outcome = catalog.save_catalog_form(store, result.article, result.expected_version)
    match outcome:
        case catalog.SavedOutcome():
            return HttpResponseRedirect(f"/artikel/{ulid}")
        case catalog.ConflictOutcome() as conflict:
            context = _edit_context_from_post(
                request, ulid, result, collections, autofocus="speichern", conflict=conflict
            )
            return render(request, "workbench/artikel_bearbeiten.html", context)


def _rerender_with_custom_removed(
    request: HttpRequest, ulid: Ulid, collections: tuple[Collection, ...]
) -> HttpResponseBase:
    """The no-JS custom-row removal: drop the row whose index rode the ``custom_entfernen`` submit,
    then re-render the form with every OTHER value preserved and NO save (spec §5). A bad index is a
    no-op (nothing removed) — total, never raises."""
    values = _post_to_form_values(request, ulid)
    try:
        index = int(request.POST.get("custom_entfernen", ""))
    except ValueError:
        index = -1
    rows = list(values["custom_rows"])  # type: ignore[call-overload]
    if 0 <= index < len(rows):
        rows.pop(index)
    if ("", "") not in rows:
        rows.append(("", ""))  # keep the always-present empty add-row
    values["custom_rows"] = rows
    version = catalog.parse_version(request.POST.get("expected_version", ""))
    context = _edit_context(values, version, collections, errors={}, autofocus="")
    return render(request, "workbench/artikel_bearbeiten.html", context)


@dataclass(frozen=True, slots=True)
class _ConflictRow:
    """One row of the neutral CAS diff table (spec §6.1): the German field label + the archivist's
    submitted value + the winner's stored value. ``is_sig`` marks the Signatur row so the template
    renders both cells as ``.c-sig`` marks."""

    label: str
    mine: str
    theirs: str
    is_sig: bool


def _edit_context_from_article(
    article: Article,
    version: int,
    collections: tuple[Collection, ...],
    *,
    autofocus_first_empty: bool,
) -> dict[str, object]:
    """The edit form context seeded from a stored Article (the GET path). Autofocus lands on the
    first empty field (spec §5) when requested."""
    values = _article_to_form_values(article)
    autofocus = _first_empty_field(values) if autofocus_first_empty else ""
    return _edit_context(values, version, collections, errors={}, autofocus=autofocus)


def _edit_context_from_post(
    request: HttpRequest,
    ulid: Ulid,
    result: catalog.ParseResult,
    collections: tuple[Collection, ...],
    *,
    autofocus: str,
    conflict: catalog.ConflictOutcome | None = None,
) -> dict[str, object]:
    """The edit form context re-seeded from the raw POST (state F/G): the archivist's just-typed
    values are preserved verbatim. On a ``Conflict`` the hidden ``expected_version`` is refreshed to
    the winner's current version and the neutral diff rows are attached (spec §6.1)."""
    values = _post_to_form_values(request, ulid)
    version = conflict.current_version if conflict is not None else result.expected_version
    context = _edit_context(values, version, collections, errors=result.errors, autofocus=autofocus)
    if conflict is not None:
        context["conflict_rows"] = _conflict_rows(conflict.submitted, conflict.winner)
    return context


def _edit_context(
    values: dict[str, object],
    version: int,
    collections: tuple[Collection, ...],
    *,
    errors: catalog.FormErrors,
    autofocus: str,
) -> dict[str, object]:
    """Assemble the full edit-form context: the field values, the option lists, the field errors, the
    hidden version, and the autofocus target. The Signatur mark in the header reflects the current
    ``ref_code`` value (empty → the hollow slot)."""
    return {
        "values": values,
        "version": version,
        "errors": errors,
        "autofocus": autofocus,
        "collection_options": _collection_options(collections),
        "media_type_options": _media_type_options(),
        "document_type_groups": vocab.grouped_document_type_options(),
        "sichtbarkeit_options": _SICHTBARKEIT_OPTIONS,
        "ref_code": values.get("ref_code") or "",
        "edtf_echo": _edtf_echo(str(values.get("date") or "")),
    }


def _media_type_options() -> tuple[tuple[str, str], ...]:
    """The Medienart select options: the placeholder first (empty, server-rejected), then the
    vocabulary in order."""
    return (("", "— Medienart wählen —"), *((m, m) for m in vocab.media_types()))


def _edtf_echo(date_value: str) -> str:
    """The server-side EDTF echo (spec §5): render the human-German sentence if the value parses,
    else empty (a bad value shows its field error, not a broken echo)."""
    if not date_value.strip():
        return ""
    try:
        return vocab.edtf_to_german(EdtfDate(date_value.strip()))
    except ValueError:
        return ""


def _article_to_form_values(article: Article) -> dict[str, object]:
    """A stored Article → the flat form-value dict the template prints (GET seed). Every scalar
    renders as its string or ``""``; the audience decomposes to the Sichtbarkeit select value + the
    comma-joined Gruppen; custom pairs become the row list plus one trailing empty row."""
    return {
        "ulid": article.ulid,
        "title": article.title,
        "collection_id": article.collection_id,
        "ref_code": article.ref_code or "",
        "media_type": article.media_type or "",
        "document_type": article.document_type or "",
        "tags": ", ".join(article.tags),
        "date": article.date.value if article.date is not None else "",
        "creator": article.creator or "",
        "subject_place": article.subject_place or "",
        "physical_location": article.physical_location or "",
        "body": article.body,
        "sichtbarkeit": _sichtbarkeit_value(article),
        "gruppen": ", ".join(article.audience.groups) if article.audience is not None else "",
        "custom_rows": [*article.custom, ("", "")],  # always one trailing empty row (no-JS add)
        "is_draft": article.lifecycle.name == "DRAFT",
    }


def _post_to_form_values(request: HttpRequest, ulid: Ulid) -> dict[str, object]:
    """The raw POST → the flat form-value dict (state B/F/G re-render). Values are preserved verbatim
    so the archivist never loses input; custom rows echo back what was typed plus one empty row."""
    post = request.POST
    keys = post.getlist("custom_key")
    vals = post.getlist("custom_value")
    rows = [*zip(keys, vals, strict=False), ("", "")]
    return {
        "ulid": ulid,
        "title": post.get("title", ""),
        "collection_id": post.get("collection_id", ""),
        "ref_code": post.get("ref_code", ""),
        "media_type": post.get("media_type", ""),
        "document_type": post.get("document_type", ""),
        "tags": post.get("tags", ""),
        "date": post.get("date", ""),
        "creator": post.get("creator", ""),
        "subject_place": post.get("subject_place", ""),
        "physical_location": post.get("physical_location", ""),
        "body": post.get("body", ""),
        "sichtbarkeit": post.get("sichtbarkeit", ""),
        "gruppen": post.get("gruppen", ""),
        "custom_rows": rows,
        "is_draft": True,  # Slice A+B: articles under edit are drafts
    }


def _sichtbarkeit_value(article: Article) -> str:
    """The Sichtbarkeit select value for a stored Article: empty (inherit) when audience is None,
    else the rung's select value."""
    if article.audience is None:
        return ""
    match article.audience.tier:
        case AudienceTier.PUBLIC:
            return "public"
        case AudienceTier.MEMBERS:
            return "members"
        case AudienceTier.GROUPS:
            return "groups"


# The single-line fields in DOM/tab order — the autofocus scan walks these to find the first empty
# one (GET) so an archivist lands on the first thing to fill (spec §5). body/custom are excluded:
# body is a textarea (not "empty field" in the field sense) and custom is the escape hatch.
_FOCUSABLE_FIELDS: tuple[str, ...] = (
    "title",
    "collection_id",
    "ref_code",
    "media_type",
    "document_type",
    "tags",
    "date",
    "creator",
    "subject_place",
    "physical_location",
)


def _first_empty_field(values: dict[str, object]) -> str:
    """The first single-line field (DOM order) whose value is empty — the fresh-edit autofocus target
    (spec §5). Falls back to Titel when every field is filled."""
    for name in _FOCUSABLE_FIELDS:
        if not str(values.get(name) or "").strip():
            return name
    return "title"


def _first_error_field(errors: catalog.FormErrors) -> str:
    """The first errored field in DOM order — the validation-re-render autofocus target (spec §5).
    ``custom`` maps to no single input, so it focuses nothing (empty)."""
    for name in _FOCUSABLE_FIELDS:
        if name in errors:
            return name
    if "gruppen" in errors:
        return "gruppen"
    return ""


# --- the CAS conflict diff (spec §6.1) ---------------------------------------------

# The fields the neutral diff compares, with their German labels. Only CHANGED fields are shown
# (signals-once); the Signatur row renders as .c-sig marks. Order is the form's field order.
_DIFF_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "Titel"),
    ("ref_code", "Signatur"),
    ("media_type", "Medienart"),
    ("document_type", "Dokumenttyp"),
    ("tags", "Schlagworte"),
    ("date", "Datierung"),
    ("creator", "Autor"),
    ("subject_place", "Ort"),
    ("physical_location", "Standort"),
    ("body", "Beschreibung"),
    ("sichtbarkeit", "Sichtbarkeit"),
)


def _conflict_rows(mine: Article, theirs: Article) -> list[_ConflictRow]:
    """The neutral CAS diff (spec §6.1): one row per CHANGED field, comparing the archivist's
    submitted Article to the winner's stored Article. Only differences are listed (signals-once).
    The Signatur row is flagged so the template renders both cells as ``.c-sig`` marks."""
    rows: list[_ConflictRow] = []
    for name, label in _DIFF_FIELDS:
        mine_str = _diff_value(mine, name)
        theirs_str = _diff_value(theirs, name)
        if mine_str != theirs_str:
            rows.append(
                _ConflictRow(
                    label=label, mine=mine_str, theirs=theirs_str, is_sig=name == "ref_code"
                )
            )
    return rows


def _diff_value(article: Article, name: str) -> str:
    """One Article field as a comparable/displayable string for the CAS diff. Optional scalars show
    ``""`` when absent; tags join on comma; date shows its EDTF value; sichtbarkeit shows the rung."""
    match name:
        case "tags":
            return ", ".join(article.tags)
        case "date":
            return article.date.value if article.date is not None else ""
        case "sichtbarkeit":
            return _audience_label(article)
        case _:
            return str(getattr(article, name) or "")


def _audience_label(article: Article) -> str:
    """The stored audience as a human-German label for the CAS diff (inherit / rung / groups)."""
    if article.audience is None:
        return "Vom Bestand erben"
    match article.audience.tier:
        case AudienceTier.PUBLIC:
            return "Öffentlich"
        case AudienceTier.MEMBERS:
            return "Alle Mitglieder"
        case AudienceTier.GROUPS:
            return "Gruppe: " + ", ".join(article.audience.groups)
