"""The cataloging-form views (Part 4.7 Slice A+B): create step + full edit form (no-JS baseline).

Two production routes, both archivist-gated to the media route's plain 404 for anyone else
(existence-hiding — the cataloging surface must not be discoverable). Thin by design: the
leak-sensitive parsing + validation live in ``catalog`` (pure, unit-tested), the write services in
``app.articles``, and the form's ADR-0013 ``Conflict`` catch site in ``catalog.save_catalog_form``
(the delete confirm catches its own).
These views only resolve the viewer, gate, and hand an ``EditSurface`` — the record as SAVED plus
whatever the form shows — the overlay its outcome calls for.

- ``article_create`` — ``GET/POST /articles/new``: GET renders the minimal create form (Titel +
  Bestand); POST creates a DRAFT via ``create_article`` and 302s to the edit form. Validation
  re-renders state B (verbatim errors, preserved values).
- ``article_edit`` — ``GET/POST /articles/<ulid>/edit``: GET renders the full form seeded from
  the stored Article; POST parses + saves (CAS on ``expected_version``). A ``Conflict`` re-renders
  the "Inzwischen geändert" panel (state G) with the just-submitted values preserved.

The ``<ulid>`` is validated in-view via ``is_valid_ulid`` (never a route converter), so a malformed
value collapses to the same 404 as an absent one. ``neu`` is registered before ``<str:ulid>`` in
``urls.py`` so the literal path wins.
"""

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import BinaryIO, cast
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest, HttpResponse, QueryDict
from django.http.response import HttpResponseBase
from django.urls import reverse

from bundesarchiv.app import articles as article_services
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import Conflicted, Missing, SaveResult, Updated
from bundesarchiv.app.web import catalog, landing, vocab
from bundesarchiv.app.web.browse_views import (
    CollectionCrumb,
    MediaTile,
    collection_crumbs,
    media_tiles,
)
from bundesarchiv.app.web.card import (
    FIELDS,
    LIFECYCLE_OPTIONS,
    LIFECYCLE_VALUES,
    card_fields,
    first_empty_field,
    first_error_field,
)
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.media_views import not_found
from bundesarchiv.app.web.panels import article_rows, new_article_panel
from bundesarchiv.app.web.viewers import (
    is_partial,
    panel_response,
    redirect_to,
    render_screen,
    viewer_of,
)
from bundesarchiv.domain.access import preview
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import (
    Article,
    Lifecycle,
    MediaRef,
    Ulid,
    Version,
)
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.index.query import suggest_tags
from bundesarchiv.persistence import errors
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.repository import Stored, cleaned_name

#: The refusal when Veröffentlichen arrives for a record whose Bestand chain the domain cannot
#: resolve, said as a field error on the Bestand.
_PUBLISH_UNRESOLVABLE = "Der Bestand lässt sich nicht auflösen — Veröffentlichen ist gesperrt."


def _load_gated(
    request: HttpRequest, ulid: str, *, marked: bool = False
) -> tuple[Archive, Stored, Archivist] | None:
    """The shared gate for every ulid-bearing cataloging route: archivist-only, validate the ulid
    in-view, and load the Article — returning ``(archive, stored, archivist)`` ONLY if all pass,
    else ``None`` (the caller maps ``None`` to the plain 404). A non-archivist, a malformed
    ulid, and an absent/unreadable article all collapse to the SAME ``None`` (existence-hiding,
    spec §8). So does an Article on the wrong side of the Papierkorb: ``marked`` routes take only a
    marked one, every other route only an unmarked one (ADR 0022)."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist) or not is_valid_ulid(ulid):
        return None
    archive = Archive.canonical()
    stored = _load(archive, ulid, marked=marked)
    return None if stored is None else (archive, stored, archivist)


def _load(archive: Archive, ulid: Ulid, *, marked: bool) -> Stored | None:
    """The Article, or ``None`` when it is absent, unreadable or not on the ``marked`` side."""
    try:
        stored = archive.articles.load(ulid)
    except ArchiveError:
        return None
    return stored if (stored.article.deleted is not None) == marked else None


# --- /articles/new — the create step (Slice A) --------------------------------------


def article_create(request: HttpRequest) -> HttpResponseBase:
    """``GET/POST /articles/new`` — the minimal create step. Archivist-only (non-archivist → the
    plain 404, both methods). POST creates a DRAFT with just Titel + Bestand and 302s to the
    edit form; a validation failure re-renders state B with the verbatim error + preserved values.

    On GET, a ``?collection=<ulid>`` param pre-selects that Bestand (validated against the real set,
    ignored if bogus — no oracle) and ``?created=1`` announces it as just created — the
    landing after creating a Bestand (4.8), so create-Bestand → catalog-an-article is one flow."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist):
        return not_found()
    archive = Archive.canonical()
    chooser = CollectionChooser.of(archive)
    if request.method == "POST":
        title = catalog.one_line(request.POST.get("title", ""))
        collection_id = request.POST.get("collection_id", "").strip()
        errors = _create_errors(title, collection_id, chooser)
        if not errors:
            created = article_services.create_article(
                archive, changed_by=archivist.username, title=title, collection_id=collection_id
            )
            edit = reverse("article-edit", args=[created.ulid])
            return redirect_to(request, landing.noting_lag(edit, created.index_updated))
        if is_partial(request):
            return panel_response(
                request,
                new_article_panel(chooser, title=title, collection_id=collection_id, errors=errors),
            )
        return render_screen(
            request,
            "workbench/article_new.html",
            _create_context(chooser, title=title, collection_id=collection_id, errors=errors),
            chooser=chooser,
        )
    # GET: pre-select the Bestand only if it is a real collection (else ignore — no oracle); the
    # "Bestand … angelegt." line shows the name of a real Bestand, never text from the URL.
    return render_screen(
        request,
        "workbench/article_new.html",
        _create_context(
            chooser,
            title="",
            collection_id=landing.preselected_collection(request, chooser),
            errors={},
            just_created=landing.created_collection_name(request, chooser),
        ),
        chooser=chooser,
    )


def _create_errors(
    title: str, collection_id: str, chooser: CollectionChooser
) -> catalog.FormErrors:
    """The two create-step validations (spec §2), verbatim strings — the same two rules the full
    parse layer applies, kept minimal here because the create step has only these two fields."""
    errors: catalog.FormErrors = {}
    if not title:
        errors["title"] = "Titel ist erforderlich."
    if not chooser.accepts(collection_id):
        errors["collection_id"] = chooser.error()
    return errors


def _create_context(
    chooser: CollectionChooser,
    *,
    title: str,
    collection_id: str,
    errors: catalog.FormErrors,
    just_created: str = "",
) -> dict[str, object]:
    """The create page's template context: its two fields and ``created``, the just-created
    Bestand's name for the success hinweis (empty on the plain create step)."""
    title_field, collection_field = article_rows(chooser, title, collection_id, errors)
    return {
        "title_field": title_field,
        "collection_field": collection_field,
        "created": just_created,
    }


# --- /articles/<ulid>/edit — the full edit form (Slice B) ---------------------


def article_edit(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /articles/<ulid>/edit`` — the full edit form. Archivist-only (non-archivist,
    malformed, or absent ulid → the plain 404, both methods). GET seeds the form from the
    stored Article; POST parses + saves under CAS. A ``Conflict`` re-renders state G with the
    just-submitted values preserved and a refreshed ``expected_version``."""
    gated = _load_gated(request, ulid)
    if gated is None:
        return not_found()
    archive, stored, archivist = gated
    chooser = CollectionChooser.of(archive)
    if request.method == "POST":
        return _handle_edit_post(request, archive, ulid, stored, chooser, archivist.username)
    # After Duplizieren the copy lands with the just-cleared Signatur focused (spec §5).
    focus = "ref_code" if landing.focus_ref_code(request) else ""
    surface = EditSurface.of(stored.article, stored.version, chooser)
    return surface.render(request, autofocus=focus or surface.first_empty_field())


def _handle_edit_post(
    request: HttpRequest,
    archive: Archive,
    ulid: Ulid,
    stored: Stored,
    chooser: CollectionChooser,
    changed_by: str,
) -> HttpResponseBase:
    """Parse + save the edit POST: state F on a validation error (first errored field autofocused),
    302 on success, state G on ``Conflict`` with the submitted values preserved. A ``custom_remove``
    or ``custom_add`` submit removes or adds a custom row — a re-render, no save (spec §5).

    SAVING IS PART OF PUBLISHING (owner decision 2026-08-08; a1 round 4): the margin's Status select
    rides the form, so the ONE CAS save commits the metadata and the Status together — Speichern
    applies it, Enter included. An unchanged Status is a plain save; a value that is no Status is a
    404 with no mutation; draft → published is REFUSED when the exposure cannot be computed (the
    branch below)."""
    current = stored.article
    surface = EditSurface.of(current, stored.version, chooser)
    adding = "custom_add" in request.POST
    if adding or "custom_remove" in request.POST:
        # spec §5: drop the named row or add an empty one, preserve everything else, save nothing.
        return surface.submitted(
            request.POST,
            catalog.parse_version(request.POST.get("expected_version", "")),
            drop_custom_row=None if adding else _named_custom_row(request.POST),
            add_custom_row=adding,
        ).render(request, autofocus="custom_key" if adding else "")
    status = request.POST.get("lifecycle")
    try:
        lifecycle = current.lifecycle if status is None else Lifecycle(status)
    except ValueError:
        return not_found()  # not a Status → no save, no transition, indistinguishable 404
    result = catalog.parse_edit_form(
        request.POST,
        ulid=ulid,
        chooser=chooser,
        current_media=current.media,
        current_audience=current.audience,
        lifecycle=lifecycle,
        added_at=current.added_at,
        deleted=current.deleted,
    )
    if (
        result.article is not None
        and current.lifecycle is Lifecycle.DRAFT
        and lifecycle is Lifecycle.PUBLISHED
        and chooser.chain_of(result.article.collection_id) is None
    ):
        # FAIL-CLOSED, server-side (learning G.43/G.48). The Status select drops Veröffentlicht when
        # the chain does not resolve, but that is the client half only, and the state is reachable with
        # ordinary UI actions — re-parenting a Bestand under a missing parent leaves the article's
        # own version untouched, so CAS passes. Published, the record 404s for everyone including its
        # cataloguer, and a later repair puts it live at whatever rung results unreviewed.
        # Refusing as a FIELD ERROR on the Bestand is what makes the whole re-render the existing
        # validation path: nothing written, every value preserved, the caret on the field that has to
        # change. Only the draft → published transition is gated: withdrawing, and saving a record
        # already published, need no exposure fact.
        result = replace(
            result,
            article=None,
            errors={**result.errors, "collection_id": _PUBLISH_UNRESOLVABLE},
        )
    if result.article is None:
        return surface.submitted(request.POST, result.expected_version).render(
            request, errors=result.errors, autofocus=first_error_field(result.errors)
        )
    outcome = catalog.save_catalog_form(
        archive, result.article, result.expected_version, changed_by=changed_by
    )
    match outcome:
        case catalog.SavedOutcome(result=save_result):
            # a lagging index (ADR 0014) is said on the page it lands on
            page = reverse("article-detail", args=[ulid])
            return redirect_to(request, landing.noting_lag(page, save_result.index_updated))
        case catalog.ConflictOutcome() as conflict:
            # The surface is the WINNER's: crumbs, media and the refreshed expected_version come from
            # the record as it now stands; the form keeps the archivist's own values.
            return (
                EditSurface.of(conflict.winner, conflict.current_version, chooser)
                .submitted(request.POST, conflict.current_version)
                .render(request, overlay=Conflict(conflict.submitted))
            )
        case catalog.DeletedOutcome():
            # hard-deleted underneath the save — collapse to the byte-identical 404
            return not_found()


def _named_custom_row(post: QueryDict) -> int:
    """The custom row the ``custom_remove`` submit names — a position in the RAW POST lists. A
    non-numeric value yields ``-1``, which drops nothing."""
    try:
        return int(post.get("custom_remove", ""))
    except ValueError:
        return -1


@dataclass(frozen=True, slots=True)
class _ConflictRow:
    """One field a CAS conflict touches (spec §6.1): its name, its German label, the id of its
    control (the notice links there) and the winner's stored value as the diff spells it."""

    name: str
    label: str
    target: str
    stored: str


# --- THE EDIT SURFACE --------------------------------------------------------------
#
# ONE value object per request and ONE render of workbench/article_edit.html: the template's
# whole context is built in one expression below, and every panel that can sit over the form is a
# member of the Overlay union (debt #3).


@dataclass(frozen=True, slots=True)
class NoOverlay:
    """The plain edit form: no panel over the surface."""


@dataclass(frozen=True, slots=True)
class Conflict:
    """State G (spec §6.1): a concurrent save won while the archivist was typing. The WINNER is the
    surface's own stored Article — a surface is always built from the saved record — so only the
    submitted one rides here, and the diff cannot compare against the wrong pair."""

    submitted: Article


@dataclass(frozen=True, slots=True)
class MediaError:
    """A structural media change the register refuses (oversize upload, a lost race): one German line
    above the register. Not a field error — nothing the archivist typed is wrong."""

    message: str


@dataclass(frozen=True, slots=True)
class DrawerIndexLag:
    """State H (ADR 0014) for a media action: the canonical write stood, the synchronous index update
    did not, and it is said in the Medien drawer, the only part that swap replaces. Every other write
    redirects and the landing page says it (``landing.noting_lag``)."""


@dataclass(frozen=True, slots=True)
class RemoveConfirm:
    """Step 1 of the two-step no-JS media removal (spec §6.3): this row asks before dropping."""

    content_hash: str


#: What may sit over the edit surface — CLOSED, so the template's panels are enumerable from here.
type Overlay = NoOverlay | Conflict | MediaError | DrawerIndexLag | RemoveConfirm

_NO_OVERLAY = NoOverlay()


@dataclass(frozen=True, slots=True)
class EditSurface:
    """The archivist's edit surface for ONE article: the record as SAVED, plus whatever the form
    currently shows.

    ``stored`` is always the article as it stands on disk — the GET seed, the article the POST was
    parsed against, the winner of a lost CAS race, or the one a save just wrote. The crumbs and the
    publish affordance read it, so neither describes a record that does not exist yet.

    ``values``/``media`` are what the FORM shows, which is the stored record on a GET and the
    archivist's own input on every re-render. ``version`` is what the hidden ``expected_version``
    carries, and it is the SUBMISSION's on a re-render (a stale form must keep losing) — refreshed
    only where a ``Conflict`` re-seeds the surface from the winner (spec §6.1)."""

    stored: Article
    version: Version
    chooser: CollectionChooser
    values: dict[str, object]
    media: tuple[MediaRef, ...]

    @classmethod
    def of(cls, stored: Article, version: Version, chooser: CollectionChooser) -> EditSurface:
        """The surface as saved: the form seeded from the stored Article, the register showing its
        media, the hidden version the one to save against."""
        return cls(
            stored=stored,
            version=version,
            chooser=chooser,
            values=_article_to_form_values(stored),
            media=stored.media,
        )

    def submitted(
        self,
        post: QueryDict,
        version: Version,
        *,
        drop_custom_row: int | None = None,
        add_custom_row: bool = False,
    ) -> EditSurface:
        """The same saved surface with the form re-seeded from ``post``: the just-typed values
        verbatim (the archivist never loses input) and the register carrying the captions that ride
        THIS submission, so a re-render shows no caption the next Speichern would not write.
        ``drop_custom_row`` / ``add_custom_row`` are the custom-row removal and add (spec §5)."""
        return replace(
            self,
            version=version,
            values=_post_to_form_values(
                post,
                self.stored,
                drop_custom_row=drop_custom_row,
                add_custom_row=add_custom_row,
            ),
            media=catalog.apply_captions(post, self.stored.media),
        )

    def first_empty_field(self) -> str:
        """The cataloguing spine's first empty field — the fresh-edit autofocus target (spec §5)."""
        return first_empty_field(self.values)

    def render(
        self,
        request: HttpRequest,
        *,
        errors: catalog.FormErrors | None = None,
        autofocus: str = "",
        overlay: Overlay = _NO_OVERLAY,
    ) -> HttpResponseBase:
        """THE render of the edit form. ``autofocus`` is the field to focus, ``""`` for none."""
        errors = errors or {}
        conflict_rows = (
            _conflict_rows(overlay.submitted, self.stored) if isinstance(overlay, Conflict) else []
        )
        inherited = _exposure_audience(replace(self.stored, audience=None), self.chooser)
        confirm = overlay.content_hash if isinstance(overlay, RemoveConfirm) else ""
        return render_screen(
            request,
            "workbench/article_edit.html",
            {
                "values": self.values,
                "version": self.version,
                "errors": errors,
                "autofocus": autofocus,
                "card_fields": card_fields(
                    self.values,
                    self.chooser,
                    errors=errors,
                    autofocus=autofocus,
                    conflicts={row.name: row.stored for row in conflict_rows},
                    audience_options=_audience_options(inherited),
                    lifecycle_options=(
                        LIFECYCLE_OPTIONS[1:]
                        if inherited is None and self.stored.lifecycle is Lifecycle.DRAFT
                        else LIFECYCLE_OPTIONS
                    ),
                ),
                "media_rows": _media_rows(self.stored.ulid, self.media, confirm),
                "delete_confirm": vocab.TRASH_CONFIRM,
                "crumbs": _crumbs(self.stored, self.chooser),
                "conflict": isinstance(overlay, Conflict),
                "conflict_rows": conflict_rows,
                "media_error": overlay.message if isinstance(overlay, MediaError) else "",
                "drawer_index_lag": vocab.INDEX_LAG if isinstance(overlay, DrawerIndexLag) else "",
            },
            chooser=self.chooser,
        )


def _crumbs(article: Article, chooser: CollectionChooser) -> tuple[CollectionCrumb, ...]:
    """The saved article's Bestand chain as crumbs, root first — the detail page's own builder. A
    chain the domain cannot resolve yields none: the crumbs show a place, and there is none."""
    chain = chooser.chain_of(article.collection_id)
    return () if chain is None else collection_crumbs(chain)


@dataclass(frozen=True, slots=True)
class _MediaRow:
    """One media register row (spec §6.3): the file's tile, its human byte size, the caption value,
    and the structural flags. ``is_cover`` marks the FIRST row; ``confirm_remove`` puts this row into
    the two-step remove confirm; ``is_first``/``is_last`` disable the reorder controls at the ends."""

    tile: MediaTile
    content_hash: str
    size: str
    caption: str
    is_cover: bool
    is_first: bool
    is_last: bool
    confirm_remove: bool


def _media_rows(ulid: str, media: tuple[MediaRef, ...], remove_hash: str) -> tuple[_MediaRow, ...]:
    """The media register view-models, cover-first (the tuple's order is meaning, ADR 0015)."""
    last = len(media) - 1
    return tuple(
        _MediaRow(
            tile=tile,
            content_hash=ref.content_hash,
            size=vocab.human_size(ref.byte_size),
            caption=ref.caption or "",
            is_cover=i == 0,
            is_first=i == 0,
            is_last=i == last,
            confirm_remove=ref.content_hash == remove_hash,
        )
        for i, (ref, tile) in enumerate(zip(media, media_tiles(ulid, media), strict=True))
    )


def _article_to_form_values(article: Article) -> dict[str, object]:
    """A stored Article → the flat form-value dict the template prints (GET seed). Every field's own
    ``seed`` renders it; ``custom_rows`` is the one shape no single field owns."""
    values: dict[str, object] = {"ulid": article.ulid}
    for registered in FIELDS:
        if registered.control:
            values[registered.name] = registered.value_of(article)
    values["custom_rows"] = list(article.custom)
    return values


def _post_to_form_values(
    post: QueryDict,
    stored: Article,
    *,
    drop_custom_row: int | None = None,
    add_custom_row: bool = False,
) -> dict[str, object]:
    """The raw POST → the flat form-value dict (state B/F/G re-render). Values are preserved verbatim
    so the archivist never loses input; blank custom pairs drop, and ``add_custom_row`` appends one.
    A Status or Sichtbarkeit the POST does not name shows ``stored``'s, as the save keeps it.

    ``drop_custom_row`` names a position in the RAW lists, so it is popped BEFORE the blank rows are
    filtered — popping after would shift positions and drop the wrong row whenever an earlier one was
    blanked in the browser. An out-of-range index drops nothing, never raises."""
    raw = list(zip(post.getlist("custom_key"), post.getlist("custom_value"), strict=False))
    if drop_custom_row is not None and 0 <= drop_custom_row < len(raw):
        raw.pop(drop_custom_row)
    values: dict[str, object] = {"ulid": stored.ulid}
    for registered in FIELDS:
        if registered.control:
            values[registered.name] = post.get(registered.name, "")
    if values["lifecycle"] not in LIFECYCLE_VALUES:
        # Veröffentlicht is the first option, so a value matching none would show a draft as published
        values["lifecycle"] = stored.lifecycle.value
    if catalog.audience_choice(post) is None:
        # "" would re-render as inherit, and the next Speichern would post it
        seeded = _article_to_form_values(stored)
        values["audience"], values["groups"] = seeded["audience"], seeded["groups"]
    rows = [pair for pair in raw if pair != ("", "")]
    values["custom_rows"] = [*rows, ("", "")] if add_custom_row else rows
    return values


# --- the CAS conflict diff (spec §6.1) ---------------------------------------------


def _conflict_rows(mine: Article, theirs: Article) -> list[_ConflictRow]:
    """The CAS diff (spec §6.1): one row per CHANGED field, submitted against the winner's stored
    Article — the registry's fields carrying a diff label, in the form's own order, each spelled by
    the field's own renderer."""
    return [
        _ConflictRow(
            name=registered.name,
            label=registered.diff,
            target=registered.control_id,
            stored=registered.diff_of(theirs),
        )
        for registered in FIELDS
        if registered.diff and registered.diff_of(mine) != registered.diff_of(theirs)
    ]


# --- /articles/<ulid>/publish — publish from the article page (a3 round 7) ---


class _PublishRefused(Exception):
    """The record handed to the publish transform is not the draft the archivist confirmed, or its
    Bestand chain does not resolve: nothing is written."""


def article_publish(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /articles/<ulid>/publish`` — the article page's confirmation publishes the
    draft. Archivist-only, POST-only, else the plain 404. CAS on the page's ``expected_version``;
    the gate is the edit form's (no resolvable chain, no publishing), checked against the record
    actually written. A refusal writes nothing and returns to the page as it now stands."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return not_found()
    archive, stored, archivist = gated
    page = reverse("article-detail", args=[ulid])
    if stored.version != catalog.parse_version(request.POST.get("expected_version", "")):
        return redirect_to(request, page)
    chooser = CollectionChooser.of(archive)

    def publish(article: Article) -> Article:
        if (
            article != stored.article
            or article.lifecycle is not Lifecycle.DRAFT
            or chooser.chain_of(article.collection_id) is None
        ):
            raise _PublishRefused
        return replace(article, lifecycle=Lifecycle.PUBLISHED)

    try:
        outcome = article_services.update_article(
            archive, ulid, publish, changed_by=archivist.username, retries=0
        )
    except _PublishRefused:
        return redirect_to(request, page)
    match outcome:
        case Missing():
            return not_found()
        case Conflicted():
            return redirect_to(request, page)
        case Updated(index_updated=index_updated):
            return redirect_to(request, landing.noting_lag(page, index_updated))


# --- /articles/<ulid>/copy — copy to a fresh draft (Slice C, spec §7) -----------


def article_copy(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /articles/<ulid>/copy`` — copy the article's metadata into a fresh DRAFT (Signatur
    cleared, no media) via the ``copy_article`` service, then 302 to the copy's edit form with the
    Signatur field autofocused (spec §5 — the one field that must change first on the volume path).
    Archivist-only; a non-archivist / malformed / absent ulid gets the plain 404. No confirm
    (it creates, never destroys). GET is not allowed (a copy is a mutation)."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return not_found()
    archive, _, archivist = gated
    copy = article_services.copy_article(archive, ulid, changed_by=archivist.username)
    return redirect_to(request, landing.noting_lag(landing.copy_url(copy.ulid), copy.index_updated))


# --- /articles/<ulid>/delete, /delete-permanently, /restore (ADR 0022) -------------


def article_delete(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /articles/<ulid>/delete`` — the delete confirm page (GET) and its execution
    (POST), which puts the Article in the Papierkorb (ADR 0022). Archivist-only; a non-archivist /
    malformed / absent / already marked ulid gets the plain 404, both methods."""
    return _confirmed_delete(
        request,
        ulid,
        marked=False,
        delete=lambda archive, stored, by: article_services.delete_article(
            archive, stored.article, stored.version, changed_by=by
        ),
    )


def article_delete_permanently(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /articles/<ulid>/delete-permanently`` — the same confirm for an Article in the
    Papierkorb, whose POST hard-deletes it (ADR 0020, 0022) and returns to the Papierkorb. Any
    other ulid gets the plain 404."""
    return _confirmed_delete(
        request,
        ulid,
        marked=True,
        delete=lambda archive, stored, _by: article_services.hard_delete_article(
            archive, stored.article.ulid, stored.version
        ),
    )


def _confirmed_delete(
    request: HttpRequest,
    ulid: str,
    *,
    marked: bool,
    delete: Callable[[Archive, Stored, str], SaveResult],
) -> HttpResponseBase:
    """The delete confirm both deletes share: GET names the record and what happens to it; POST
    deletes against the confirm's ``expected_version`` and 302s to the list the record left (the
    workbench, or the Papierkorb), or, when the index lagged behind a mark, to the record's page,
    which says so (ADR 0014). A confirm older than the record deletes nothing and asks again,
    naming the record as it now stands."""
    gated = _load_gated(request, ulid, marked=marked)
    if gated is None:
        return not_found()
    archive, stored, archivist = gated
    stale = ""
    if request.method == "POST":
        # The gate's load is what was checked, so it must be the version the CAS bets on.
        if stored.version == catalog.parse_version(request.POST.get("expected_version", "")):
            with contextlib.suppress(errors.Conflict):
                result = delete(archive, stored, archivist.username)
                if marked:
                    left = reverse("trash")
                elif result.index_updated:
                    left = reverse("workbench")
                else:  # the list still shows a mark the index has not caught up with
                    left = reverse("article-detail", args=[ulid])
                return redirect_to(request, landing.noting_lag(left, result.index_updated))
        reloaded = _load(archive, ulid, marked=marked)
        if reloaded is None:
            return not_found()
        stored = reloaded
        stale = _DELETE_STALE
    confirm = (
        vocab.delete_permanently_confirm(len(stored.article.media))
        if marked
        else vocab.TRASH_CONFIRM
    )
    chooser = CollectionChooser.of(archive)
    return render_screen(
        request,
        # htmx asked from a tool panel: the refusal answers in place (components/confirm.html)
        "components/confirm.html" if is_partial(request) else "workbench/article_delete.html",
        {
            "id": "delete-permanently" if marked else "delete",
            "ulid": ulid,
            "version": stored.version,
            "stale": stale,
            "title": stored.article.title,
            "ref_code": stored.article.ref_code or "",
            "crumbs": _crumbs(stored.article, chooser),
            "lead": confirm.question,
            "consequence": confirm.consequence,
            "button": confirm.button,
            "tone": "danger" if marked else "primary",
            "cancel_href": reverse("trash") if marked else reverse("article-detail", args=[ulid]),
            "in_place": True,
            "action": request.get_full_path(),
        },
        chooser=chooser,
    )


#: Why a delete asked again: the record was saved after its confirm was shown.
_DELETE_STALE = "Jemand hat diesen Artikel inzwischen gespeichert. Prüfe, was gelöscht wird, und bestätige erneut."


def article_restore(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /articles/<ulid>/restore`` — take an Article out of the Papierkorb (ADR 0022) against
    the page's ``expected_version``, then go to its page; a lagging index is said, as after a
    publish (ADR 0014). Archivist-only, POST-only, a marked Article only; else the plain 404. A
    stale version restores nothing and goes to its page too."""
    gated = _load_gated(request, ulid, marked=True)
    if gated is None or request.method != "POST":
        return not_found()
    archive, stored, archivist = gated
    page = reverse("article-detail", args=[ulid])
    if stored.version != catalog.parse_version(request.POST.get("expected_version", "")):
        return redirect_to(request, page)
    try:
        result = article_services.restore_article(
            archive, stored.article, stored.version, changed_by=archivist.username
        )
    except errors.Conflict:
        return redirect_to(request, page)  # a save landed since the gate's load: nothing restored
    return redirect_to(request, landing.noting_lag(page, result.index_updated))


# --- who would see it once published (G.34) ----------------------------------------


def _exposure_audience(article: Article, chooser: CollectionChooser) -> str | None:
    """Who would see ``article`` once published, in German, computed by the domain ``preview()``
    over the resolved collection chain so the who-sees decision stays in the domain. ``None`` when
    the chain cannot resolve (fail-closed: no statement rather than a misleading one)."""
    chain = chooser.chain_of(article.collection_id)
    return None if chain is None else vocab.exposure_label(preview(article, chain))


def _audience_options(inherited: str | None) -> tuple[tuple[str, str], ...]:
    """The Sichtbarkeit options with the inherit caption naming the rung it inherits, so the form
    always says who will see the record (owner ruling 5; a1 round 3). ``inherited`` is the
    audience with the article's own setting cleared; unresolvable, the plain caption stays."""
    if inherited is None:
        return vocab.AUDIENCE_OPTIONS
    return (("", f"{inherited} (wie Bestand)"), *vocab.AUDIENCE_OPTIONS[1:])


# --- media manager: structural POSTs (spec §6.3 + ADR 0015) -----------------------
#
# Reorder / remove / upload are SEPARATE structural POSTs, distinct from the caption metadata save.
# "Non-CAS" in that they never save against the form's expected_version (they only hand it back,
# _media_surface): they hand an idempotent transform of the media tuple to ``update_article``, which
# loads, applies and retries onto a concurrent winner. Order is meaning (first = cover), so reorder is re-cover and upload appends at the END.

#: How many times a structural media save re-loads after a concurrent version bump before giving up
#: and telling the archivist to try again (rare: single-app-process, a handful of writers).
_STRUCTURAL_SAVE_RETRIES = 2

#: The German hinweis shown when a structural media change lost every race (see _structural_change).
_MEDIA_CONFLICT = "Konnte nicht gespeichert werden — bitte erneut versuchen."

#: The refusal of an upload whose name cleans to nothing (ADR 0019 "Media names").
_FILENAME_EMPTY = "Dateiname besteht nur aus Punkten oder Leerzeichen. Bitte die Datei umbenennen."


def article_media_move(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /articles/<ulid>/media/move`` — reorder one media entry up/down (``direction`` =
    ``up``/``down``, ``hash`` = the entry). Order defines the cover, so reorder = re-cover (spec
    §6.3). Archivist-only, POST-only → plain 404 otherwise. Structural, non-CAS: re-render
    the edit form afterwards. A bad hash / edge move is a no-op (never raises)."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return not_found()
    archive, _, archivist = gated
    content_hash = request.POST.get("hash", "")
    direction = request.POST.get("direction", "")
    return _structural_change(
        request,
        archive,
        ulid,
        lambda media: _reordered(media, content_hash, direction),
        changed_by=archivist.username,
    )


def article_media_remove(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /articles/<ulid>/media/remove`` — the two-step no-JS remove (spec §6.3). First POST
    (``remove``=hash) re-renders the edit form with that row in the "Wirklich entfernen? [Ja]
    [Nein]" confirm state — NO removal yet. The [Ja] POST (``confirmed``=1) actually drops the ref
    (the blob is write-once and stays, recoverable). Archivist-only, POST-only → 404 otherwise."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return not_found()
    archive, stored, archivist = gated
    content_hash = request.POST.get("remove", "")
    if request.POST.get("confirmed") == "1":
        return _structural_change(
            request,
            archive,
            ulid,
            lambda media: _without(media, content_hash),
            changed_by=archivist.username,
        )
    # step 1: show the inline confirm for this row (no mutation yet — the gated Stored is still
    # current, so no re-load here either)
    return _media_surface(
        request, stored.article, stored.version, CollectionChooser.of(archive)
    ).render(request, overlay=RemoveConfirm(content_hash))


def article_media_upload(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /articles/<ulid>/media/upload`` — attach one or more files (multipart ``files``).
    Each file is stored under its own name (write-once, ADR 0019) and its ref appended at the END
    (never displacing the cover, ADR 0015). Archivist-only, POST-only → 404 otherwise. An oversize
    file or one whose name cleans to nothing → a clean German error, not a 500, and no file of the
    batch is stored. The file MUST persist before the README references it (repository.save raises
    otherwise) — ``add_media`` writes the file, then the structural save commits the refs."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return not_found()
    archive, stored, archivist = gated
    files = request.FILES.getlist("files")
    ceiling = settings.BUNDESARCHIV_MAX_UPLOAD_BYTES
    oversize = any(f.size is not None and f.size > ceiling for f in files)
    unnamed = any(cleaned_name(f.name or "") is None for f in files)
    if oversize or unnamed:
        message = (
            "Datei zu groß. Bitte kleinere Dateien hochladen." if oversize else _FILENAME_EMPTY
        )
        return _media_surface(
            request, stored.article, stored.version, CollectionChooser.of(archive)
        ).render(request, overlay=MediaError(message))
    repo = archive.articles
    new_refs = [
        repo.add_media(ulid, f.name or "", cast(BinaryIO, f), f.content_type or None) for f in files
    ]  # add_media persists each file (write-once) BEFORE any ref is committed
    if new_refs:
        return _structural_change(
            request,
            archive,
            ulid,
            lambda media: (*media, *new_refs),
            changed_by=archivist.username,
        )
    # no files posted — plain re-render of the gated Stored
    return _media_surface(
        request, stored.article, stored.version, CollectionChooser.of(archive)
    ).render(request)


def upload_gate(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /upload-gate/<ulid>`` — nginx's ``auth_request`` for the upload route
    (``deploy/nginx/nginx.conf``): 204 exactly when ``article_media_upload`` would take the
    files from a same-origin page, so nginx refuses everyone else before it reads the body (ADR
    0017). Same-origin is ``Sec-Fetch-Site``, else ``Origin``, else the ``Referer``: the order
    Django's CSRF check falls back in. Otherwise the plain 404."""
    if request.method != "GET" or _load_gated(request, ulid) is None:
        return not_found()
    site = request.headers.get("Sec-Fetch-Site")
    if site is None:
        origin = request.headers.get("Origin")
        if origin is None:
            referer = urlsplit(request.headers.get("Referer", ""))
            origin = f"{referer.scheme}://{referer.netloc}"
        same_origin = origin == f"{request.scheme}://{request.get_host()}"
    else:
        same_origin = site == "same-origin"
    return HttpResponse(status=204) if same_origin else not_found()


def _structural_change(
    request: HttpRequest,
    archive: Archive,
    ulid: Ulid,
    transform: Callable[[tuple[MediaRef, ...]], tuple[MediaRef, ...]],
    *,
    changed_by: str,
) -> HttpResponseBase:
    """Apply an idempotent structural transform to the article's media tuple through the retrying
    write service and render the outcome — everything the three structural routes share once each
    has parsed its own parameter. Non-CAS from the form's view: it saves at the version it just
    loaded rather than the form's expected_version (spec §6.3), which is what makes retrying safe.

    Hard-deleted underneath → the plain 404 (not a hinweis-worthy conflict); every attempt lost the
    race → the edit form with the konflikt hinweis, over a FRESH load (the winners changed what the
    register holds); committed → the edit form fed the post-save state, no re-load."""
    outcome = article_services.update_article(
        archive,
        ulid,
        lambda article: replace(article, media=transform(article.media)),
        changed_by=changed_by,
        retries=_STRUCTURAL_SAVE_RETRIES,
    )
    chooser = CollectionChooser.of(archive)
    match outcome:
        case Missing():
            return not_found()
        case Conflicted():
            try:
                stored = archive.articles.load(ulid)
            except ArchiveError:
                return not_found()  # hard-deleted between the lost race and this re-load
            return _media_surface(request, stored.article, stored.version, chooser).render(
                request, overlay=MediaError(_MEDIA_CONFLICT)
            )
        case Updated(article=article, version=version, index_updated=index_updated):
            return _media_surface(request, article, version, chooser, own_save=True).render(
                request, overlay=_NO_OVERLAY if index_updated else DrawerIndexLag()
            )


def _media_surface(
    request: HttpRequest,
    article: Article,
    version: Version,
    chooser: CollectionChooser,
    *,
    own_save: bool = False,
) -> EditSurface:
    """The edit surface a media route renders, and the expected_version it hands back. Without JS
    the media forms post none and the whole form re-renders from ``article``, so ``version`` is the
    honest one. With JS only the drawer and the version swap (the form keeps the archivist's
    values), so the posted version advances only past this route's ``own_save`` of exactly it —
    never past another editor's save (ADR 0013; a save is ``version + 1``). The drawer's rows show
    the unsaved captions the JS forms post along, matched by file; the route saves none of them."""
    raw = request.POST.get("expected_version")
    held = None if raw is None else catalog.parse_version(raw)
    shown = version if held is None or (own_save and version == held + 1) else held
    surface = EditSurface.of(article, shown, chooser)
    return replace(surface, media=catalog.apply_captions(request.POST, article.media))


def _reordered(
    media: tuple[MediaRef, ...], content_hash: str, direction: str
) -> tuple[MediaRef, ...]:
    """Move the entry named by ``content_hash`` one step ``up`` (earlier) or ``down`` (later). A
    missing hash, an unknown direction, or a move past an edge is a no-op (returns the tuple as-is)."""
    index = next((i for i, r in enumerate(media) if r.content_hash == content_hash), None)
    if index is None:
        return media
    target = index - 1 if direction == "up" else index + 1 if direction == "down" else index
    if not (0 <= target < len(media)) or target == index:
        return media
    items = list(media)
    items[index], items[target] = items[target], items[index]
    return tuple(items)


def _without(media: tuple[MediaRef, ...], content_hash: str) -> tuple[MediaRef, ...]:
    """The media tuple without the entry named by ``content_hash`` (the blob stays on disk, write-once
    recoverable). A missing hash is a no-op."""
    return tuple(r for r in media if r.content_hash != content_hash)


# --- HTMX enhancement partial (Slice E, spec §5) -----------------------------------
# An archivist-gated GET transform the edit form's HTMX layer swaps in. Its no-JS baseline already
# ships (the grouped optgroup select), so it ONLY removes a round-trip. A pure transform, no mutation.
# Gated via _load_gated -> 404 for anyone else and NEVER partial content (the 4.10 leak suite).


def article_document_types(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /articles/<ulid>/document-types?media_type=`` — the Dokumenttyp option list for one
    Medienart (spec §5). Archivist-only, GET-only. The no-JS baseline renders all types grouped by
    Medienart; this returns just the chosen Medienart's options for an HTMX inner-swap."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "GET":
        return not_found()
    media_type = request.GET.get("media_type", "")
    return render_screen(
        request,
        "workbench/_document_type_options.html",
        {"document_types": vocab.document_types_for(media_type)},
    )


def tag_suggestions(request: HttpRequest) -> HttpResponseBase:
    """``GET /tags/suggestions?q=&tags=`` — the Schlagworte the archive already uses that match
    ``q``, the line being typed, leaving out those in ``tags``, the whole field: the option list
    the edit form's Schlagworte field offers. Archivist-only, GET-only; else the plain 404."""
    viewer = viewer_of(request)
    if not isinstance(viewer, Archivist) or request.method != "GET":
        return not_found()
    on_field = frozenset(catalog.parse_lines(request.GET.get("tags", "")))
    return render_screen(
        request,
        "workbench/_tag_suggestions.html",
        {"suggestions": suggest_tags(viewer, request.GET.get("q", ""), exclude=on_field)},
    )
