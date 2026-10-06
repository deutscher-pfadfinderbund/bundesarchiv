"""The bulk-edit (Sammelbearbeitung) check and commit route (spec §2 D/R, §4, §6).

``/articles/bulk-edit`` checks first and commits only with ``bestaetigt=1`` (spec §0.1). No
server-side session state: the selection rides as hidden ``auswahl`` inputs into the commit.
"""

from django.http import HttpRequest
from django.http.response import HttpResponseBase

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import browse, bulk, vocab
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.media_views import not_found
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Article
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.errors import ArchiveError


def article_bulk_edit(request: HttpRequest) -> HttpResponseBase:
    """``POST /articles/bulk-edit`` — confirm (no ``bestaetigt``) or commit (``bestaetigt=1``).
    Archivist-only, POST-only → the plain 404 otherwise (spec §6.1/§6.2)."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist) or request.method != "POST":
        return not_found()
    archive = Archive.canonical()
    chooser = CollectionChooser.of(archive)
    # the ledger's ticked head box ("alle") carries the rows of the page it was rendered on
    all_ulids = request.POST.get("alle", "").split()
    selection = _distinct_valid_ulids([*request.POST.getlist("auswahl"), *all_ulids])
    field = request.POST.get("feld", "")
    # Read the value for ANY field, allowed or not: a refused field never mutates (``_validate``
    # gates that), and the reject page must echo what was typed — gating the read here blanked the
    # value whenever the placeholder was submitted.
    value = request.POST.get(bulk.value_input_of(field), "")

    error = _validate(selection, field, archive, chooser, value)
    if error is not None:
        return _reject(request, chooser, selection, field, value, error)

    if request.POST.get("bestaetigt") == "1":
        return _commit(request, archive, chooser, selection, field, value, archivist.username)
    return _confirm(request, archive, chooser, selection, field, value)


def bulk_document_types(request: HttpRequest) -> HttpResponseBase:
    """``GET /articles/bulk-edit/document-types?medienart=`` — the dependent Dokumenttyp option
    list for the bulk drawer (spec §0.5). ULID-FREE (pure vocab, no article), archivist-gated,
    GET-only → the plain 404 otherwise. The no-JS baseline renders all optgroups + the
    server re-validates per-article; this only removes a round-trip on Medienart change."""
    if not isinstance(viewer_of(request), Archivist) or request.method != "GET":
        return not_found()
    # htmx sends the drawer's <select name="wert_media_type"> value under that name; accept the plain
    # media_type / medienart names too so the endpoint is callable directly.
    media_type = (
        request.GET.get("wert_media_type")
        or request.GET.get("media_type")
        or request.GET.get("medienart", "")
    )
    return render_screen(
        request,
        "workbench/_document_type_options.html",
        {"document_types": vocab.document_types_for(media_type)},
    )


def _distinct_valid_ulids(raw: list[str]) -> list[str]:
    """The selection, deduped + shape-validated in-view (spec §6.4). A malformed ulid is dropped here
    (never distinguishable, never a 500); a well-formed-but-absent one is bucketed ``missing`` later."""
    return list(dict.fromkeys(u for u in raw if is_valid_ulid(u)))


def _validate(
    selection: list[str], field: str, archive: Archive, chooser: CollectionChooser, value: str
) -> str | None:
    """The verbatim German refusal of an apply, or ``None`` when it may proceed."""
    if not selection:
        return "Keine Artikel ausgewählt."
    if not field or not bulk.is_allowed_field(field):
        return "Bitte ein Feld wählen."
    if field == "media_type" and (value.strip() not in vocab.media_types()):
        return "Medienart ist erforderlich."
    if field == "collection_id" and not chooser.accepts(value):
        return chooser.error()
    if field == "document_type" and value.strip():
        loaded = _load_all(archive, selection)
        if not bulk.document_type_fits_all(value.strip(), loaded):
            return (
                f"„{value.strip()}“ gehört nicht zur Medienart aller ausgewählten Artikel. "
                "Bitte zuerst die Medienart angleichen oder die Auswahl einschränken."
            )
    return None


def _confirm(
    request: HttpRequest,
    archive: Archive,
    chooser: CollectionChooser,
    selection: list[str],
    field: str,
    value: str,
) -> HttpResponseBase:
    """The check page (state D). An absent article is left out; the commit buckets it ``missing``, so
    the page reveals nothing about why it is gone."""
    articles = _load_all(archive, selection)
    orphans = {a.ulid for a in _orphans(articles, field, value)}
    return render_screen(
        request,
        "workbench/bulk_edit_review.html",
        {
            "auswahl": [a.ulid for a in articles],
            "feld": field,
            "wert": value,
            "wert_field": bulk.value_input_of(field),
            "feld_label": bulk.label_of(field),
            "wert_display": bulk.field_display(field, value, chooser),
            "anzahl": len(articles),
            "betroffen": bulk.counted(field, len(articles)),
            "geleert": bulk.counted("document_type", len(orphans)) if orphans else "",
            "zeilen": [
                {
                    "ref_code": a.ref_code or "",
                    "title": a.title,
                    "bisher": bulk.current_display(a, field, chooser),
                    "dokumenttyp": (a.document_type or "") if a.ulid in orphans else "",
                }
                for a in articles
            ],
            "abbrechen_query": browse.select_page_query({}, [a.ulid for a in articles], []),
        },
        chooser=chooser,
    )


def _commit(
    request: HttpRequest,
    archive: Archive,
    chooser: CollectionChooser,
    selection: list[str],
    field: str,
    value: str,
    changed_by: str,
) -> HttpResponseBase:
    """The commit and its result page (state R). A Medienart change that clears a Dokumenttyp needs
    ``dokumenttyp_leeren=1``; without it the check page comes back and nothing is written."""
    if (
        field == "media_type"
        and request.POST.get("dokumenttyp_leeren") != "1"
        and _orphans(_load_all(archive, selection), field, value)
    ):
        return _confirm(request, archive, chooser, selection, field, value)  # re-confirm, no write
    outcome = bulk.apply_bulk(archive, selection, field, value, changed_by=changed_by)
    return render_screen(
        request,
        "workbench/bulk_edit_result.html",
        {
            "feld_label": bulk.label_of(field),
            "wert_display": bulk.field_display(field, value, chooser),
            "saved": outcome.saved,
            "total": outcome.saved + len(outcome.conflicted) + len(outcome.missing),
            "conflicted": outcome.conflicted,
            "missing_count": len(outcome.missing),
            "doctype_cleared_count": len(outcome.doctype_cleared),
            "bulk_index_lag": vocab.BULK_INDEX_LAG if outcome.index_lagged else "",
            "erneut_query": browse.select_page_query({}, [], [r.ulid for r in outcome.conflicted]),
        },
        chooser=chooser,
    )


def _reject(
    request: HttpRequest,
    chooser: CollectionChooser,
    selection: list[str],
    field: str,
    value: str,
    error: str,
) -> HttpResponseBase:
    """A refused apply (spec §2 C): the check page with the Feld chooser, what was sent and the
    selection kept. Not the list: this POST does not carry the search query."""
    return render_screen(
        request,
        "workbench/bulk_edit_review.html",
        {
            "auswahl": selection,
            "fehler": error,
            "anzahl": len(selection),
            "abbrechen_query": browse.select_page_query({}, selection, []),
            **bulk.field_picker_context(chooser, field=field, value=value),
        },
        chooser=chooser,
    )


def _orphans(articles: list[Article], field: str, value: str) -> list[Article]:
    """The articles whose Dokumenttyp would be cleared by a Medienart change (spec §3) — a non-empty
    current document_type that does not fit the new media_type. Empty for any non-media_type field."""
    if field != "media_type":
        return []
    return [
        a
        for a in articles
        if a.document_type is not None and not vocab.is_valid_pair(value.strip(), a.document_type)
    ]


def _load_all(archive: Archive, ulids: list[str]) -> list[Article]:
    """Load every present article for ``ulids`` (read-only, for the confirm list + orphan/pair
    checks). An absent/unreadable ulid, or one in the Papierkorb (ADR 0022), is silently skipped —
    it will bucket ``missing`` on commit."""
    repo = archive.articles
    out: list[Article] = []
    for ulid in ulids:
        try:
            article = repo.load(ulid).article
        except ArchiveError:
            continue
        if article.deleted is None:
            out.append(article)
    return out
