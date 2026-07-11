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
article form uses (``catalog_views._SICHTBARKEIT_OPTIONS`` / ``catalog._parse_audience``) — the
GROUPS-iff invariant is security-critical, so it is reused verbatim, never re-implemented.
"""

from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app import create_collection
from bundesarchiv.app.web.catalog import FormErrors, _parse_audience
from bundesarchiv.app.web.catalog_views import _SICHTBARKEIT_OPTIONS
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.models import Collection
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.objectstore import ObjectStore


def _canonical_store() -> ObjectStore:
    """The canonical files-store, built per request from settings — same construction the cataloging
    views use. Monkeypatchable in tests."""
    return LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))


def _is_archivist(request: HttpRequest) -> bool:
    return isinstance(viewer_of(request), Archivist)


def _collections(store: ObjectStore) -> tuple[Collection, ...]:
    return CollectionRepository(store).load_all()


def _parent_options(collections: tuple[Collection, ...]) -> tuple[tuple[str, str], ...]:
    """The Eltern-Bestand select options: the empty top-level option first (a top-level Bestand has
    no parent), then each existing collection as ``(ulid, name)``."""
    return (("", "— Oberste Ebene —"), *((c.ulid, c.name) for c in collections))


# --- /bestand/neu — create -----------------------------------------------------------


def collection_create(request: HttpRequest) -> HttpResponseBase:
    """``GET/POST /bestand/neu`` — create a Bestand. Archivist-only (non-archivist → the byte-identical
    404, both methods). POST validates (Name required; parent must be the top-level option or a real
    collection; GROUPS-iff), creates, and 302s to the workbench filtered to the new Bestand; a
    validation failure re-renders with the verbatim error + preserved values."""
    if not _is_archivist(request):
        return _not_found()
    store = _canonical_store()
    collections = _collections(store)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        parent_id = request.POST.get("parent_id", "").strip()
        sichtbarkeit = request.POST.get("sichtbarkeit", "")
        gruppen = request.POST.get("gruppen", "")
        audience, audience_error = _parse_audience(sichtbarkeit, gruppen)
        errors = _create_errors(name, parent_id, collections, audience_error)
        if not errors:
            result = create_collection(
                store, name=name, parent_id=parent_id or None, audience=audience
            )
            return HttpResponseRedirect(f"/?bestand={result.ulid}")
        return render(
            request,
            "workbench/bestand_neu.html",
            _create_context(collections, name, parent_id, sichtbarkeit, gruppen, errors),
        )
    return render(
        request,
        "workbench/bestand_neu.html",
        _create_context(collections, "", "", "", "", {}),
    )


def _create_errors(
    name: str,
    parent_id: str,
    collections: tuple[Collection, ...],
    audience_error: str | None,
) -> FormErrors:
    """The create-Bestand validations (verbatim German). Name required; a non-empty parent must be a
    real collection (validated against the actual set — no oracle); the GROUPS-iff audience error (if
    any) rides the Sichtbarkeit field. An empty parent is the valid top-level choice."""
    errors: FormErrors = {}
    if not name:
        errors["name"] = "Name ist erforderlich."
    if parent_id and parent_id not in {c.ulid for c in collections}:
        errors["parent_id"] = "Bitte einen gültigen Eltern-Bestand wählen."
    if audience_error is not None:
        errors["sichtbarkeit"] = audience_error
    return errors


def _create_context(
    collections: tuple[Collection, ...],
    name: str,
    parent_id: str,
    sichtbarkeit: str,
    gruppen: str,
    errors: FormErrors,
) -> dict[str, object]:
    """The create form's template context: preserved values, the parent + Sichtbarkeit options, field
    errors, and the server-computed autofocus (Name, unless it already has a value)."""
    return {
        "name": name,
        "parent_id": parent_id,
        "sichtbarkeit": sichtbarkeit,
        "gruppen": gruppen,
        "parent_options": _parent_options(collections),
        "sichtbarkeit_options": _SICHTBARKEIT_OPTIONS,
        "errors": errors,
        "autofocus": "parent_id" if name and "name" not in errors else "name",
    }
