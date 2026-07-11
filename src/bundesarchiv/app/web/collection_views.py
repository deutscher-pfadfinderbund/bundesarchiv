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

from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app import create_collection, save_collection
from bundesarchiv.app.web.catalog import FormErrors, _parse_audience
from bundesarchiv.app.web.catalog_views import _SICHTBARKEIT_OPTIONS
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Audience, AudienceTier, Collection
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository, StoredCollection
from bundesarchiv.persistence.errors import ArchiveError, Conflict
from bundesarchiv.persistence.objectstore import ObjectStore


def _canonical_store() -> ObjectStore:
    """The canonical files-store, built per request from settings — same construction the cataloging
    views use. Monkeypatchable in tests."""
    return LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))


def _is_archivist(request: HttpRequest) -> bool:
    return isinstance(viewer_of(request), Archivist)


def _collections(store: ObjectStore) -> tuple[Collection, ...]:
    return CollectionRepository(store).load_all()


#: The Eltern-Bestand top-level marker — a Bestand with no parent. One constant so the select
#: placeholder + the read-only parent-display row can never drift.
_TOP_LEVEL_LABEL = "— Oberste Ebene —"


def _parent_options(collections: tuple[Collection, ...]) -> tuple[tuple[str, str], ...]:
    """The Eltern-Bestand select options: the empty top-level option first (a top-level Bestand has
    no parent), then each existing collection as ``(ulid, name)``."""
    return (("", _TOP_LEVEL_LABEL), *((c.ulid, c.name) for c in collections))


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
            # Land on the create-article form with the new Bestand PRE-SELECTED + a success hinweis
            # (create→catalog is one flow, design-gate blocker 2). The name rides ?angelegt= for the
            # "Bestand … angelegt." status line; artikel_neu validates ?bestand against the real set.
            query = urlencode({"bestand": result.ulid, "angelegt": name})
            return HttpResponseRedirect(f"/artikel/neu?{query}")
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


# --- /bestand/<ulid>/bearbeiten — rename (SLIM: Name only) ---------------------------


def collection_edit(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /bestand/<ulid>/bearbeiten`` — rename a Bestand. SLIM: the Name field ONLY; parent
    + Sichtbarkeit render READ-ONLY (moving + visibility changes are deferred — they move descendants'
    visibility and need machinery a rename does not). Archivist-only; a non-archivist, malformed, or
    absent ulid all collapse to the byte-identical 404. POST saves the renamed Collection under CAS
    (via ``save_collection``, which reindexes the subtree so the new name is live in facets); a blank
    Name re-renders with the verbatim error, unchanged."""
    gated = _load_gated_collection(request, ulid)
    if gated is None:
        return _not_found()
    store, stored = gated
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            return render(
                request,
                "workbench/bestand_bearbeiten.html",
                _edit_context(store, stored, name, {"name": "Name ist erforderlich."}),
            )
        # rename ONLY: keep parent_id + audience exactly as stored (this slice never changes them).
        try:
            save_collection(store, replace(stored.collection, name=name), stored.version)
        except Conflict:
            # A concurrent rename won between GET and POST (ADR 0013). Re-load for the fresh version +
            # winner name, re-render the "Inzwischen geändert" panel with the just-submitted name
            # preserved (parity with the article form) — never a 500 (security LOW).
            winner = CollectionRepository(store).load(ulid)
            return render(
                request,
                "workbench/bestand_bearbeiten.html",
                _edit_context(store, winner, name, {}, conflict_name=winner.collection.name),
            )
        return HttpResponseRedirect(f"/?bestand={ulid}")
    return render(
        request,
        "workbench/bestand_bearbeiten.html",
        _edit_context(store, stored, stored.collection.name, {}),
    )


def _load_gated_collection(
    request: HttpRequest, ulid: str
) -> tuple[ObjectStore, StoredCollection] | None:
    """The shared gate for the rename route: archivist-only, validate the ulid in-view, load the
    Collection — returning ``(store, stored)`` ONLY if all pass, else ``None`` (the caller maps
    ``None`` to the byte-identical 404). A non-archivist, a malformed ulid, and an absent/unreadable
    collection all collapse to the SAME ``None`` (existence-hiding)."""
    if not _is_archivist(request) or not is_valid_ulid(ulid):
        return None
    store = _canonical_store()
    try:
        return store, CollectionRepository(store).load(ulid)
    except ArchiveError:
        return None


def _edit_context(
    store: ObjectStore,
    stored: StoredCollection,
    name: str,
    errors: FormErrors,
    conflict_name: str | None = None,
) -> dict[str, object]:
    """The rename form's context: the editable Name (preserved on re-render) + the READ-ONLY parent
    name + Sichtbarkeit label as quiet display strings (this slice edits neither). Autofocus on Name.
    ``conflict_name`` (the winner's name after a racing rename) drives the "Inzwischen geändert"
    panel — None on the normal path."""
    collection = stored.collection
    return {
        "ulid": collection.ulid,
        "name": name,
        "parent_display": _parent_name(store, collection.parent_id),
        "sichtbarkeit_display": _sichtbarkeit_label(collection.audience),
        "errors": errors,
        "conflict_name": conflict_name,
    }


def _parent_name(store: ObjectStore, parent_id: str | None) -> str:
    """The parent Collection's name for the read-only display row, or the top-level marker. A targeted
    load (1 read) rather than a full ``load_all`` scan; a dangling parent (shouldn't happen) shows the
    ulid rather than raising."""
    if parent_id is None:
        return _TOP_LEVEL_LABEL
    try:
        return CollectionRepository(store).load(parent_id).collection.name
    except ArchiveError:
        return parent_id


def _sichtbarkeit_label(audience: Audience | None) -> str:
    """The human Sichtbarkeit label for the read-only display row. ``None`` = inherit (the ADR 0001
    default); otherwise the rung's caption, with the group list for GROUPS. The strings match the
    shared 4.7 source (``catalog_views._audience_label`` / ``_SICHTBARKEIT_OPTIONS``) verbatim."""
    if audience is None:
        return "Vom Bestand erben"
    if audience.tier is AudienceTier.PUBLIC:
        return "Öffentlich"
    if audience.tier is AudienceTier.MEMBERS:
        return "Alle Mitglieder"
    return f"Gruppe: {', '.join(audience.groups)}"
