"""The cataloging-form views (Part 4.7 Slice A+B): create step + full edit form (no-JS baseline).

Two production routes, both archivist-gated to the media route's byte-identical 404 for anyone else
(existence-hiding — the cataloging surface must not be discoverable). Thin by design: the
leak-sensitive parsing + validation live in ``catalog`` (pure, unit-tested), the write services in
``app.articles``, and the ONE ADR-0013 ``Conflict`` catch site in ``catalog.save_catalog_form``.
These views only resolve the viewer, gate, and hand an ``EditSurface`` — the record as SAVED plus
whatever the form shows — the overlay its outcome calls for.

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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import BinaryIO, cast
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, QueryDict
from django.http.response import HttpResponseBase
from django.urls import reverse

from bundesarchiv.app import articles as article_services
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import Conflicted, Missing, Updated
from bundesarchiv.app.web import catalog, vocab
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.browse_views import BestandCrumb, bestand_crumbs
from bundesarchiv.app.web.media_views import _not_found, thumbnail_url
from bundesarchiv.app.web.viewers import render_screen, viewer_of
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
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.repository import Stored, cleaned_name

#: The refusal when Veröffentlichen arrives for a record whose Bestand chain the domain cannot
#: resolve, said as a field error on the Bestand.
_EINBLICK_UNRESOLVABLE = "Der Bestand lässt sich nicht auflösen — Veröffentlichen ist gesperrt."


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


def _load_gated(request: HttpRequest, ulid: str) -> tuple[Archive, Stored, Archivist] | None:
    """The shared gate for every ulid-bearing cataloging route: archivist-only, validate the ulid
    in-view, and load the Article — returning ``(archive, stored, archivist)`` ONLY if all pass,
    else ``None`` (the caller maps ``None`` to the byte-identical 404). A non-archivist, a malformed
    ulid, and an absent/unreadable article all collapse to the SAME ``None`` (existence-hiding,
    spec §8)."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist) or not is_valid_ulid(ulid):
        return None
    archive = Archive.canonical()
    try:
        return archive, archive.articles.load(ulid), archivist
    except ArchiveError:
        return None


# --- /artikel/neu — the create step (Slice A) --------------------------------------


def article_create(request: HttpRequest) -> HttpResponseBase:
    """``GET/POST /artikel/neu`` — the minimal create step. Archivist-only (non-archivist → the
    byte-identical 404, both methods). POST creates a DRAFT with just Titel + Bestand and 302s to the
    edit form; a validation failure re-renders state B with the verbatim error + preserved values.

    On GET, a ``?bestand=<ulid>`` param pre-selects that Bestand (validated against the real set,
    ignored if bogus — no oracle) and a ``?angelegt=<name>`` param shows a success hinweis — the
    landing after creating a Bestand (4.8), so create-Bestand → catalog-an-article is one flow."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist):
        return _not_found()
    archive = Archive.canonical()
    bestand = BestandChooser.of(archive)
    if request.method == "POST":
        title = catalog.one_line(request.POST.get("title", ""))
        collection_id = request.POST.get("collection_id", "").strip()
        errors = _create_errors(title, collection_id, bestand)
        if not errors:
            ulid = catalog.new_draft(
                archive, title=title, collection_id=collection_id, changed_by=archivist.username
            )
            return HttpResponseRedirect(reverse("artikel-bearbeiten", args=[ulid]))
        return render_screen(
            request,
            "workbench/artikel_neu.html",
            _create_context(bestand, title=title, collection_id=collection_id, errors=errors),
        )
    # GET: pre-select the ?bestand only if it is a real collection (else ignore — no oracle); show a
    # "Bestand … angelegt." status line when ?angelegt carries the just-created Bestand's name.
    preselect = request.GET.get("bestand", "").strip()
    if not bestand.accepts(preselect):
        preselect = ""
    return render_screen(
        request,
        "workbench/artikel_neu.html",
        _create_context(
            bestand,
            title="",
            collection_id=preselect,
            errors={},
            angelegt=request.GET.get("angelegt", ""),
        ),
    )


def _create_errors(title: str, collection_id: str, bestand: BestandChooser) -> catalog.FormErrors:
    """The two create-step validations (spec §2), verbatim strings — the same two rules the full
    parse layer applies, kept minimal here because the create step has only these two fields."""
    errors: catalog.FormErrors = {}
    if not title:
        errors["title"] = "Titel ist erforderlich."
    if not bestand.accepts(collection_id):
        errors["collection_id"] = bestand.error()
    return errors


def _create_context(
    bestand: BestandChooser,
    *,
    title: str,
    collection_id: str,
    errors: catalog.FormErrors,
    angelegt: str = "",
) -> dict[str, object]:
    """The create form's template context: preserved values, the Bestand options, field errors, and
    the server-computed autofocus target (Titel unless it already has a value). ``angelegt`` is the
    just-created Bestand's name for the success hinweis (empty on the plain create step)."""
    autofocus = "collection_id" if title and "title" not in errors else "title"
    lead = _card_fields(
        {"title": title}, bestand, errors=errors, autofocus=autofocus, only=("lead",)
    )
    return {
        "titel": lead["lead"][0],
        "collection_id": collection_id,
        "collection_options": bestand.options(),
        "errors": errors,
        "autofocus": autofocus,
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
    archive, stored, archivist = gated
    bestand = BestandChooser.of(archive)
    if request.method == "POST":
        return _handle_edit_post(request, archive, ulid, stored, bestand, archivist.username)
    # After Duplizieren the copy lands with the just-cleared Signatur focused (spec §5).
    fokus = "ref_code" if request.GET.get("fokus") == "signatur" else ""
    surface = EditSurface.of(stored.article, stored.version, bestand)
    return surface.render(request, autofocus=fokus or surface.first_empty_field())


def _handle_edit_post(
    request: HttpRequest,
    archive: Archive,
    ulid: Ulid,
    stored: Stored,
    bestand: BestandChooser,
    changed_by: str,
) -> HttpResponseBase:
    """Parse + save the edit POST: state F on a validation error (first errored field autofocused),
    302 on success, state G on ``Conflict`` with the submitted values preserved. A ``custom_entfernen``
    or ``custom_neu`` submit removes or adds a custom row — a re-render, no save (spec §5).

    SAVING IS PART OF PUBLISHING (owner decision 2026-08-08; a1 round 4): the margin's Status select
    rides the form, so the ONE CAS save commits the metadata and the Status together — Speichern
    applies it, Enter included. An unchanged Status is a plain save; a value that is no Status is a
    404 with no mutation; draft → published is REFUSED when the exposure cannot be computed (the
    branch below)."""
    current = stored.article
    surface = EditSurface.of(current, stored.version, bestand)
    adding = "custom_neu" in request.POST
    if adding or "custom_entfernen" in request.POST:
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
        return _not_found()  # not a Status → no save, no transition, indistinguishable 404
    result = catalog.parse_edit_form(
        request.POST,
        ulid=ulid,
        bestand=bestand,
        current_media=current.media,
        lifecycle=lifecycle,
        added_at=current.added_at,
    )
    if (
        result.article is not None
        and current.lifecycle is Lifecycle.DRAFT
        and lifecycle is Lifecycle.PUBLISHED
        and bestand.chain_of(result.article.collection_id) is None
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
            errors={**result.errors, "collection_id": _EINBLICK_UNRESOLVABLE},
        )
    if result.article is None:
        return surface.submitted(request.POST, result.expected_version).render(
            request, errors=result.errors, autofocus=_first_error_field(result.errors)
        )
    outcome = catalog.save_catalog_form(
        archive, result.article, result.expected_version, changed_by=changed_by
    )
    match outcome:
        case catalog.SavedOutcome(result=save_result):
            # State H (ADR 0014): the canonical write stood but the sync index update failed and a
            # retry job was enqueued — re-render (not 302) with the quiet index-lag hinweis so the
            # archivist knows the visibility change is not yet effective in search. Otherwise 302.
            if not save_result.index_updated:
                saved = EditSurface.of(result.article, save_result.version, bestand)
                return saved.render(request, overlay=IndexLag())
            return _redirect(request, reverse("artikel-detail", args=[ulid]))
        case catalog.ConflictOutcome() as conflict:
            # The surface is the WINNER's: crumbs, media and the refreshed expected_version come from
            # the record as it now stands; the form keeps the archivist's own values.
            return (
                EditSurface.of(conflict.winner, conflict.current_version, bestand)
                .submitted(request.POST, conflict.current_version)
                .render(request, overlay=Conflict(conflict.submitted))
            )
        case catalog.DeletedOutcome():
            # hard-deleted underneath the save — collapse to the byte-identical 404
            return _not_found()


def _named_custom_row(post: QueryDict) -> int:
    """The custom row the ``custom_entfernen`` submit names — a position in the RAW POST lists. A
    non-numeric value yields ``-1``, which drops nothing."""
    try:
        return int(post.get("custom_entfernen", ""))
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
# ONE value object per request and ONE render of workbench/artikel_bearbeiten.html: the template's
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
class IndexLag:
    """State H (ADR 0014): the canonical write stood, the synchronous index update did not."""


@dataclass(frozen=True, slots=True)
class RemoveConfirm:
    """Step 1 of the two-step no-JS media removal (spec §6.3): this row asks before dropping."""

    content_hash: str


#: What may sit over the edit surface — CLOSED, so the template's panels are enumerable from here.
type Overlay = NoOverlay | Conflict | MediaError | IndexLag | RemoveConfirm

_NO_OVERLAY = NoOverlay()

#: The state-H hinweis (ADR 0014), shown when a save's index update lagged.
_INDEX_LAG_HINWEIS = "Gespeichert. Die Suche zeigt die Änderung in Kürze."


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
    bestand: BestandChooser
    values: dict[str, object]
    media: tuple[MediaRef, ...]

    @classmethod
    def of(cls, stored: Article, version: Version, bestand: BestandChooser) -> EditSurface:
        """The surface as saved: the form seeded from the stored Article, the register showing its
        media, the hidden version the one to save against."""
        return cls(
            stored=stored,
            version=version,
            bestand=bestand,
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
                self.stored.ulid,
                self.stored.lifecycle,
                drop_custom_row=drop_custom_row,
                add_custom_row=add_custom_row,
            ),
            media=catalog.apply_captions(post, self.stored.media),
        )

    def first_empty_field(self) -> str:
        """The cataloguing spine's first empty field — the fresh-edit autofocus target (spec §5)."""
        return _first_empty_field(self.values)

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
        inherited = _exposure_audience(replace(self.stored, audience=None), self.bestand)
        confirm = overlay.content_hash if isinstance(overlay, RemoveConfirm) else ""
        return render_screen(
            request,
            "workbench/artikel_bearbeiten.html",
            {
                "values": self.values,
                "version": self.version,
                "errors": errors,
                "autofocus": autofocus,
                "card_fields": _card_fields(
                    self.values,
                    self.bestand,
                    errors=errors,
                    autofocus=autofocus,
                    conflicts={row.name: row.stored for row in conflict_rows},
                    sichtbarkeit_options=_sichtbarkeit_options(inherited),
                    lifecycle_options=(
                        _LIFECYCLE_OPTIONS[1:]
                        if inherited is None and self.stored.lifecycle is Lifecycle.DRAFT
                        else _LIFECYCLE_OPTIONS
                    ),
                ),
                "media_rows": _media_rows(self.stored.ulid, self.media, confirm),
                "loeschen": vocab.delete_confirm(len(self.stored.media), discard=False),
                "verwerfen": vocab.delete_confirm(len(self.stored.media), discard=True),
                "crumbs": _crumbs(self.stored, self.bestand),
                "conflict": isinstance(overlay, Conflict),
                "conflict_rows": conflict_rows,
                "medien_fehler": overlay.message if isinstance(overlay, MediaError) else "",
                "index_lag": _INDEX_LAG_HINWEIS if isinstance(overlay, IndexLag) else "",
            },
        )


def _crumbs(article: Article, bestand: BestandChooser) -> tuple[BestandCrumb, ...]:
    """The saved article's Bestand chain as crumbs, root first — the detail page's own builder. A
    chain the domain cannot resolve yields none: the crumbs show a place, and there is none."""
    chain = bestand.chain_of(article.collection_id)
    return () if chain is None else bestand_crumbs(chain)


@dataclass(frozen=True, slots=True)
class _MediaRow:
    """One media register row (spec §6.3): the thumb URL via the gated media-thumb route (which
    re-authorizes per request), the filename + human byte size, the caption value, and the structural
    flags. ``is_cover`` marks the FIRST row; ``confirm_remove`` puts this row into the two-step remove
    confirm; ``is_first``/``is_last`` disable the reorder controls at the ends."""

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
    thumb URL points at the gated route, which re-authorizes on its own — the edit form never
    bypasses media auth."""
    last = len(media) - 1
    return tuple(
        _MediaRow(
            filename=ref.filename,
            content_hash=ref.content_hash,
            thumb_url=thumbnail_url(ulid, ref.content_hash),
            size=vocab.human_size(ref.byte_size),
            caption=ref.caption or "",
            is_cover=i == 0,
            is_first=i == 0,
            is_last=i == last,
            confirm_remove=ref.content_hash == entfernen_hash,
        )
        for i, ref in enumerate(media)
    )


def _article_to_form_values(article: Article) -> dict[str, object]:
    """A stored Article → the flat form-value dict the template prints (GET seed). Every field's own
    ``seed`` renders it; ``custom_rows`` and ``is_draft`` are the two shapes no single field owns."""
    values: dict[str, object] = {"ulid": article.ulid}
    for registered in _FIELDS:
        if registered.control:
            values[registered.name] = registered.value_of(article)
    values["custom_rows"] = list(article.custom)
    values["is_draft"] = article.lifecycle is Lifecycle.DRAFT
    return values


def _post_to_form_values(
    post: QueryDict,
    ulid: Ulid,
    lifecycle: Lifecycle,
    *,
    drop_custom_row: int | None = None,
    add_custom_row: bool = False,
) -> dict[str, object]:
    """The raw POST → the flat form-value dict (state B/F/G re-render). Values are preserved verbatim
    so the archivist never loses input; blank custom pairs drop, and ``add_custom_row`` appends one.
    ``lifecycle`` is the article's actual current lifecycle (the caller holds it), never assumed.

    ``drop_custom_row`` names a position in the RAW lists, so it is popped BEFORE the blank rows are
    filtered — popping after would shift positions and drop the wrong row whenever an earlier one was
    blanked in the browser. An out-of-range index drops nothing, never raises."""
    raw = list(zip(post.getlist("custom_key"), post.getlist("custom_value"), strict=False))
    if drop_custom_row is not None and 0 <= drop_custom_row < len(raw):
        raw.pop(drop_custom_row)
    values: dict[str, object] = {"ulid": ulid}
    for registered in _FIELDS:
        if registered.control:
            values[registered.name] = post.get(registered.name, "")
    if values["lifecycle"] not in _LIFECYCLE_VALUES:
        # Veröffentlicht is the first option, so a value matching none would show a draft as published
        values["lifecycle"] = lifecycle.value
    rows = [pair for pair in raw if pair != ("", "")]
    values["custom_rows"] = [*rows, ("", "")] if add_custom_row else rows
    values["is_draft"] = lifecycle is Lifecycle.DRAFT
    return values


def _audience_label(article: Article) -> str:
    """The stored audience as a human-German label for the CAS diff (inherit / rung / groups) — the
    shared ``vocab`` formatter fed the article's own audience."""
    return vocab.sichtbarkeit_label(article.audience)


# --- THE FIELD REGISTRY ------------------------------------------------------------
#
# The form's fields, declared ONCE, in DOM/tab order: what each one is called, where it sits, how it
# renders, how it is seeded from an Article and how the CAS diff spells it. Every derivation below is
# a filter over it, and so is the form's own markup (`_card_fields` → `workbench/_feld.html`), so the
# template holds no second enumeration. The columns are guarded against the real render or the real
# behaviour — tests/app/web/test_catalog_edit.py, "the field registry's columns".


def _seed_tags(article: Article) -> str:
    return ", ".join(article.tags)


def _seed_date(article: Article) -> str:
    return vocab.datierung_mono(article.date)


def _seed_gruppen(article: Article) -> str:
    return ", ".join(article.audience.groups) if article.audience is not None else ""


def _lifecycle_label(article: Article) -> str:
    return "Entwurf" if article.lifecycle is Lifecycle.DRAFT else "Veröffentlicht"


def _seed_lifecycle(article: Article) -> str:
    return article.lifecycle.value


#: The Status select (a1 round 4): the POST value is the Lifecycle's own value.
_LIFECYCLE_OPTIONS: tuple[tuple[str, str], ...] = (
    (Lifecycle.PUBLISHED.value, "Veröffentlicht"),
    (Lifecycle.DRAFT.value, "Entwurf (nur Archivare)"),
)
_LIFECYCLE_VALUES = frozenset(value for value, _ in _LIFECYCLE_OPTIONS)


@dataclass(frozen=True, slots=True)
class _Field:
    """One row of the form's field registry.

    ``section`` is the part of the form that holds the field: ``lead`` (the heading field),
    ``margin`` (the record's margin), a body section, or ``""`` for the rows that are not on the form
    at all — a single string, so "a field lives in at most one section" is structural.

    ``control`` is what the form renders for it: ``text``, ``select`` (flat options), ``groups``
    (optgrouped options), ``textarea``, or ``""`` for a row that is no control. A row with a control
    carries a scalar form value — it is seeded, re-rendered from the POST and printed by that column
    alone.

    ``scanned`` marks the cataloguing spine the GET autofocus walks for its first EMPTY field (spec
    §5). Gruppen is deliberately NOT on it: it is empty on almost every record by design (it means
    something only at the GROUPS rung), so "first empty field" would park the caret there on every
    fully catalogued record.

    ``focusable`` marks every field with its own single-line input, i.e. every field that can CARRY
    ``autofocus`` — the spine plus Gruppen, since a validation re-render focuses whatever errored.
    ``body`` is excluded (a textarea is not an "empty field" in the field sense) and so are the custom
    bag's inputs (the escape hatch).

    ``span`` gives the field the whole row of its section's grid (long values).

    ``required`` marks a field the save refuses blank; ``archivist_only`` one no viewer outside the
    archivists ever sees. Both put a marker after the label (the minority is marked). ``help`` is the
    template of the popover the hint's ⓘ opens, or ``""`` for a hint without one.

    ``diff`` is the German label the CAS conflict notice names the field by, or ``""`` when a
    conflict never marks it.

    ``seed``/``shown`` are the two renderings of the field's value, reached through ``value_of`` and
    ``diff_of``; both default to the Article attribute of the same name, so only a field that does not
    simply print one — the joined tuples, the audience's two spellings, the lifecycle word — declares
    anything here.
    """

    name: str
    label: str = ""
    control: str = ""
    section: str = ""
    hint: str = ""
    options: str = ""
    blank: str = ""
    element_id: str = ""
    hx: tuple[tuple[str, str], ...] = ()
    hx_get: str = ""
    span: bool = False
    required: bool = False
    archivist_only: bool = False
    help: str = ""
    scanned: bool = False
    focusable: bool = False
    diff: str = ""
    seed: Callable[[Article], str] | None = None
    shown: Callable[[Article], str] | None = None

    def value_of(self, article: Article) -> str:
        """The field's form value for a stored Article: its own ``seed`` where it declares one, else
        the Article attribute of the same name — ``""`` when unset (spec §8)."""
        if self.seed is not None:
            return self.seed(article)
        return str(getattr(article, self.name) or "")

    @property
    def control_id(self) -> str:
        """The id of the field's control: ``element_id`` where it declares one."""
        return self.element_id or f"feld-{self.name}"

    def diff_of(self, article: Article) -> str:
        """The field's value as the CAS diff prints it — ``shown`` where the form's own spelling is
        the wrong one to put in front of a human, else the form value."""
        return self.shown(article) if self.shown is not None else self.value_of(article)


#: Every field of the form in DOM/tab order: the lead, the margin, then the body sections.
#: ``custom`` is the ``errors`` key for the bag as a whole (it maps to no single input, so it is
#: neither scanned nor focusable); ``custom_key``/``custom_value`` are its inputs, rendered by the
#: bag's own row loop.
_FIELDS: tuple[_Field, ...] = (
    _Field(
        "title",
        label="Titel",
        control="text",
        section="lead",
        required=True,
        scanned=True,
        focusable=True,
        diff="Titel",
    ),
    _Field(
        "lifecycle",
        label="Status",
        control="select",
        section="margin",
        options="lifecycle_options",
        diff="Status",
        seed=_seed_lifecycle,
        shown=_lifecycle_label,
    ),
    _Field(
        "sichtbarkeit",
        label="Sichtbar für",
        control="select",
        section="margin",
        options="sichtbarkeit_options",
        diff="Sichtbarkeit",
        seed=lambda article: vocab.sichtbarkeit_value(article.audience),
        shown=_audience_label,
    ),
    _Field(
        "gruppen",
        label="Gruppen",
        control="text",
        section="margin",
        hint="Mehrere durch Komma trennen",
        focusable=True,
        seed=_seed_gruppen,
    ),
    # Bestand has no diff row: a bulk/CAS diff of collection MOVES is its own surface, not this one.
    _Field(
        "collection_id",
        label="Bestand",
        control="select",
        section="kerndaten",
        required=True,
        options="collection_options",
        scanned=True,
        focusable=True,
    ),
    _Field(
        "ref_code",
        label="Signatur",
        control="text",
        section="kerndaten",
        scanned=True,
        focusable=True,
        diff="Signatur",
    ),
    _Field(
        "physical_location",
        label="Standort",
        control="text",
        section="kerndaten",
        span=True,
        archivist_only=True,
        scanned=True,
        focusable=True,
        diff="Standort",
    ),
    _Field(
        "body",
        label="Beschreibung",
        control="textarea",
        section="beschreibung",
        diff="Beschreibung",
    ),
    _Field(
        "media_type",
        label="Medienart",
        control="select",
        section="einordnung",
        required=True,
        options="media_type_options",
        # On change, swap in the dependent Dokumenttyp options. No-JS baseline unchanged: the full
        # grouped optgroup list + server pairing re-validation still stand.
        hx_get="artikel-dokumenttypen",
        hx=(
            ("hx-trigger", "change"),
            ("hx-target", "#dokumenttyp-select"),
            ("hx-swap", "innerHTML"),
        ),
        scanned=True,
        focusable=True,
        diff="Medienart",
    ),
    _Field(
        "document_type",
        label="Dokumenttyp",
        control="groups",
        section="einordnung",
        options="document_type_groups",
        blank="— kein Dokumenttyp —",
        element_id="dokumenttyp-select",
        scanned=True,
        focusable=True,
        diff="Dokumenttyp",
    ),
    _Field(
        "tags",
        label="Schlagworte",
        control="text",
        section="einordnung",
        hint="Mehrere durch Komma trennen",
        span=True,
        scanned=True,
        focusable=True,
        diff="Schlagworte",
        seed=_seed_tags,
    ),
    _Field(
        "creator",
        label="Autor",
        control="text",
        section="herkunft",
        scanned=True,
        focusable=True,
        diff="Autor",
    ),
    _Field(
        "subject_place",
        label="Ort",
        control="text",
        section="herkunft",
        scanned=True,
        focusable=True,
        diff="Ort",
    ),
    _Field(
        "date",
        label="Datierung",
        control="text",
        section="herkunft",
        hint="z. B. 1962, 1984/1995, 1970~",
        help="workbench/_hilfe_datierung.html",
        scanned=True,
        focusable=True,
        diff="Datierung",
        seed=_seed_date,
    ),
    _Field("custom", section="weitere"),
    _Field("custom_key", section="weitere"),
    _Field("custom_value", section="weitere"),
)


def _first_empty_field(values: dict[str, object]) -> str:
    """The first field of the cataloguing spine (DOM order) whose value is empty — the fresh-edit
    autofocus target (spec §5). Falls back to Titel when every field is filled."""
    for field in _FIELDS:
        if field.scanned and not str(values.get(field.name) or "").strip():
            return field.name
    return "title"


def _first_error_field(errors: catalog.FormErrors) -> str:
    """The first errored field in DOM order that can carry the focus — the validation-re-render
    autofocus target (spec §5). ``custom`` maps to no single input, so it focuses nothing (empty)."""
    for field in _FIELDS:
        if field.focusable and field.name in errors:
            return field.name
    return ""


#: What a card ``<select>`` renders: flat ``(value, caption)`` rows, or one ``(group, rows)`` pair per
#: ``<optgroup>``. Which one a field takes is its ``control`` (``select`` / ``groups``).
type _Options = tuple[tuple[str, str], ...] | tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


@dataclass(frozen=True, slots=True)
class _CardRow:
    """One field of the form, ready to render: the registry's declaration joined to THIS render's
    value, error, conflict and focus. ``workbench/_feld.html`` prints it and nothing else, so a field
    is on the form exactly when the registry says so. ``was`` is the winner's stored value when a
    CAS conflict touches the field, else ``None``."""

    name: str
    label: str
    control: str
    control_id: str
    value: str
    hint: str
    error: str
    was: str | None
    autofocus: bool
    options: _Options
    blank: str
    hx: tuple[tuple[str, str], ...]
    span: bool
    required: bool
    archivist_only: bool
    help: str


def _card_fields(
    values: Mapping[str, object],
    bestand: BestandChooser,
    *,
    errors: catalog.FormErrors,
    autofocus: str,
    conflicts: Mapping[str, str] | None = None,
    sichtbarkeit_options: _Options = vocab.SICHTBARKEIT_OPTIONS,
    lifecycle_options: _Options = _LIFECYCLE_OPTIONS,
    only: tuple[str, ...] | None = None,
) -> dict[str, tuple[_CardRow, ...]]:
    """The form's fields grouped by section, in DOM order — the ONE list the template loops over.
    ``only`` limits it to those sections (the create step renders the lead alone).

    Only ``focusable`` rows can carry the caret, so a target the registry does not mark focusable
    focuses nothing rather than nothing-visible."""
    option_lists: dict[str, _Options] = {
        "collection_options": bestand.options(),
        "media_type_options": vocab.media_type_options(),
        "document_type_groups": vocab.grouped_document_type_options(),
        "sichtbarkeit_options": sichtbarkeit_options,
        "lifecycle_options": lifecycle_options,
    }
    ulid = str(values.get("ulid") or "")
    conflicts = conflicts or {}
    sections: dict[str, list[_CardRow]] = {}
    for registered in _FIELDS:
        if not registered.control or (only is not None and registered.section not in only):
            continue
        value = str(values.get(registered.name) or "")
        hx = registered.hx
        if registered.hx_get:
            hx = (("hx-get", reverse(registered.hx_get, args=[ulid])), *hx)
        sections.setdefault(registered.section, []).append(
            _CardRow(
                name=registered.name,
                label=registered.label,
                control=registered.control,
                control_id=registered.control_id,
                value=value,
                hint=registered.hint,
                error=errors.get(registered.name, ""),
                was=conflicts.get(registered.name),
                autofocus=registered.focusable and registered.name == autofocus,
                options=option_lists.get(registered.options, ()),
                blank=registered.blank,
                hx=hx,
                span=registered.span,
                required=registered.required,
                archivist_only=registered.archivist_only,
                help=registered.help,
            )
        )
    return {name: tuple(rows) for name, rows in sections.items()}


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
        for registered in _FIELDS
        if registered.diff and registered.diff_of(mine) != registered.diff_of(theirs)
    ]


# --- /artikel/<ulid>/veroeffentlichen — publish from the article page (a3 round 7) ---


class _PublishRefused(Exception):
    """The record handed to the publish transform is not the draft the archivist confirmed, or its
    Bestand chain does not resolve: nothing is written."""


def article_publish(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/veroeffentlichen`` — the article page's confirmation publishes the
    draft. Archivist-only, POST-only, else the plain 404. CAS on the page's ``expected_version``;
    the gate is the edit form's (no resolvable chain, no publishing), checked against the record
    actually written. A refusal writes nothing and returns to the page as it now stands."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    archive, stored, archivist = gated
    page = reverse("artikel-detail", args=[ulid])
    if stored.version != catalog.parse_version(request.POST.get("expected_version", "")):
        return _redirect(request, page)
    bestand = BestandChooser.of(archive)

    def publish(article: Article) -> Article:
        if (
            article != stored.article
            or article.lifecycle is not Lifecycle.DRAFT
            or bestand.chain_of(article.collection_id) is None
        ):
            raise _PublishRefused
        return replace(article, lifecycle=Lifecycle.PUBLISHED)

    try:
        outcome = article_services.update_article(
            archive, ulid, publish, changed_by=archivist.username, retries=0
        )
    except _PublishRefused:
        return _redirect(request, page)
    match outcome:
        case Missing():
            return _not_found()
        case Conflicted():
            return _redirect(request, page)
        case Updated(article=article, version=version, index_updated=False):
            return EditSurface.of(article, version, bestand).render(request, overlay=IndexLag())
        case Updated():
            return _redirect(request, page)


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
    archive, _, archivist = gated
    copy = article_services.copy_article(archive, ulid, changed_by=archivist.username)
    return HttpResponseRedirect(f"{reverse('artikel-bearbeiten', args=[copy.ulid])}?fokus=signatur")


# --- /artikel/<ulid>/loeschen — delete confirm + execute (Slice C, spec §7) --------


def article_delete(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET/POST /artikel/<ulid>/loeschen`` — the delete confirm page (GET) and its execution
    (POST). Archivist-only; a non-archivist / malformed / absent ulid gets the plain 404, both
    methods. GET names the record and what goes with it; POST hard-deletes against the confirm's
    ``expected_version`` and 302s to the workbench. A confirm older than the record deletes nothing
    and asks again, naming the record as it now stands."""
    gated = _load_gated(request, ulid)
    if gated is None:
        return _not_found()
    archive, stored, _ = gated
    veraltet = ""
    if request.method == "POST":
        if stored.version == catalog.parse_version(request.POST.get("expected_version", "")):
            article_services.hard_delete_article(archive, ulid)
            return _redirect(request, "/")  # HTMX: HX-Redirect to the workbench (spec §5)
        veraltet = _LOESCHEN_VERALTET
    # Verwerfen (abandoning a draft from the edit form) reuses this identical confirm page + the same
    # hard-delete, only reworded (spec §7 — avoids a second destructive idiom). ?verwerfen=1 flags it,
    # but the "Entwurf verwerfen" wording is only honest for a DRAFT — a published article is deleted,
    # not discarded, so it always reads "Artikel löschen?" regardless of the query param.
    verwerfen = request.GET.get("verwerfen") == "1" and stored.article.lifecycle is Lifecycle.DRAFT
    return render_screen(
        request,
        # htmx asked from a tool panel: the refusal answers in place (workbench/_loeschen.html)
        "workbench/_loeschen.html"
        if request.headers.get("HX-Request")
        else "workbench/artikel_loeschen.html",
        {
            "id": "verwerfen" if verwerfen else "loeschen",
            "ulid": ulid,
            "version": stored.version,
            "veraltet": veraltet,
            "title": stored.article.title,
            "ref_code": stored.article.ref_code or "",
            "crumbs": _crumbs(stored.article, BestandChooser.of(archive)),
            "confirm": vocab.delete_confirm(len(stored.article.media), discard=verwerfen),
            "action": request.get_full_path(),
        },
    )


#: Why a delete asked again: the record was saved after its confirm was shown.
_LOESCHEN_VERALTET = "Jemand hat diesen Artikel inzwischen gespeichert. Prüfe, was gelöscht wird, und bestätige erneut."


# --- who would see it once published (G.34) ----------------------------------------


def _exposure_audience(article: Article, bestand: BestandChooser) -> str | None:
    """Who would see ``article`` once published, in German, computed by the domain ``preview()``
    over the resolved collection chain so the who-sees decision stays in the domain. ``None`` when
    the chain cannot resolve (fail-closed: no statement rather than a misleading one)."""
    chain = bestand.chain_of(article.collection_id)
    return None if chain is None else vocab.exposure_label(preview(article, chain))


def _sichtbarkeit_options(inherited: str | None) -> _Options:
    """The Sichtbarkeit options with the inherit caption naming the rung it inherits, so the form
    always says who will see the record (owner ruling 5; a1 round 3). ``inherited`` is the
    audience with the article's own setting cleared; unresolvable, the plain caption stays."""
    if inherited is None:
        return vocab.SICHTBARKEIT_OPTIONS
    return (("", f"{inherited} (wie Bestand)"), *vocab.SICHTBARKEIT_OPTIONS[1:])


# --- media manager: structural POSTs (spec §6.3 + ADR 0015) -----------------------
#
# Reorder / remove / upload are SEPARATE structural POSTs, distinct from the caption metadata save.
# "Non-CAS" in that they do not ride the form's expected_version: they hand an idempotent transform
# of the media tuple to ``update_article``, which loads, applies and retries onto a concurrent
# winner. Order is meaning (first = cover), so reorder is re-cover and upload appends at the END.

#: How many times a structural media save re-loads after a concurrent version bump before giving up
#: and telling the archivist to try again (rare: single-app-process, a handful of writers).
_STRUCTURAL_SAVE_RETRIES = 2

#: The German hinweis shown when a structural media change lost every race (see _structural_change).
_MEDIEN_KONFLIKT = "Konnte nicht gespeichert werden — bitte erneut versuchen."

#: The refusal of an upload whose name cleans to nothing (ADR 0019 "Media names").
_DATEINAME_LEER = "Dateiname besteht nur aus Punkten oder Leerzeichen. Bitte die Datei umbenennen."


def article_medien_verschieben(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/medien/verschieben`` — reorder one media entry up/down (``richtung`` =
    ``hoch``/``runter``, ``hash`` = the entry). Order defines the cover, so reorder = re-cover (spec
    §6.3). Archivist-only, POST-only → byte-identical 404 otherwise. Structural, non-CAS: re-render
    the edit form afterwards. A bad hash / edge move is a no-op (never raises)."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    archive, _, archivist = gated
    content_hash = request.POST.get("hash", "")
    richtung = request.POST.get("richtung", "")
    return _structural_change(
        request,
        archive,
        ulid,
        lambda media: _reordered(media, content_hash, richtung),
        changed_by=archivist.username,
    )


def article_medien_entfernen(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/medien/entfernen`` — the two-step no-JS remove (spec §6.3). First POST
    (``entfernen``=hash) re-renders the edit form with that row in the "Wirklich entfernen? [Ja]
    [Nein]" confirm state — NO removal yet. The [Ja] POST (``bestaetigt``=1) actually drops the ref
    (the blob is write-once and stays, recoverable). Archivist-only, POST-only → 404 otherwise."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    archive, stored, archivist = gated
    content_hash = request.POST.get("entfernen", "")
    if request.POST.get("bestaetigt") == "1":
        return _structural_change(
            request,
            archive,
            ulid,
            lambda media: _without(media, content_hash),
            changed_by=archivist.username,
        )
    # step 1: show the inline confirm for this row (no mutation yet — the gated Stored is still
    # current, so no re-load here either)
    return EditSurface.of(stored.article, stored.version, BestandChooser.of(archive)).render(
        request, overlay=RemoveConfirm(content_hash)
    )


def article_medien_hochladen(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``POST /artikel/<ulid>/medien/hochladen`` — attach one or more files (multipart ``dateien``).
    Each file is stored under its own name (write-once, ADR 0019) and its ref appended at the END
    (never displacing the cover, ADR 0015). Archivist-only, POST-only → 404 otherwise. An oversize
    file or one whose name cleans to nothing → a clean German error, not a 500, and no file of the
    batch is stored. The file MUST persist before the README references it (repository.save raises
    otherwise) — ``add_media`` writes the file, then the structural save commits the refs."""
    gated = _load_gated(request, ulid)
    if gated is None or request.method != "POST":
        return _not_found()
    archive, stored, archivist = gated
    files = request.FILES.getlist("dateien")
    ceiling = settings.BUNDESARCHIV_MAX_UPLOAD_BYTES
    oversize = any(f.size is not None and f.size > ceiling for f in files)
    unnamed = any(cleaned_name(f.name or "") is None for f in files)
    if oversize or unnamed:
        message = (
            "Datei zu groß. Bitte kleinere Dateien hochladen." if oversize else _DATEINAME_LEER
        )
        return EditSurface.of(stored.article, stored.version, BestandChooser.of(archive)).render(
            request, overlay=MediaError(message)
        )
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
    return EditSurface.of(stored.article, stored.version, BestandChooser.of(archive)).render(
        request
    )


def upload_gate(request: HttpRequest, ulid: str) -> HttpResponseBase:
    """``GET /upload-gate/<ulid>`` — nginx's ``auth_request`` for the upload route
    (``deploy/nginx/nginx.conf``): 204 exactly when ``article_medien_hochladen`` would take the
    files from a same-origin page, so nginx refuses everyone else before it reads the body (ADR
    0017). Same-origin is ``Sec-Fetch-Site``, else ``Origin``, else the ``Referer``: the order
    Django's CSRF check falls back in. Otherwise the plain 404."""
    if request.method != "GET" or _load_gated(request, ulid) is None:
        return _not_found()
    site = request.headers.get("Sec-Fetch-Site")
    if site is None:
        origin = request.headers.get("Origin")
        if origin is None:
            referer = urlsplit(request.headers.get("Referer", ""))
            origin = f"{referer.scheme}://{referer.netloc}"
        same_origin = origin == f"{request.scheme}://{request.get_host()}"
    else:
        same_origin = site == "same-origin"
    return HttpResponse(status=204) if same_origin else _not_found()


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
    bestand = BestandChooser.of(archive)
    match outcome:
        case Missing():
            return _not_found()
        case Conflicted():
            try:
                stored = archive.articles.load(ulid)
            except ArchiveError:
                return _not_found()  # hard-deleted between the lost race and this re-load
            return EditSurface.of(stored.article, stored.version, bestand).render(
                request, overlay=MediaError(_MEDIEN_KONFLIKT)
            )
        case Updated(article=article, version=version):
            return EditSurface.of(article, version, bestand).render(request)


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


# --- HTMX enhancement partial (Slice E, spec §5) -----------------------------------
# An archivist-gated GET transform the edit form's HTMX layer swaps in. Its no-JS baseline already
# ships (the grouped optgroup select), so it ONLY removes a round-trip. A pure transform, no mutation.
# Gated via _load_gated -> 404 for anyone else and NEVER partial content (the 4.10 leak suite).


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
    return render_screen(
        request,
        "workbench/_dokumenttyp_options.html",
        {"document_types": vocab.document_types_for(media_type)},
    )
