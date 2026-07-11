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

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
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
    MediaRef,
    Ulid,
)
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError, Conflict
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


def _redirect(request: HttpRequest, location: str) -> HttpResponseBase:
    """Redirect to ``location`` — a normal 302 for a plain POST, or a 200 carrying ``HX-Redirect`` for
    an HTMX request so htmx does a full browser navigation (spec §5: delete confirm HX-Redirects to /;
    a saved form navigates to the read view). One helper so the enhancement never forks the render:
    the destination is identical, only the mechanism differs by request kind."""
    if request.headers.get("HX-Request"):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = location
        return response
    return HttpResponseRedirect(location)


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
    edit form; a validation failure re-renders state B with the verbatim error + preserved values.

    On GET, a ``?bestand=<ulid>`` param pre-selects that Bestand (validated against the real set,
    ignored if bogus — no oracle) and a ``?angelegt=<name>`` param shows a success hinweis — the
    landing after creating a Bestand (4.8), so create-Bestand → catalog-an-article is one flow."""
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
    # GET: pre-select the ?bestand only if it is a real collection (else ignore — no oracle); show a
    # "Bestand … angelegt." status line when ?angelegt carries the just-created Bestand's name.
    preselect = request.GET.get("bestand", "")
    if preselect not in {c.ulid for c in collections}:
        preselect = ""
    return render(
        request,
        "workbench/artikel_neu.html",
        _create_context(
            collections,
            title="",
            collection_id=preselect,
            errors={},
            angelegt=request.GET.get("angelegt", ""),
        ),
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
    angelegt: str = "",
) -> dict[str, object]:
    """The create form's template context: preserved values, the Bestand options, field errors, and
    the server-computed autofocus target (Titel unless it already has a value). ``angelegt`` is the
    just-created Bestand's name for the success hinweis (empty on the plain create step)."""
    return {
        "title": title,
        "collection_id": collection_id,
        "collection_options": _collection_options(collections),
        "errors": errors,
        "autofocus": "collection_id" if title and "title" not in errors else "title",
        "angelegt": angelegt,
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
        return _handle_edit_post(request, store, ulid, stored.article, collections)
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
    current: Article,
    collections: tuple[Collection, ...],
) -> HttpResponseBase:
    """Parse + save the edit POST. On a validation error re-render state F (first errored field
    autofocused). On success 302 to the read view. On ``Conflict`` re-render state G with the
    submitted values preserved (the ONE catch site is ``catalog.save_catalog_form``). A
    ``custom_entfernen`` submit is the no-JS custom-row removal — it re-renders the form with that
    row cleared, without saving (spec §5). The current media + lifecycle ride the parse so the
    metadata save preserves them (only captions update; media structure is its own POSTs)."""
    if "custom_entfernen" in request.POST:
        return _rerender_with_custom_removed(request, ulid, collections)
    result = catalog.parse_edit_form(
        request.POST,
        ulid=ulid,
        collections=tuple(c.ulid for c in collections),
        current_media=current.media,
        current_lifecycle=current.lifecycle,
    )
    if result.article is None:
        context = _edit_context_from_post(
            request,
            ulid,
            result,
            collections,
            autofocus=_first_error_field(result.errors),
            media=current.media,
        )
        return render(request, "workbench/artikel_bearbeiten.html", context)
    outcome = catalog.save_catalog_form(store, result.article, result.expected_version)
    match outcome:
        case catalog.SavedOutcome(result=save_result):
            # State H (ADR 0014): the canonical write stood but the sync index update failed and a
            # retry job was enqueued — re-render (not 302) with the quiet index-lag hinweis so the
            # archivist knows the visibility change is not yet effective in search. Otherwise 302.
            if not save_result.index_updated:
                return _rerender_edit(request, store, ulid, index_lag=True)
            return _redirect(request, f"/artikel/{ulid}")
        case catalog.ConflictOutcome() as conflict:
            context = _edit_context_from_post(
                request,
                ulid,
                result,
                collections,
                autofocus="speichern",
                media=conflict.winner.media,
                conflict=conflict,
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
    entfernen_hash: str = "",
) -> dict[str, object]:
    """The edit form context seeded from a stored Article (the GET path). Autofocus lands on the
    first empty field (spec §5) when requested. The media register renders the stored media, cover-
    first; ``entfernen_hash`` puts one row into the remove-confirm state."""
    values = _article_to_form_values(article)
    autofocus = _first_empty_field(values) if autofocus_first_empty else ""
    return _edit_context(
        values,
        version,
        collections,
        errors={},
        autofocus=autofocus,
        media=article.media,
        entfernen_hash=entfernen_hash,
    )


def _edit_context_from_post(
    request: HttpRequest,
    ulid: Ulid,
    result: catalog.ParseResult,
    collections: tuple[Collection, ...],
    *,
    autofocus: str,
    media: tuple[MediaRef, ...],
    conflict: catalog.ConflictOutcome | None = None,
) -> dict[str, object]:
    """The edit form context re-seeded from the raw POST (state F/G): the archivist's just-typed
    values are preserved verbatim. On a ``Conflict`` the hidden ``expected_version`` is refreshed to
    the winner's current version and the neutral diff rows are attached (spec §6.1). ``media`` is the
    stored media (structure isn't POSTed via the main form), so the register renders correctly."""
    values = _post_to_form_values(request, ulid)
    version = conflict.current_version if conflict is not None else result.expected_version
    context = _edit_context(
        values, version, collections, errors=result.errors, autofocus=autofocus, media=media
    )
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
    media: tuple[MediaRef, ...] = (),
    entfernen_hash: str = "",
) -> dict[str, object]:
    """Assemble the full edit-form context: the field values, the option lists, the field errors, the
    hidden version, and the autofocus target. The Signatur mark in the header reflects the current
    ``ref_code`` value (empty → the hollow slot). The media register rows come from the stored media
    (structure is edited via its own POSTs, never the main form); ``entfernen_hash`` puts one row
    into the two-step "Wirklich entfernen?" confirm state (spec §6.3)."""
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
        "media_rows": _media_rows(str(values.get("ulid") or ""), media, entfernen_hash),
    }


@dataclass(frozen=True, slots=True)
class _MediaRow:
    """One media register row for the edit-form template (spec §6.3). Built on the ledger grid: the
    thumb URL (via the gated media-thumb route, which re-authorizes per request), the filename +
    human byte size (mono marks), the caption input value, and structural flags. ``is_cover`` marks
    the FIRST row — the TITELBILD cover stamp is a NEUTRAL-INK INVERSION (never amber/violet/tint), a
    position-state expressed like the active facet row. ``confirm_remove`` puts this row into the
    two-step remove confirm. ``is_first``/``is_last`` disable the reorder links at the ends."""

    filename: str
    content_hash: str
    thumb_url: str
    size: str
    caption: str
    is_cover: bool
    is_first: bool
    is_last: bool
    confirm_remove: bool


def _media_rows(
    ulid: str, media: tuple[MediaRef, ...], entfernen_hash: str
) -> tuple[_MediaRow, ...]:
    """The media register view-models, cover-first (the tuple's order is meaning, ADR 0015). The
    thumb URL points at the gated ``/media/<ulid>/<hash>/thumb`` route (re-authorizes on its own —
    the edit form never bypasses media auth). ``entfernen_hash`` flags the one row in remove-confirm
    state."""
    last = len(media) - 1
    return tuple(
        _MediaRow(
            filename=ref.filename,
            content_hash=ref.content_hash,
            thumb_url=f"/media/{ulid}/{ref.content_hash}/thumb",
            size=_human_size(ref.byte_size),
            caption=ref.caption or "",
            is_cover=i == 0,
            is_first=i == 0,
            is_last=i == last,
            confirm_remove=ref.content_hash == entfernen_hash,
        )
        for i, ref in enumerate(media)
    )


def _human_size(byte_size: int | None) -> str:
    """A compact human byte size (mono meta mark). Absent → empty."""
    if byte_size is None:
        return ""
    size = float(byte_size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


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
        return _redirect(request, "/")  # HTMX: HX-Redirect to the workbench (spec §5)
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
            return _redirect(request, f"/artikel/{ulid}")
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


# --- media manager: structural POSTs (Slice D, spec §6.3 + ADR 0015) ---------------
#
# Reorder / remove / upload are SEPARATE structural POSTs, distinct from the caption metadata save
# (captions ride the main form's save_article, spec §6.3). They are "non-CAS" in that they do NOT
# ride the edit form's expected_version: each re-loads the article at its current version, applies a
# pure idempotent transform of the media tuple, and saves at THAT version, retrying once on a
# concurrent bump (safe because the transform is idempotent — "move hash X up", "drop hash Y",
# "append these blobs" re-applied to the winner's fresh article yields the same intent). Order is
# meaning (first = cover, ADR 0015), so reorder is re-cover and upload appends at the END.

#: How many bytes a single upload request may carry / a single file may be (spec §8). Kept modest for
#: a v1 archive of scans; the settings mirror lets the deploy raise them. Oversize → a clean German
#: error, never a 500.
_MAX_UPLOAD_BYTES = getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 50 * 1024 * 1024)

#: How many times a structural media save retries a concurrent version bump before giving up and
#: telling the archivist to try again (rare: single-app-process, a handful of writers).
_STRUCTURAL_SAVE_ATTEMPTS = 3

#: The German hinweis shown when a structural media change lost every race (see _structural_save).
_MEDIEN_KONFLIKT = "Konnte nicht gespeichert werden — bitte erneut versuchen."


def article_medien_verschieben(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/medien/verschieben`` — reorder one media entry up/down (``richtung`` =
    ``hoch``/``runter``, ``hash`` = the entry). Order defines the cover, so reorder = re-cover (spec
    §6.3). Archivist-only, POST-only → byte-identical 404 otherwise. Structural, non-CAS: re-render
    the edit form afterwards. A bad hash / edge move is a no-op (never raises)."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    store, _ = gated
    content_hash = request.POST.get("hash", "")
    richtung = request.POST.get("richtung", "")
    saved = _structural_save(store, ulid, lambda media: _reordered(media, content_hash, richtung))
    return _rerender_edit(request, store, ulid, medien_fehler="" if saved else _MEDIEN_KONFLIKT)


def article_medien_entfernen(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/medien/entfernen`` — the two-step no-JS remove (spec §6.3). First POST
    (``entfernen``=hash) re-renders the edit form with that row in the "Wirklich entfernen? [Ja]
    [Nein]" confirm state — NO removal yet. The [Ja] POST (``bestaetigt``=1) actually drops the ref
    (the blob is write-once and stays, recoverable). Archivist-only, POST-only → 404 otherwise."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    store, _ = gated
    content_hash = request.POST.get("entfernen", "")
    if request.POST.get("bestaetigt") == "1":
        saved = _structural_save(store, ulid, lambda media: _without(media, content_hash))
        return _rerender_edit(request, store, ulid, medien_fehler="" if saved else _MEDIEN_KONFLIKT)
    # step 1: show the inline confirm for this row (no mutation)
    return _rerender_edit(request, store, ulid, entfernen_hash=content_hash)


def article_medien_hochladen(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/medien/hochladen`` — attach one or more files (multipart ``dateien``).
    Each blob is stored content-addressed (write-once: identical bytes = a no-op attach) and its ref
    appended at the END (never displacing the cover, ADR 0015). Archivist-only, POST-only → 404
    otherwise. Oversize → a clean German error, not a 500. The blob MUST persist before the README
    references it (repository.save raises otherwise) — ``add_media`` writes the blob, then the
    structural save commits the refs."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    store, _ = gated
    files = request.FILES.getlist("dateien")
    oversize = any(f.size is not None and f.size > _MAX_UPLOAD_BYTES for f in files)
    if oversize:
        return _rerender_edit(
            request, store, ulid, medien_fehler="Datei zu groß. Bitte kleinere Dateien hochladen."
        )
    repo = ArticleRepository(store)
    new_refs = [
        repo.add_media(ulid, f.name or "datei", f.read(), f.content_type or None) for f in files
    ]  # add_media persists each blob (write-once) BEFORE any ref is committed
    saved = True
    if new_refs:
        saved = _structural_save(store, ulid, lambda media: (*media, *new_refs))
    return _rerender_edit(request, store, ulid, medien_fehler="" if saved else _MEDIEN_KONFLIKT)


def _structural_save(
    store: ObjectStore,
    ulid: Ulid,
    transform: Callable[[tuple[MediaRef, ...]], tuple[MediaRef, ...]],
) -> bool:
    """Apply an idempotent structural transform to the article's media tuple and save via the service
    (canonical write + index sync), retrying on a concurrent version bump (safe: the transform
    re-applies to the winner's fresh media with the same intent). Non-CAS from the form's view — it
    re-loads the current version rather than trusting the form's expected_version (spec §6.3).

    Returns True on a committed save, False if every attempt lost the race (so the caller surfaces a
    German hinweis rather than silently pretending the change stuck)."""
    repo = ArticleRepository(store)
    for _ in range(_STRUCTURAL_SAVE_ATTEMPTS):
        stored = repo.load(ulid)
        mutated = replace(stored.article, media=transform(stored.article.media))
        try:
            article_services.save_article(store, mutated, stored.version)
            return True
        except Conflict:
            continue  # a concurrent write won; re-load and re-apply the idempotent transform
    return False


def _reordered(
    media: tuple[MediaRef, ...], content_hash: str, richtung: str
) -> tuple[MediaRef, ...]:
    """Move the entry named by ``content_hash`` one step ``hoch`` (earlier) or ``runter`` (later). A
    missing hash, an unknown direction, or a move past an edge is a no-op (returns the tuple as-is)."""
    index = next((i for i, r in enumerate(media) if r.content_hash == content_hash), None)
    if index is None:
        return media
    target = index - 1 if richtung == "hoch" else index + 1 if richtung == "runter" else index
    if not (0 <= target < len(media)) or target == index:
        return media
    items = list(media)
    items[index], items[target] = items[target], items[index]
    return tuple(items)


def _without(media: tuple[MediaRef, ...], content_hash: str) -> tuple[MediaRef, ...]:
    """The media tuple without the entry named by ``content_hash`` (the blob stays on disk, write-once
    recoverable). A missing hash is a no-op."""
    return tuple(r for r in media if r.content_hash != content_hash)


def _rerender_edit(
    request: HttpRequest,
    store: ObjectStore,
    ulid: Ulid,
    *,
    entfernen_hash: str = "",
    medien_fehler: str = "",
    index_lag: bool = False,
) -> HttpResponseBase:
    """Re-render the edit form after a structural media change (or the remove-confirm step, or a
    saved-but-index-lagged metadata save). Re-loads the article so the register + fields reflect the
    just-applied change. ``entfernen_hash`` shows one row's inline remove-confirm; ``medien_fehler``
    surfaces an upload error above the register; ``index_lag`` shows the ADR-0014 state-H hinweis."""
    stored = ArticleRepository(store).load(ulid)
    collections = _collections(store)
    context = _edit_context_from_article(
        stored.article,
        stored.version,
        collections,
        autofocus_first_empty=False,
        entfernen_hash=entfernen_hash,
    )
    if medien_fehler:
        context["medien_fehler"] = medien_fehler
    if index_lag:
        context["index_lag"] = "Gespeichert. Die Suche zeigt die Änderung in Kürze."
    return render(request, "workbench/artikel_bearbeiten.html", context)


# --- HTMX enhancement partials (Slice E, spec §5) ----------------------------------
# Two archivist-gated GET transforms the edit form's HTMX layer swaps in. Both have a no-JS baseline
# already shipped (the grouped optgroup select; the server-side echo after submit), so these ONLY
# remove a round-trip. Pure transforms, no mutation. Gated via _load_gated -> byte-identical 404 for
# anyone else and NEVER partial content (they join the 4.10 leak suite).


def article_dokumenttypen(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /artikel/<ulid>/dokumenttypen?medienart=`` — the Dokumenttyp option list for one
    Medienart (spec §5). Archivist-only, GET-only. The no-JS baseline renders all types grouped by
    Medienart; this returns just the chosen Medienart's options for an HTMX inner-swap."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "GET":
        return _not_found()
    # htmx sends the <select name="media_type"> value under that name; accept ?medienart= too so the
    # endpoint is callable directly with the German param name.
    media_type = request.GET.get("media_type") or request.GET.get("medienart", "")
    return render(
        request,
        "workbench/_dokumenttyp_options.html",
        {"document_types": vocab.document_types_for(media_type)},
    )


def article_datierung_echo(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /artikel/<ulid>/datierung-echo?date=`` — the human-German EDTF echo line (spec §5).
    Archivist-only, GET-only. Empty echo for an unparseable value (no error surface while typing —
    validation errors ride the field on submit, not the echo)."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "GET":
        return _not_found()
    return render(
        request,
        "workbench/_datierung_echo.html",
        {"edtf_echo": _edtf_echo(request.GET.get("date", ""))},
    )
