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
  the "Inzwischen geändert" panel (state G) with the just-submitted values preserved. Since the form
  wave the render also carries the READER'S SHEET — the reader's view of the stored record plus the
  exposure statement (owner rulings 1 + 5, 2026-08-08) — which is why there is no separate
  over-exposure preview route any more.

The ``<ulid>`` is validated in-view via ``is_valid_ulid`` (never a route converter), so a malformed
value collapses to the same 404 as an absent one. ``neu`` is registered before ``<str:ulid>`` in
``urls.py`` so the literal path wins.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import BinaryIO, cast

from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, QueryDict
from django.http.response import HttpResponseBase
from django.urls import reverse

from bundesarchiv.app import articles as article_services
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import Conflicted, Missing, Updated
from bundesarchiv.app.web import catalog, vocab
from bundesarchiv.app.web.bestand import BestandChooser
from bundesarchiv.app.web.browse_views import _body_paragraphs
from bundesarchiv.app.web.media_views import _not_found, thumbnail_url
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.access import VisibilityPreview, preview, project
from bundesarchiv.domain.collections import resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import (
    Article,
    AudienceTier,
    Lifecycle,
    MediaRef,
    Ulid,
    Version,
)
from bundesarchiv.domain.viewer import Archivist, Public
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.repository import Stored, cleaned_name

# The Sichtbarkeit select options: (value, caption). The empty value is the inherit default (ADR
# 0001); the rest map to the audience rungs. GROUPS is chosen together with the Gruppen field.
_SICHTBARKEIT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", vocab.SICHTBARKEIT_ERBEN),
    ("public", vocab.SICHTBARKEIT_PUBLIC),
    ("members", vocab.SICHTBARKEIT_MEMBERS),
    ("groups", vocab.SICHTBARKEIT_GRUPPEN),
)


#: The refusal when Veröffentlichen arrives for a record whose Bestand chain the domain cannot
#: resolve. Same fact as _einblick.html's absence branch, said as a field error on the Bestand.
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
        title = request.POST.get("title", "").strip()
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
    return {
        "title": title,
        "collection_id": collection_id,
        "collection_options": bestand.options(),
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
    archive, stored, archivist = gated
    bestand = BestandChooser.of(archive)
    if request.method == "POST":
        return _handle_edit_post(request, archive, ulid, stored, bestand, archivist.username)
    # After Kopieren the copy's edit form lands with the Signatur field focused (spec §5 — the one
    # field that must change first on the volume path, just cleared). ?fokus=signatur carries that.
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

    SAVING IS PART OF PUBLISHING (owner decision 2026-08-08): the edit form's own submit carries the
    lifecycle verb, so the ONE CAS save commits the metadata and the transition together. A separate
    lifecycle POST rebuilt the record from disk and discarded the archivist's unsaved edits silently.
    Everything downstream is unchanged by construction — publishing cannot behave differently from
    saving, because it IS saving. An unknown verb is a 404 with no mutation; ``veroeffentlichen`` is
    REFUSED when the exposure cannot be computed (the branch below)."""
    current = stored.article
    surface = EditSurface.of(current, stored.version, bestand)
    if "custom_entfernen" in request.POST or "custom_neu" in request.POST:
        # spec §5: drop the named row or add an empty one, preserve everything else, save nothing.
        adding = "custom_neu" in request.POST
        return surface.submitted(
            request.POST,
            catalog.parse_version(request.POST.get("expected_version", "")),
            drop_custom_row=None if adding else _named_custom_row(request.POST),
            add_custom_row=adding,
        ).render(request, autofocus="custom_key" if adding else "custom")
    verb = request.POST.get("lebenszyklus", "")
    lifecycle = _lifecycle_for(verb) if verb else current.lifecycle
    if lifecycle is None:
        return _not_found()  # unknown verb → no save, no transition, indistinguishable 404
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
        and verb == "veroeffentlichen"
        and _einblick_view_model(result.article, bestand) is None
    ):
        # The retired gate's FAIL-CLOSED branch, server-side (learning G.43/G.48). The record row hides
        # Veröffentlichen when the exposure view-model is None, but that is the client half only, and
        # the state is reachable with ordinary UI actions — re-parenting a Bestand under a missing
        # parent leaves the article's own version untouched, so CAS passes. Published, the record 404s
        # for everyone including its cataloguer, and a later repair puts it live at whatever rung
        # results with no archivist having read an exposure statement.
        # Refusing as a FIELD ERROR on the Bestand is what makes the whole re-render the existing
        # validation path: nothing written, every value preserved, the caret on the field that has to
        # change. Zurückziehen is deliberately not gated — that is why the verb, not the target
        # lifecycle, is the condition.
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
            # The surface is the WINNER's: the sheet, the media and the refreshed expected_version all
            # come from the record as it now stands, with the archivist's own values still in the card.
            return (
                EditSurface.of(conflict.winner, conflict.current_version, bestand)
                .submitted(request.POST, conflict.current_version)
                .render(request, autofocus="speichern", overlay=Conflict(conflict.submitted))
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
    """One row of the neutral CAS diff table (spec §6.1): the German field label + the archivist's
    submitted value + the winner's stored value. ``is_sig`` marks the Signatur row so the template
    renders both cells as ``.c-sig`` marks."""

    label: str
    mine: str
    theirs: str
    is_sig: bool


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
    submitted one rides here, and the neutral diff cannot compare against the wrong pair."""

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
    parsed against, the winner of a lost CAS race, or the one a save just wrote. That is what makes
    the reader's sheet honest: a box labelled „Leseansicht“ carries the exposure statement (owner
    ruling 5), so it may never show keystrokes describing a record that does not exist yet.

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
        """THE render of the edit form. ``autofocus`` is the field to focus, ``""`` for none; the
        folded sections holding an error or the focus open themselves from the same two arguments,
        so neither can end up inside a fold (G.33)."""
        errors = errors or {}
        rows = self.values.get("custom_rows")
        conflict = overlay if isinstance(overlay, Conflict) else None
        confirm = overlay.content_hash if isinstance(overlay, RemoveConfirm) else ""
        return render_screen(
            request,
            "workbench/artikel_bearbeiten.html",
            {
                "values": self.values,
                "version": self.version,
                "errors": errors,
                "autofocus": autofocus,
                # The card's rows, section by section — the template loops these, so the registry is
                # the ONE place a field of the record card exists.
                "card_fields": _card_fields(
                    self.values, self.bestand, errors=errors, autofocus=autofocus
                ),
                "media_rows": _media_rows(self.stored.ulid, self.media, confirm),
                # The folded sections' summary values (owner ruling 4: folding may never hide data).
                # Both read what the FIELDS print — the caption off the very option list the select
                # renders — so a summary cannot spell a fact differently from its field (law C7).
                "sichtbarkeit_caption": _sichtbarkeit_caption(
                    str(self.values.get("sichtbarkeit") or "")
                ),
                "custom_keys": [key for key, _ in rows if key] if isinstance(rows, list) else [],
                "open_sections": _open_sections(errors, autofocus),
                # The reader's sheet (ruling 1) and, through it, the exposure statement (ruling 5) —
                # ONE view-model for both of that statement's placements.
                "sheet": _sheet_view_model(self.stored, self.bestand),
                "conflict": conflict is not None,
                "conflict_rows": (
                    _conflict_rows(conflict.submitted, self.stored) if conflict else ()
                ),
                "medien_fehler": overlay.message if isinstance(overlay, MediaError) else "",
                "index_lag": _INDEX_LAG_HINWEIS if isinstance(overlay, IndexLag) else "",
            },
        )


def _sichtbarkeit_caption(value: str) -> str:
    """The German caption the Sichtbarkeit select shows for ``value`` — read from the SAME option
    list the template renders, so the folded Zugriff summary and the open select can never disagree.
    An unknown value (only reachable from a hand-crafted POST) falls back to the inherit caption, the
    same rung the parse layer applies to it."""
    captions = dict(_SICHTBARKEIT_OPTIONS)
    return captions.get(value, captions[""])


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
    rows = [pair for pair in raw if pair != ("", "")]
    values["custom_rows"] = [*rows, ("", "")] if add_custom_row else rows
    values["is_draft"] = lifecycle is Lifecycle.DRAFT
    return values


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


def _audience_label(article: Article) -> str:
    """The stored audience as a human-German label for the CAS diff (inherit / rung / groups) — the
    shared ``vocab`` formatter fed the article's own audience."""
    return vocab.sichtbarkeit_label(article.audience)


# --- THE FIELD REGISTRY ------------------------------------------------------------
#
# The record card's fields, declared ONCE, in DOM/tab order: what each one is called, where it sits,
# how it renders, how it is seeded from an Article and how the CAS diff spells it. Every derivation
# below is a filter over it, and so is the card's own markup (`_card_fields` → `workbench/_feld.html`),
# so the template holds no second enumeration. The columns are guarded against the real render or the
# real behaviour — tests/app/web/test_catalog_edit.py, the block after the fold walk.


def _seed_tags(article: Article) -> str:
    return ", ".join(article.tags)


def _seed_date(article: Article) -> str:
    return vocab.datierung_mono(article.date)


def _seed_gruppen(article: Article) -> str:
    return ", ".join(article.audience.groups) if article.audience is not None else ""


def _lifecycle_label(article: Article) -> str:
    return "Entwurf" if article.lifecycle is Lifecycle.DRAFT else "Veröffentlicht"


@dataclass(frozen=True, slots=True)
class _Field:
    """One row of the record card's field registry.

    ``section`` is the card section that holds the field, or ``""`` for the rows that are not on the
    card at all — a single string, not membership in one of several sets, which is what makes "a field
    lives in at most one section" structural instead of something a test has to rule out. The three
    in ``_FOLDED`` render as ``<details>``.

    ``control`` is what the card renders for it: ``text``, ``select`` (flat options), ``groups``
    (optgrouped options), ``textarea``, or ``""`` for a row that is no control. A row with a control
    carries a scalar form value — it is seeded, echoed and printed by that column alone.

    ``scanned`` marks the cataloguing spine the GET autofocus walks for its first EMPTY field (spec
    §5). Gruppen is deliberately NOT on it: it is empty on almost every record by design (it means
    something only at the GROUPS rung), so "first empty field" would park the caret there on every
    fully catalogued record and pop the Zugriff fold open with it.

    ``focusable`` marks every field with its own single-line input, i.e. every field that can CARRY
    ``autofocus`` — the spine plus Gruppen, since a validation re-render focuses whatever errored.
    ``body`` is excluded (a textarea is not an "empty field" in the field sense) and so are the custom
    bag's inputs (the escape hatch).

    ``fit`` is a text control's width class from its content's ceiling (learning G.31): ``kurz`` for
    a short domain value, ``signatur`` for the Signatur (which also takes the mono face), or ``""``
    to fill the value cell.

    ``required`` marks a field the save refuses blank; ``archivist_only`` one no viewer outside the
    archivists ever sees. Both put a marker after the label (the minority is marked). ``help`` is the
    template of the popover the hint's ⓘ opens, or ``""`` for a hint without one.

    ``diff`` is the German label the CAS conflict table prints for the field, or ``""`` when the field
    has no diff row.

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
    fit: str = ""
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

    def diff_of(self, article: Article) -> str:
        """The field's value as the CAS diff prints it — ``shown`` where the form's own spelling is
        the wrong one to put in front of a human, else the form value."""
        return self.shown(article) if self.shown is not None else self.value_of(article)


#: Every field of the record card in DOM/tab order. ``custom`` is the ``errors`` key for the bag as a
#: whole (it maps to no single input, so it is neither scanned nor focusable);
#: ``custom_key``/``custom_value`` are its inputs, rendered by the bag's own row loop. ``lifecycle`` is
#: not a field at all — it is the record's state, and it rides here only because the CAS diff shows it
#: as a row, last.
_FIELDS: tuple[_Field, ...] = (
    _Field(
        "title",
        label="Titel",
        control="text",
        section="kerndaten",
        required=True,
        scanned=True,
        focusable=True,
        diff="Titel",
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
        fit="signatur",
        scanned=True,
        focusable=True,
        diff="Signatur",
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
        scanned=True,
        focusable=True,
        diff="Schlagworte",
        seed=_seed_tags,
    ),
    _Field(
        "date",
        label="Datierung",
        control="text",
        section="einordnung",
        hint="z. B. 1962, 1984/1995, 1970~",
        help="workbench/_hilfe_datierung.html",
        fit="kurz",
        scanned=True,
        focusable=True,
        diff="Datierung",
        seed=_seed_date,
    ),
    _Field(
        "creator",
        label="Autor",
        control="text",
        section="herkunft",
        fit="kurz",
        scanned=True,
        focusable=True,
        diff="Autor",
    ),
    _Field(
        "subject_place",
        label="Ort",
        control="text",
        section="herkunft",
        fit="kurz",
        scanned=True,
        focusable=True,
        diff="Ort",
    ),
    _Field(
        "physical_location",
        label="Standort",
        control="text",
        section="herkunft",
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
        "sichtbarkeit",
        label="Sichtbarkeit",
        control="select",
        section="zugriff",
        options="sichtbarkeit_options",
        diff="Sichtbarkeit",
        seed=_sichtbarkeit_value,
        shown=_audience_label,
    ),
    _Field(
        "gruppen",
        label="Gruppen",
        control="text",
        section="zugriff",
        hint="Mehrere durch Komma trennen",
        focusable=True,
        seed=_seed_gruppen,
    ),
    _Field("custom", section="weitere"),
    _Field("custom_key", section="weitere"),
    _Field("custom_value", section="weitere"),
    _Field("lifecycle", diff="Status", shown=_lifecycle_label),
)

#: The card sections that render as a ``<details>``. Everything else on the card is always open.
_FOLDED: frozenset[str] = frozenset({"herkunft", "zugriff", "weitere"})


#: The folded card sections and the fields each HOLDS. Folding may hide neither DATA (owner ruling 4)
#: nor a MESSAGE nor the FOCUS: a validation error inside a folded section is invisible, and an
#: ``autofocus`` inside one focuses nothing at all (learning G.33). Both are decided from the SAME
#: error/autofocus context the fields render with — one rule over every fold, not a patch per
#: instance.
def _derive_section_fields() -> dict[str, frozenset[str]]:
    """Group the registry's fields by their folded section, in first-appearance order.

    A function, not a module-level comprehension: on the pinned CPython (3.14.0rc2) writing this as
    ``{s: frozenset(f.name for f in _FIELDS if f.section == s) for s in ...}`` at module scope
    SEGFAULTS while executing THIS module — 5/5 runs, in ``_PySet_AddTakeRef``. The trigger is
    narrower than "a nested comprehension" (a review refuted that shape, correctly, from a toy
    module): it is ``frozenset(<generator>)`` inside a module-scope comprehension. Measured on this
    file, 5 runs each — ``frozenset({set comp})`` 0/5, ``frozenset([list comp])`` 0/5,
    ``frozenset(<genexp>)`` 5/5 with any outer iterable (``dict.fromkeys``, ``sorted``, a bare name).
    It needs this module's own state to reproduce, so a reproduction extracted into a small file
    passes and proves nothing. Issue #46 pins a final 3.14."""
    sections: dict[str, set[str]] = {}
    for registered in _FIELDS:
        if registered.section in _FOLDED:
            sections.setdefault(registered.section, set()).add(registered.name)
    return {name: frozenset(names) for name, names in sections.items()}


_SECTION_FIELDS: dict[str, frozenset[str]] = _derive_section_fields()


def _open_sections(errors: catalog.FormErrors, autofocus: str) -> frozenset[str]:
    """The folded sections that must render OPEN: the ones holding an errored field or the autofocus
    target. Empty on a clean render, so the rare sections stay folded as ruled."""
    marked = set(errors) | ({autofocus} if autofocus else set())
    return frozenset(name for name, fields in _SECTION_FIELDS.items() if fields & marked)


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
    """One ruled row of the record card, ready to render: the registry's declaration joined to THIS
    render's value, error and focus. ``workbench/_feld.html`` prints it and nothing else, so a field
    is on the card exactly when the registry says so."""

    name: str
    label: str
    control: str
    value: str
    hint: str
    error: str
    autofocus: bool
    options: _Options
    blank: str
    element_id: str
    hx: tuple[tuple[str, str], ...]
    fit: str
    required: bool
    archivist_only: bool
    help: str


def _card_fields(
    values: Mapping[str, object],
    bestand: BestandChooser,
    *,
    errors: catalog.FormErrors,
    autofocus: str,
) -> dict[str, tuple[_CardRow, ...]]:
    """The card's rows grouped by section, in DOM order — the ONE list the template loops over.

    Only ``focusable`` rows can carry the caret, so a target the registry does not mark focusable
    focuses nothing rather than nothing-visible."""
    option_lists: dict[str, _Options] = {
        "collection_options": bestand.options(),
        "media_type_options": vocab.media_type_options(),
        "document_type_groups": vocab.grouped_document_type_options(),
        "sichtbarkeit_options": _SICHTBARKEIT_OPTIONS,
    }
    ulid = str(values.get("ulid") or "")
    sections: dict[str, list[_CardRow]] = {}
    for registered in _FIELDS:
        if registered.control in ("", "textarea"):
            continue  # no control, or the prose area the Beschreibung section renders itself
        value = str(values.get(registered.name) or "")
        hx = registered.hx
        if registered.hx_get:
            hx = (("hx-get", reverse(registered.hx_get, args=[ulid])), *hx)
        sections.setdefault(registered.section, []).append(
            _CardRow(
                name=registered.name,
                label=registered.label,
                control=registered.control,
                value=value,
                hint=registered.hint,
                error=errors.get(registered.name, ""),
                autofocus=registered.focusable and registered.name == autofocus,
                options=option_lists.get(registered.options, ()),
                blank=registered.blank,
                element_id=registered.element_id,
                hx=hx,
                fit=registered.fit,
                required=registered.required,
                archivist_only=registered.archivist_only,
                help=registered.help,
            )
        )
    return {name: tuple(rows) for name, rows in sections.items()}


# --- the CAS conflict diff (spec §6.1) ---------------------------------------------


def _conflict_rows(mine: Article, theirs: Article) -> list[_ConflictRow]:
    """The neutral CAS diff (spec §6.1): one row per CHANGED field, submitted against the winner's
    stored Article. The rows are the registry's fields carrying a diff label, in the form's own order,
    each spelled by the field's own renderer; the Signatur row is flagged so the template renders both
    cells as ``.c-sig`` marks."""
    rows: list[_ConflictRow] = []
    for registered in _FIELDS:
        if not registered.diff:
            continue
        mine_str, theirs_str = registered.diff_of(mine), registered.diff_of(theirs)
        if mine_str != theirs_str:
            rows.append(
                _ConflictRow(
                    label=registered.diff,
                    mine=mine_str,
                    theirs=theirs_str,
                    is_sig=registered.name == "ref_code",
                )
            )
    return rows


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
    # ?fokus=signatur tells the edit view to autofocus the Signatur field on this first load.
    return HttpResponseRedirect(f"{reverse('artikel-bearbeiten', args=[copy.ulid])}?fokus=signatur")


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
    archive, stored, _ = gated
    if request.method == "POST":
        article_services.hard_delete_article(archive, ulid)
        return _redirect(request, "/")  # HTMX: HX-Redirect to the workbench (spec §5)
    # Verwerfen (abandoning a draft from the edit form) reuses this identical confirm page + the same
    # hard-delete, only reworded (spec §7 — avoids a second destructive idiom). ?verwerfen=1 flags it,
    # but the "Entwurf verwerfen" wording is only honest for a DRAFT — a published article is deleted,
    # not discarded, so it always reads "Artikel löschen?" regardless of the query param.
    verwerfen = request.GET.get("verwerfen") == "1" and stored.article.lifecycle is Lifecycle.DRAFT
    return render_screen(
        request,
        "workbench/artikel_loeschen.html",
        {
            "ulid": ulid,
            "title": stored.article.title,
            "ref_code": stored.article.ref_code or "",
            "titel_confirm": "Entwurf verwerfen?" if verwerfen else "Artikel löschen?",
            "button_label": "Entwurf verwerfen" if verwerfen else "Endgültig löschen",
            "action": reverse("artikel-loeschen", args=[ulid]),
        },
    )


# --- the lifecycle verb (spec §6.2) ------------------------------------------------
#
# There is no lifecycle ROUTE any more. Publishing and withdrawing both ride the edit form's own
# CAS-guarded write (owner decision 2026-08-08 — saving IS publishing: a separate transition rebuilt
# the record from disk and discarded the archivist's unsaved edits without a word). After the form
# wave the standalone POST /artikel/<ulid>/lebenszyklus had exactly one live caller — the detail
# reader's withdraw form — while its `veroeffentlichen` branch was UI-unreachable from anywhere. The
# detail reader now LINKS to /bearbeiten for both verbs, symmetric with its publish link, so the
# archivist reads the exposure statement before either transition; the route, its urls.py row, its
# leak-matrix contract row and the six tests guarding a verb nothing could reach went with it.


def _lifecycle_for(aktion: str) -> Lifecycle | None:
    """Map the lifecycle POST verb to its target state, or ``None`` for an unknown verb."""
    match aktion:
        case "veroeffentlichen":
            return Lifecycle.PUBLISHED
        case "zurueckziehen":
            return Lifecycle.DRAFT
        case _:
            return None


# --- the reader's sheet on the edit surface (owner rulings 1 + 5, 2026-08-08) -------


@dataclass(frozen=True, slots=True)
class _EinblickViewModel:
    """The EXPOSURE statement: who gains sight of this record, and which fields they get. Permanent
    chrome on the edit surface since the separate over-exposure preview gate retired (owner ruling 5,
    2026-08-08) — the fact the archivist used to buy with three extra interactions is simply on
    screen. Built from the domain ``preview()`` like the retired panel was, so the who-sees decision
    stays in the domain and is never re-implemented (and never client-side).

    ``draft`` switches the statement's tense: a draft is archivist-only TODAY, so saying "Sichtbar
    für: Öffentlich" about it would be a lie — it reads "Nach Veröffentlichung sichtbar für: …".
    ``public`` drives WEIGHT emphasis only (no loud color — the exposure fact is neither draft nor
    error)."""

    audience: str
    public: bool
    fields: str
    draft: bool


@dataclass(frozen=True, slots=True)
class _SheetViewModel:
    """The reader's view of THIS record, server-rendered beside the card (owner ruling 1 —
    composition E: the work column plus THE pulled sheet). Deliberately the reader's facts only:
    Titel, Signatur, the machine Datierung, the cover thumbnail, the first body paragraph, and the
    exposure statement. Every value comes from the stored Article through the same renderers the
    reader's own surfaces use (law C7), and the exposure comes from the domain — nothing here is a
    second implementation of a reader fact.

    ``ref_code`` empty renders NO Signatur mark rather than the hollow "ohne Signatur" slot: on this
    screen absence is carried by the Signatur INPUT (owner finding, signals-once)."""

    title: str
    ref_code: str
    datierung: str
    thumb_url: str
    absatz: str
    einblick: _EinblickViewModel | None


def _einblick_view_model(article: Article, bestand: BestandChooser) -> _EinblickViewModel | None:
    """The exposure statement for ``article``, computed by the domain ``preview()`` over the resolved
    collection chain. ``None`` when the chain cannot resolve (fail-closed: no statement rather than a
    misleading one — the same rule the retired preview panel followed)."""
    try:
        chain = resolve_chain(article.collection_id, bestand.by_ulid())
    except DomainError:
        return None
    result = preview(article, chain)
    return _EinblickViewModel(
        audience=_preview_audience_label(result),
        public=result.public,
        fields=_preview_fields_label(result),
        draft=article.lifecycle is Lifecycle.DRAFT,
    )


def _sheet_view_model(article: Article, bestand: BestandChooser) -> _SheetViewModel:
    """The reader's-sheet view-model, built from the STORED article's READER PROJECTION — never from
    unsaved keystrokes: the sheet answers "what does a reader see of the record as it stands", which
    is why it can retire the publish-time preview.

    THE PROJECTION IS THE POINT (learning G.42). A box labelled ``aria-label="Leseansicht"`` must show
    what the domain's ``project()`` produces. Reading the stored Article field by field printed the
    same bytes only by COINCIDENCE — ``project`` floors exactly ``ARCHIVIST_ONLY_FIELDS`` and the
    sheet happens to show none of them. Calling the pipeline means the floor already holds the day
    that set grows. Only the FLOOR half runs: ``can_view`` would deny every non-archivist a DRAFT by
    definition, and "who WOULD see this once published" is the exposure statement's question.

    It travels with EVERY write, by two mechanisms: the metadata save swaps the whole
    ``#form-region``, and the structural media POSTs carry it out-of-band
    (``hx-select-oob="#lesesicht"``). Both read this one view-model out of the same full-page
    render."""
    read = project(Public(), article)
    return _SheetViewModel(
        title=read.title,
        ref_code=read.ref_code or "",
        # the machine value through the ONE machine-date renderer (vocab.datierung_mono, law C7) —
        # exactly what the workbench pane, the reader's own preview of a record, prints in this very
        # .meta hook (mono). The human-German spelling has its own single
        # renderer (vocab.edtf_to_german) and belongs to the detail reader's header.
        datierung=vocab.datierung_mono(read.date),
        thumb_url=(thumbnail_url(read.ulid, read.media[0].content_hash) if read.media else ""),
        # the FIRST body paragraph, split by the reader view's own paragraph rule (browse_views) so
        # the sheet cannot disagree with the page it previews
        absatz=next(iter(_body_paragraphs(read.body)), ""),
        # the EXPOSURE statement is computed from the STORED article: it reports who gains sight of
        # the record, which is a question about the record, not about the projection of it.
        einblick=_einblick_view_model(article, bestand),
    )


def _preview_audience_label(result: VisibilityPreview) -> str:
    """The who-gains-sight string for the preview panel (spec §6.2): the widest rung the article
    would reach after publication, in plain German. Reuses the shared rung captions so the preview
    can't drift from the ledger/CAS-diff wording; the ``Niemand`` fallback is preview-specific."""
    if result.public:
        return vocab.SICHTBARKEIT_PUBLIC
    if result.groups:
        return vocab.groups_label(result.groups)
    if result.members:
        return vocab.SICHTBARKEIT_MEMBERS
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
