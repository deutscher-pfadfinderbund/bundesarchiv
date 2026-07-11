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

from dataclasses import dataclass, replace
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app import articles as article_services
from bundesarchiv.app.web import catalog, vocab
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.access import VisibilityPreview, preview
from bundesarchiv.domain.collections import resolve_chain
from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import (
    Article,
    AudienceTier,
    Collection,
    Lifecycle,
    Ulid,
)
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository, Stored

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
    """Whether the request's viewer is an Archivist — the gate for every cataloging route."""
    return isinstance(viewer_of(request), Archivist)


def _load_gated(request: HttpRequest, ulid: str) -> tuple[ObjectStore, Stored] | None:
    """The shared gate for every ulid-bearing cataloging route: archivist-only, validate the ulid
    in-view, and load the Article — returning ``(store, stored)`` ONLY if all pass, else ``None``
    (the caller maps ``None`` to the byte-identical 404). A non-archivist, a malformed ulid, and an
    absent/unreadable article all collapse to the SAME ``None`` (existence-hiding, spec §8)."""
    if not _is_archivist(request) or not is_valid_ulid(ulid):
        return None
    store = _canonical_store()
    try:
        return store, ArticleRepository(store).load(ulid)
    except ArchiveError:
        return None


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
    gated = _load_gated(request, ulid)
    if gated is None:
        return _not_found()
    store, stored = gated
    collections = _collections(store)
    if request.method == "POST":
        return _handle_edit_post(request, store, ulid, collections)
    context = _edit_context_from_article(
        stored.article, stored.version, collections, autofocus_first_empty=True
    )
    # After Kopieren the copy's edit form lands with the Signatur field focused (spec §5 — the one
    # field that must change first on the volume path, just cleared). ?fokus=signatur carries that.
    if request.GET.get("fokus") == "signatur":
        context["autofocus"] = "ref_code"
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
        context["conflict"] = True
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
    ("lifecycle", "Status"),
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
        case "lifecycle":
            return "Entwurf" if article.lifecycle is Lifecycle.DRAFT else "Veröffentlicht"
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


# --- /artikel/<ulid>/kopieren — copy to a fresh draft (Slice C, spec §7) -----------


def article_copy(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/kopieren`` — copy the article's metadata into a fresh DRAFT (Signatur
    cleared, no media) via the ``copy_article`` service, then 302 to the copy's edit form with the
    Signatur field autofocused (spec §5 — the one field that must change first on the volume path).
    Archivist-only; a non-archivist / malformed / absent ulid gets the byte-identical 404. No confirm
    (it creates, never destroys). GET is not allowed (a copy is a mutation)."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    store, _ = gated
    copy = article_services.copy_article(store, ulid)
    # ?fokus=signatur tells the edit view to autofocus the Signatur field on this first load.
    return HttpResponseRedirect(f"/artikel/{copy.ulid}/bearbeiten?fokus=signatur")


# --- /artikel/<ulid>/loeschen — delete confirm + execute (Slice C, spec §7) --------


def article_delete(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /artikel/<ulid>/loeschen`` — the delete confirm page (GET) and its execution
    (POST). Archivist-only; a non-archivist / malformed / absent ulid gets the byte-identical 404,
    both methods. GET shows the ``.c-sig`` + Titel context so the archivist confirms WHICH record;
    POST hard-deletes and 302s to the workbench. The read-view Löschen trigger stays neutral — red
    lives ONLY on this page's Endgültig löschen button (spec §7)."""
    gated = _load_gated(request, ulid)
    if gated is None:
        return _not_found()
    store, stored = gated
    if request.method == "POST":
        article_services.hard_delete_article(store, ulid)
        return HttpResponseRedirect("/")
    # Verwerfen (abandoning a draft from the edit form) reuses this identical confirm page + the same
    # hard-delete, only reworded (spec §7 — avoids a second destructive idiom). ?verwerfen=1 flags it,
    # but the "Entwurf verwerfen" wording is only honest for a DRAFT — a published article is deleted,
    # not discarded, so it always reads "Artikel löschen?" regardless of the query param.
    verwerfen = request.GET.get("verwerfen") == "1" and stored.article.lifecycle is Lifecycle.DRAFT
    return render(
        request,
        "workbench/artikel_loeschen.html",
        {
            "ulid": ulid,
            "title": stored.article.title,
            "ref_code": stored.article.ref_code or "",
            "titel_confirm": "Entwurf verwerfen?" if verwerfen else "Artikel löschen?",
            "button_label": "Entwurf verwerfen" if verwerfen else "Endgültig löschen",
            "action": f"/artikel/{ulid}/loeschen",
        },
    )


# --- /artikel/<ulid>/lebenszyklus — publish / unpublish (Slice C, spec §6.2) -------


def article_lifecycle(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/lebenszyklus`` — the lifecycle transition, CAS-guarded (ADR 0013
    applies to lifecycle too). ``aktion=veroeffentlichen`` → PUBLISHED; ``aktion=zurueckziehen`` →
    DRAFT. Archivist-only; non-archivist / malformed / absent / GET → the byte-identical 404. A
    ``Conflict`` re-renders the edit form's state G (the ONE catch site is ``save_catalog_form``).
    An unknown aktion is a no-op 404 (never mutate on a bad verb)."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    store, stored = gated
    lifecycle = _lifecycle_for(request.POST.get("aktion", ""))
    if lifecycle is None:
        return _not_found()  # unknown verb → no mutation, indistinguishable 404
    # Publishing REQUIRES the over-exposure confirm (spec §6.2): the checkbox rides the /vorschau
    # panel form, so a publish POST without it never saw the preview — re-show the preview instead
    # of publishing blind (server-enforced, not just the client-side `required` attr).
    if lifecycle is Lifecycle.PUBLISHED and request.POST.get("geprueft") != "1":
        collections = _collections(store)
        context = _edit_context_from_article(
            stored.article, stored.version, collections, autofocus_first_empty=False
        )
        context["vorschau"] = _preview_view_model(store, stored.article)
        return render(request, "workbench/artikel_bearbeiten.html", context)
    expected_version = catalog.parse_version(request.POST.get("expected_version", ""))
    mutated = replace(stored.article, lifecycle=lifecycle)
    outcome = catalog.save_catalog_form(store, mutated, expected_version)
    match outcome:
        case catalog.SavedOutcome():
            return HttpResponseRedirect(f"/artikel/{ulid}")
        case catalog.ConflictOutcome() as conflict:
            collections = _collections(store)
            context = _edit_context_from_article(
                conflict.winner, conflict.current_version, collections, autofocus_first_empty=False
            )
            context["conflict"] = True
            context["conflict_rows"] = _conflict_rows(mutated, conflict.winner)
            return render(request, "workbench/artikel_bearbeiten.html", context)


def _lifecycle_for(aktion: str) -> Lifecycle | None:
    """Map the lifecycle POST verb to its target state, or ``None`` for an unknown verb."""
    match aktion:
        case "veroeffentlichen":
            return Lifecycle.PUBLISHED
        case "zurueckziehen":
            return Lifecycle.DRAFT
        case _:
            return None


# --- /artikel/<ulid>/vorschau — over-exposure preview (Slice C, spec §6.2) ---------


def article_vorschau(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/vorschau`` — the over-exposure preview (highest-risk oracle, spec §8):
    ``preview()`` BYPASSES the lifecycle gate by design, so THIS ROUTE GATE is the sole barrier — a
    non-archivist / malformed / absent / GET request must get the byte-identical 404 and NEVER the
    widget content. Archivist: re-render the edit form with the neutral ``c-panel--vorschau`` showing
    who gains sight after publication + the required confirm checkbox that gates Veröffentlichen. No
    save happens here (it is a preview)."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    store, stored = gated
    collections = _collections(store)
    context = _edit_context_from_article(
        stored.article, stored.version, collections, autofocus_first_empty=False
    )
    context["vorschau"] = _preview_view_model(store, stored.article)
    return render(request, "workbench/artikel_bearbeiten.html", context)


@dataclass(frozen=True, slots=True)
class _PreviewViewModel:
    """The over-exposure preview panel data (spec §6.2), built from the domain ``preview()``. NEUTRAL
    by construction — no loud color; the ``public`` flag drives WEIGHT emphasis only. ``audience`` is
    the human-German who-gains-sight string; ``fields`` the visible-field list."""

    audience: str
    public: bool
    fields: str


def _preview_view_model(store: ObjectStore, article: Article) -> _PreviewViewModel | None:
    """Build the preview panel view-model from the domain ``preview(article, chain)`` — server-
    computed, archivist-only. Returns ``None`` if the collection chain cannot resolve (fail-closed:
    no panel rather than a misleading one). The who-sees decision stays entirely in the domain."""
    try:
        chain = resolve_chain(article.collection_id, _collection_map(store))
    except DomainError:
        return None
    result = preview(article, chain)
    return _PreviewViewModel(
        audience=_preview_audience_label(result),
        public=result.public,
        fields=_preview_fields_label(result),
    )


def _collection_map(store: ObjectStore) -> dict[Ulid, Collection]:
    """Every saved Collection as a ULID→Collection map for ``resolve_chain`` (chain resolution is
    injected the lookup, never fetches — domain purity)."""
    return {c.ulid: c for c in CollectionRepository(store).load_all()}


def _preview_audience_label(result: VisibilityPreview) -> str:
    """The who-gains-sight string for the preview panel (spec §6.2): the widest rung the article
    would reach after publication, in plain German."""
    if result.public:
        return "Öffentlich"
    if result.groups:
        return "Gruppe: " + ", ".join(result.groups)
    if result.members:
        return "Alle Mitglieder"
    return "Niemand (kein Bestand-Zugriff)"


# The member-visible fields, in a stable German-labelled display order, for the preview's "Sichtbare
# Felder:" line. Only the fields a non-archivist could see (ARCHIVIST_ONLY_FIELDS are excluded by
# the domain preview's visible_fields set); Standort/interne Felder are called out as hidden.
_VISIBLE_FIELD_LABELS: tuple[tuple[str, str], ...] = (
    ("title", "Titel"),
    ("ref_code", "Signatur"),
    ("media_type", "Medienart"),
    ("document_type", "Dokumenttyp"),
    ("tags", "Schlagworte"),
    ("date", "Datierung"),
    ("creator", "Autor"),
    ("subject_place", "Ort"),
    ("body", "Beschreibung"),
    ("media", "Medien"),
)


def _preview_fields_label(result: VisibilityPreview) -> str:
    """The "Sichtbare Felder:" list for the preview panel (spec §6.2) — the member-visible fields the
    domain reports, in display order. Empty when nobody would see the article."""
    names = tuple(
        label for field_name, label in _VISIBLE_FIELD_LABELS if field_name in result.visible_fields
    )
    return ", ".join(names)
