"""Bestand (Collection) management views (Part 4.8 SLIM): create + rename.

Two archivist-only routes, both methods gated to the byte-identical 404 (existence-hiding, no oracle):

- ``/bestand/neu`` (create): Name + Eltern-Bestand + Sichtbarkeit. Audience-at-creation is SAFE — a
  fresh collection is empty, so no over-exposure is possible. Reuses the 4.7 form grammar wholesale
  (the c-form group, the Sichtbarkeit select + GROUPS-iff parse, verbatim German error strings,
  ""→None, autofocus on Name).
- ``/bestand/<ulid>/bearbeiten`` (rename): Name ONLY. Parent + Sichtbarkeit render as quiet READ-ONLY
  display rows with one hint — moving + changing visibility are deferred (the parked pile), because
  they can move descendants' visibility and need the over-exposure machinery a rename does not.

The Sichtbarkeit option vocabulary + the GROUPS-iff audience parse are the SAME single source the 4.7
article form uses (``vocab.SICHTBARKEIT_OPTIONS`` / ``catalog.parse_audience``) — the
GROUPS-iff invariant is security-critical, so it is reused verbatim, never re-implemented.
"""

from dataclasses import replace
from urllib.parse import urlencode

from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.urls import reverse

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.collections import create_collection, save_collection
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.catalog import FormErrors, parse_audience, parse_version
from bundesarchiv.app.web.catalog_views import _panel_response, _redirect
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.panels import (
    FormPanel,
    bestand_bearbeiten_panel,
    bestand_rows,
    neu_bestand_panel,
)
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.collections import StoredCollection
from bundesarchiv.persistence.errors import ArchiveError, Conflict

# --- /bestand/neu — create -----------------------------------------------------------


def collection_create(request: HttpRequest) -> HttpResponseBase:
    """``GET/POST /bestand/neu`` — create a Bestand. Archivist-only (non-archivist → the byte-identical
    404, both methods). POST validates (Name required; parent must be the top-level option or a real
    collection; GROUPS-iff), creates, and 302s to the workbench filtered to the new Bestand; a
    validation failure re-renders with the verbatim error + preserved values."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist):
        return _not_found()
    archive = Archive.canonical()
    bestand = BestandChooser.of(archive)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        parent_id = request.POST.get("parent_id", "").strip()
        sichtbarkeit = request.POST.get("sichtbarkeit", "")
        gruppen = request.POST.get("gruppen", "")
        audience, audience_error = parse_audience(sichtbarkeit, gruppen)
        errors = _create_errors(name, parent_id, bestand, audience_error)
        if not errors:
            result = create_collection(
                archive,
                changed_by=archivist.username,
                name=name,
                parent_id=parent_id or None,
                audience=audience,
            )
            # Land on the create-article form with the new Bestand PRE-SELECTED + a success hinweis
            # (create→catalog is one flow, design-gate blocker 2). The name rides ?angelegt= for the
            # "Bestand … angelegt." status line; artikel_neu validates ?bestand against the real set.
            query = urlencode({"bestand": result.ulid, "angelegt": name})
            return _redirect(request, f"{reverse('artikel-neu')}?{query}")
        rows = bestand_rows(bestand, name, parent_id, sichtbarkeit, gruppen, errors)
        if request.headers.get("HX-Request"):
            return _panel_response(request, neu_bestand_panel(rows))
        return render_screen(
            request, "workbench/bestand_neu.html", {"felder": rows}, bestand=bestand
        )
    return render_screen(
        request,
        "workbench/bestand_neu.html",
        {"felder": bestand_rows(bestand, "", "", "", "", {})},
        bestand=bestand,
    )


def _create_errors(
    name: str,
    parent_id: str,
    bestand: BestandChooser,
    audience_error: str | None,
) -> FormErrors:
    """The create-Bestand validations (verbatim German). Name required; a non-empty parent must be a
    Bestand the chooser accepts; the GROUPS-iff audience error (if any) rides the Sichtbarkeit field.
    An empty parent is the valid top-level choice, so it is the ONE value skipping the check — and it
    earns its own wording, since "kein Eltern-Bestand" is not the article form's missing Bestand."""
    errors: FormErrors = {}
    if not name:
        errors["name"] = "Name ist erforderlich."
    if parent_id and not bestand.accepts(parent_id):
        errors["parent_id"] = "Bitte einen gültigen Eltern-Bestand wählen."
    if audience_error is not None:
        errors["sichtbarkeit"] = audience_error
    return errors


# --- /bestand/<ulid>/bearbeiten — rename (SLIM: Name only) ---------------------------


def collection_edit(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /bestand/<ulid>/bearbeiten`` — rename a Bestand. SLIM: the Name field ONLY; parent
    + Sichtbarkeit render READ-ONLY (moving + visibility changes are deferred — they move descendants'
    visibility and need machinery a rename does not). Archivist-only; a non-archivist, malformed, or
    absent ulid all collapse to the byte-identical 404. POST saves against the form's
    ``expected_version`` (ADR 0013). ``save_collection`` reindexes the subtree so the new name is live
    in facets; a blank Name re-renders with the verbatim error, unchanged."""
    gated = _load_gated_collection(request, ulid)
    if gated is None:
        return _not_found()
    archive, stored, archivist = gated
    bestand = BestandChooser.of(archive)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        expected_version = parse_version(request.POST.get("expected_version", ""))
        if not name:
            return _render_edit(
                request,
                ulid,
                bestand,
                bestand_bearbeiten_panel(
                    bestand, stored, name, {"name": "Name ist erforderlich."}, expected_version
                ),
            )
        # rename ONLY: keep parent_id + audience exactly as stored (this slice never changes them).
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
                bestand,
                bestand_bearbeiten_panel(
                    bestand, winner, name, {}, winner.version, conflict_name=winner.collection.name
                ),
            )
        return _redirect(request, _scoped_list(ulid))
    return _render_edit(
        request,
        ulid,
        bestand,
        bestand_bearbeiten_panel(bestand, stored, stored.collection.name, {}, stored.version),
    )


def _render_edit(
    request: HttpRequest, ulid: str, bestand: BestandChooser, panel: FormPanel
) -> HttpResponseBase:
    """The rename form: in place as its tool panel when htmx asked, else as the page."""
    if request.headers.get("HX-Request"):
        return _panel_response(request, panel)
    return render_screen(
        request,
        "workbench/bestand_bearbeiten.html",
        {"panel": panel, "abbrechen": _scoped_list(ulid)},
        bestand=bestand,
    )


def _scoped_list(ulid: str) -> str:
    """The list scoped to the Bestand ``ulid``: where a rename returns and its Abbrechen leads."""
    return f"{reverse('workbench')}?bestand={ulid}"


def _load_gated_collection(
    request: HttpRequest, ulid: str
) -> tuple[Archive, StoredCollection, Archivist] | None:
    """The shared gate for the rename route: archivist-only, validate the ulid in-view, load the
    Collection — returning ``(archive, stored, archivist)`` ONLY if all pass, else ``None`` (the
    caller maps ``None`` to the byte-identical 404). A non-archivist, a malformed ulid, and an
    absent/unreadable collection all collapse to the SAME ``None`` (existence-hiding)."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist) or not is_valid_ulid(ulid):
        return None
    archive = Archive.canonical()
    try:
        return archive, archive.collections.load(ulid), archivist
    except ArchiveError:
        return None
