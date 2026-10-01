"""The bulk-edit (Sammelbearbeitung) check and commit route (spec §2 D/R, §4, §6).

``/articles/bulk-edit`` checks first and commits only with ``bestaetigt=1`` (spec §0.1). No
server-side session state: the selection rides as hidden ``auswahl`` inputs into the commit.
"""

from django.http import HttpRequest
from django.http.response import HttpResponseBase

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import browse, bulk, vocab
from bundesarchiv.app.web.bestand import BestandChooser
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
    bestand = BestandChooser.of(archive)
    # the ledger's ticked head box ("alle") carries the rows of the page it was rendered on
    alle = request.POST.get("alle", "").split()
    auswahl = _distinct_valid_ulids([*request.POST.getlist("auswahl"), *alle])
    feld = request.POST.get("feld", "")
    # Read the value for ANY feld, allowed or not: a refused field never mutates (``_validate``
    # gates that), and the reject page must echo what was typed — gating the read here blanked the
    # value whenever the placeholder was submitted.
    wert = request.POST.get(bulk.value_input_of(feld), "")

    error = _validate(auswahl, feld, archive, bestand, wert)
    if error is not None:
        return _reject(request, bestand, auswahl, feld, wert, error)

    if request.POST.get("bestaetigt") == "1":
        return _commit(request, archive, bestand, auswahl, feld, wert, archivist.username)
    return _confirm(request, archive, bestand, auswahl, feld, wert)


def bulk_dokumenttypen(request: HttpRequest) -> HttpResponseBase:
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
        "workbench/_dokumenttyp_options.html",
        {"document_types": vocab.document_types_for(media_type)},
    )


def _distinct_valid_ulids(raw: list[str]) -> list[str]:
    """The selection, deduped + shape-validated in-view (spec §6.4). A malformed ulid is dropped here
    (never distinguishable, never a 500); a well-formed-but-absent one is bucketed ``missing`` later."""
    return list(dict.fromkeys(u for u in raw if is_valid_ulid(u)))


def _validate(
    auswahl: list[str], feld: str, archive: Archive, bestand: BestandChooser, wert: str
) -> str | None:
    """The verbatim German refusal of an apply, or ``None`` when it may proceed."""
    if not auswahl:
        return "Keine Artikel ausgewählt."
    if not feld or not bulk.is_allowed_field(feld):
        return "Bitte ein Feld wählen."
    if feld == "media_type" and (wert.strip() not in vocab.media_types()):
        return "Medienart ist erforderlich."
    if feld == "collection_id" and not bestand.accepts(wert):
        return bestand.error()
    if feld == "document_type" and wert.strip():
        loaded = _load_all(archive, auswahl)
        if not bulk.document_type_fits_all(wert.strip(), loaded):
            return (
                f"„{wert.strip()}“ gehört nicht zur Medienart aller ausgewählten Artikel. "
                "Bitte zuerst die Medienart angleichen oder die Auswahl einschränken."
            )
    return None


def _confirm(
    request: HttpRequest,
    archive: Archive,
    bestand: BestandChooser,
    auswahl: list[str],
    feld: str,
    wert: str,
) -> HttpResponseBase:
    """The check page (state D). An absent article is left out; the commit buckets it ``missing``, so
    the page reveals nothing about why it is gone."""
    articles = _load_all(archive, auswahl)
    orphans = {a.ulid for a in _orphans(articles, feld, wert)}
    return render_screen(
        request,
        "workbench/sammelbearbeitung_pruefen.html",
        {
            "auswahl": [a.ulid for a in articles],
            "feld": feld,
            "wert": wert,
            "wert_field": bulk.value_input_of(feld),
            "feld_label": bulk.label_of(feld),
            "wert_display": bulk.field_display(feld, wert, bestand),
            "anzahl": len(articles),
            "betroffen": bulk.counted(feld, len(articles)),
            "geleert": bulk.counted("document_type", len(orphans)) if orphans else "",
            "zeilen": [
                {
                    "ref_code": a.ref_code or "",
                    "title": a.title,
                    "bisher": bulk.current_display(a, feld, bestand),
                    "dokumenttyp": (a.document_type or "") if a.ulid in orphans else "",
                }
                for a in articles
            ],
            "abbrechen_query": browse.select_page_query({}, [a.ulid for a in articles], []),
        },
        bestand=bestand,
    )


def _commit(
    request: HttpRequest,
    archive: Archive,
    bestand: BestandChooser,
    auswahl: list[str],
    feld: str,
    wert: str,
    changed_by: str,
) -> HttpResponseBase:
    """The commit and its result page (state R). A Medienart change that clears a Dokumenttyp needs
    ``dokumenttyp_leeren=1``; without it the check page comes back and nothing is written."""
    if (
        feld == "media_type"
        and request.POST.get("dokumenttyp_leeren") != "1"
        and _orphans(_load_all(archive, auswahl), feld, wert)
    ):
        return _confirm(request, archive, bestand, auswahl, feld, wert)  # re-confirm, no write
    outcome = bulk.apply_bulk(archive, auswahl, feld, wert, changed_by=changed_by)
    return render_screen(
        request,
        "workbench/sammelbearbeitung_ergebnis.html",
        {
            "feld_label": bulk.label_of(feld),
            "wert_display": bulk.field_display(feld, wert, bestand),
            "saved": outcome.saved,
            "total": outcome.saved + len(outcome.conflicted) + len(outcome.missing),
            "conflicted": outcome.conflicted,
            "missing_count": len(outcome.missing),
            "doctype_cleared_count": len(outcome.doctype_cleared),
            "bulk_index_lag": vocab.BULK_INDEX_LAG if outcome.index_lagged else "",
            "erneut_query": browse.select_page_query({}, [], [r.ulid for r in outcome.conflicted]),
        },
        bestand=bestand,
    )


def _reject(
    request: HttpRequest,
    bestand: BestandChooser,
    auswahl: list[str],
    feld: str,
    wert: str,
    error: str,
) -> HttpResponseBase:
    """A refused apply (spec §2 C): the check page with the Feld chooser, what was sent and the
    selection kept. Not the list: this POST does not carry the search query."""
    return render_screen(
        request,
        "workbench/sammelbearbeitung_pruefen.html",
        {
            "auswahl": auswahl,
            "fehler": error,
            "anzahl": len(auswahl),
            "abbrechen_query": browse.select_page_query({}, auswahl, []),
            **bulk.feldwahl_context(bestand, feld=feld, wert=wert),
        },
        bestand=bestand,
    )


def _orphans(articles: list[Article], feld: str, wert: str) -> list[Article]:
    """The articles whose Dokumenttyp would be cleared by a Medienart change (spec §3) — a non-empty
    current document_type that does not fit the new media_type. Empty for any non-media_type feld."""
    if feld != "media_type":
        return []
    return [
        a
        for a in articles
        if a.document_type is not None and not vocab.is_valid_pair(wert.strip(), a.document_type)
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
