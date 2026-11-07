"""The bulk-edit (Sammelbearbeitung) check and commit route (spec §2 D/R, §4, §6).

``/articles/bulk-edit`` checks first and commits only with ``confirmed=1`` (spec §0.1). No
server-side session state: the selection rides as hidden ``selection`` inputs into the commit.
"""

from django.http import HttpRequest
from django.http.response import HttpResponseBase

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import browse, bulk, vocab
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.app.web.media_views import not_found
from bundesarchiv.app.web.viewers import render_screen, viewer_of
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import ULID, Article
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.errors import ArchiveError


def article_bulk_edit(request: HttpRequest) -> HttpResponseBase:
    """``POST /articles/bulk-edit`` — confirm (no ``confirmed``) or commit (``confirmed=1``).
    Archivist-only, POST-only → the plain 404 otherwise (spec §6.1/§6.2)."""
    archivist = viewer_of(request)
    if not isinstance(archivist, Archivist) or request.method != "POST":
        return not_found()
    archive = Archive.canonical()
    chooser = CollectionChooser.of(archive)
    # the ledger's ticked head box ("all") carries the rows of the page it was rendered on
    all_ulids = request.POST.get("all", "").split()
    selection = _distinct_valid_ulids([*request.POST.getlist("selection"), *all_ulids])
    name = request.POST.get("field", "")
    field = bulk.BY_TARGET.get(name)
    value = request.POST.get(field.value_input if field is not None else bulk.TEXT_INPUT, "")

    def reject(error: str) -> HttpResponseBase:
        return _reject(request, chooser, selection, name, value, error)

    if not selection or field is None:
        return reject("Keine Einträge ausgewählt." if not selection else "Bitte ein Feld wählen.")
    confirmed = request.POST.get("confirmed") == "1"
    selected = _load_all(archive, selection) if field.reads_selection or not confirmed else []
    error = field.validate(value, selected, chooser)
    if error is not None:
        return reject(error)
    orphans = {a.ulid for a in selected if field.clears_document_type(a, value)}
    if not confirmed or (orphans and request.POST.get("clear_document_type") != "1"):
        return _confirm(request, chooser, selected, field, value, orphans)
    return _commit(request, archive, chooser, selection, field, value, archivist.username)


def bulk_document_types(request: HttpRequest) -> HttpResponseBase:
    """``GET /articles/bulk-edit/document-types`` — the Dokumenttyp options for a Medienart; the
    no-JS drawer lists them all."""
    if not isinstance(viewer_of(request), Archivist) or request.method != "GET":
        return not_found()
    # htmx sends the drawer's <select name="value_media_type"> value under that name; accept the plain
    # media_type name too so the endpoint is callable directly.
    media_type = request.GET.get("value_media_type") or request.GET.get("media_type", "")
    return render_screen(
        request,
        "workbench/_document_type_options.html",
        {"document_types": vocab.document_types_for(media_type)},
    )


def _distinct_valid_ulids(raw: list[str]) -> list[ULID]:
    """The selection, deduped + shape-validated in-view (spec §6.4). A malformed ulid is dropped here
    (never distinguishable, never a 500); a well-formed-but-absent one is bucketed ``missing`` later."""
    return list(dict.fromkeys(u for u in raw if is_valid_ulid(u)))


def _confirm(
    request: HttpRequest,
    chooser: CollectionChooser,
    articles: list[Article],
    field: bulk.BulkField,
    value: str,
    orphans: set[ULID],
) -> HttpResponseBase:
    """The check page (state D), also shown again for a Medienart commit that would clear a
    Dokumenttyp (``orphans``) without ``clear_document_type=1``. An absent article is left out; the
    commit buckets it ``missing``, so the page reveals nothing about why it is gone."""
    return render_screen(
        request,
        "workbench/bulk_edit_review.html",
        {
            "selection": [a.ulid for a in articles],
            "field": field.target,
            "value": value,
            "value_field": field.value_input,
            "field_label": field.label,
            "value_display": field.shown_new(value, chooser),
            "count": len(articles),
            "affected": field.counted(len(articles)),
            "cleared": bulk.BY_TARGET["document_type"].counted(len(orphans)) if orphans else "",
            "rows": [
                {
                    "ref_code": a.ref_code or "",
                    "title": a.title,
                    "previous": field.shown_current(a, chooser),
                    "document_type": (a.document_type or "") if a.ulid in orphans else "",
                }
                for a in articles
            ],
            "cancel_query": browse.select_page_query({}, [a.ulid for a in articles], []),
        },
        chooser=chooser,
    )


def _commit(
    request: HttpRequest,
    archive: Archive,
    chooser: CollectionChooser,
    selection: list[ULID],
    field: bulk.BulkField,
    value: str,
    changed_by: str,
) -> HttpResponseBase:
    """The commit and its result page (state R)."""
    outcome = bulk.apply_bulk(archive, selection, field, value, changed_by=changed_by)
    return render_screen(
        request,
        "workbench/bulk_edit_result.html",
        {
            "field_label": field.label,
            "value_display": field.shown_new(value, chooser),
            "saved": outcome.saved,
            "total": outcome.saved + len(outcome.conflicted) + len(outcome.missing),
            "conflicted": outcome.conflicted,
            "missing_count": len(outcome.missing),
            "doctype_cleared_count": len(outcome.doctype_cleared),
            "bulk_index_lag": vocab.BULK_INDEX_LAG if outcome.index_lagged else "",
            "retry_query": browse.select_page_query({}, [], [r.ulid for r in outcome.conflicted]),
        },
        chooser=chooser,
    )


def _reject(
    request: HttpRequest,
    chooser: CollectionChooser,
    selection: list[ULID],
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
            "selection": selection,
            "error": error,
            "count": len(selection),
            "cancel_query": browse.select_page_query({}, selection, []),
            **bulk.field_picker_context(chooser, field=field, value=value),
        },
        chooser=chooser,
    )


def _load_all(archive: Archive, ulids: list[ULID]) -> list[Article]:
    """Absent, unreadable and trashed ones are skipped."""
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
