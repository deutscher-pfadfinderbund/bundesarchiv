"""A create may set Sichtbarkeit (an empty Bestand exposes nothing); a rename changes the Name
only, since moving or re-scoping a Bestand needs the over-exposure gate."""

from dataclasses import replace

from django.http import HttpRequest
from django.http.response import HttpResponseBase

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.collections import create_collection, save_collection
from bundesarchiv.app.web import landing
from bundesarchiv.app.web.browse import PARAM_COLLECTION
from bundesarchiv.app.web.browse_views import collection_crumbs, preset_url
from bundesarchiv.app.web.catalog import (
    FormErrors,
    audience_choice,
    one_line,
    parse_audience,
    parse_version,
)
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.media_views import not_found
from bundesarchiv.app.web.panels import (
    FormPanel,
    collection_rows,
    edit_collection_panel,
    new_collection_panel,
)
from bundesarchiv.app.web.viewers import (
    is_partial,
    panel_response,
    redirect_to,
    render_screen,
    viewer_of,
)
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import ULID
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.collections import StoredCollection
from bundesarchiv.persistence.errors import ArchiveError, Conflict

# --- /collections/new — create -----------------------------------------------------------


def collection_create(request: HttpRequest) -> HttpResponseBase:
    """``GET/POST /collections/new`` — create a Bestand."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist):
        return not_found()
    archive = Archive.canonical()
    chooser = CollectionChooser.of(archive)
    if request.method == "POST":
        choice = audience_choice(request.POST)
        if choice is None:
            # no rung named: the form always posts one, and none is narrow enough to assume
            return not_found()
        name = one_line(request.POST.get("name", ""))
        parent_id = request.POST.get("parent_id", "").strip()
        groups_text = request.POST.get("groups", "")
        audience, audience_error = parse_audience(request.POST, keep=None)
        errors = _create_errors(name, parent_id, chooser, audience_error)
        if not errors:
            result = create_collection(
                archive,
                changed_by=archivist.username,
                name=name,
                parent_id=chooser.resolve(parent_id),
                audience=audience,
            )
            return redirect_to(request, landing.created_collection_url(result.ulid))
        rows = collection_rows(chooser, name, parent_id, choice, groups_text, errors)
        if is_partial(request):
            return panel_response(request, new_collection_panel(rows))
        return render_screen(
            request, "workbench/collection_new.html", {"fields": rows}, chooser=chooser
        )
    return render_screen(
        request,
        "workbench/collection_new.html",
        {"fields": collection_rows(chooser, "", "", "", "", {})},
        chooser=chooser,
    )


def _create_errors(
    name: str,
    parent_id: str,
    chooser: CollectionChooser,
    audience_error: str | None,
) -> FormErrors:
    """Not ``chooser.error()``: an empty parent is the valid top level, so "Bitte einen Bestand
    wählen." would mislead."""
    errors: FormErrors = {}
    if not name:
        errors["name"] = "Name ist erforderlich."
    if parent_id and not chooser.accepts(parent_id):
        errors["parent_id"] = "Bitte einen gültigen Eltern-Bestand wählen."
    if audience_error is not None:
        errors["audience"] = audience_error
    return errors


# --- /collections/<ulid>/edit — rename (SLIM: Name only) ---------------------------


def collection_edit(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /collections/<ulid>/edit`` — rename a Bestand (CAS, ADR 0013)."""
    gated = _load_gated_collection(request, ulid)
    if gated is None:
        return not_found()
    archive, ulid, stored, archivist = gated
    chooser = CollectionChooser.of(archive)
    if request.method == "POST":
        name = one_line(request.POST.get("name", ""))
        expected_version = parse_version(request.POST.get("expected_version", ""))
        if not name:
            return _render_edit(
                request,
                ulid,
                chooser,
                edit_collection_panel(
                    chooser, stored, name, {"name": "Name ist erforderlich."}, expected_version
                ),
            )
        try:
            save_collection(
                archive,
                replace(stored.collection, name=name),
                expected_version,
                changed_by=archivist.username,
            )
        except Conflict:
            # ADR 0013: show the winner, the submitted name kept
            winner = archive.collections.load(ulid)
            return _render_edit(
                request,
                ulid,
                chooser,
                edit_collection_panel(
                    chooser, winner, name, {}, winner.version, conflict_name=winner.collection.name
                ),
            )
        return redirect_to(request, preset_url(PARAM_COLLECTION, ulid))
    return _render_edit(
        request,
        ulid,
        chooser,
        edit_collection_panel(chooser, stored, stored.collection.name, {}, stored.version),
    )


def _render_edit(
    request: HttpRequest, ulid: ULID, chooser: CollectionChooser, panel: FormPanel
) -> HttpResponseBase:
    """The rename form: in place as its tool panel when htmx asked, else as the page."""
    if is_partial(request):
        return panel_response(request, panel)
    chain = chooser.chain_of(ulid)
    return render_screen(
        request,
        "workbench/collection_edit.html",
        {
            "panel": panel,
            "cancel_href": preset_url(PARAM_COLLECTION, ulid),
            "crumbs": () if chain is None else collection_crumbs(chain),
        },
        chooser=chooser,
    )


def _load_gated_collection(
    request: HttpRequest, ulid: str
) -> tuple[Archive, ULID, StoredCollection, Archivist] | None:
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist) or not is_valid_ulid(ulid):
        return None
    archive = Archive.canonical()
    try:
        return archive, ulid, archive.collections.load(ulid), archivist
    except ArchiveError:
        return None
