"""The bulk-edit (Sammelbearbeitung) confirm + commit view (spec §2 D/R, §4, §6).

ONE POST route, ``/artikel/sammelbearbeitung`` (archivist-gated, POST-only → byte-identical 404
otherwise). Two phases in one handler (confirm-always, spec §0.1):

- WITHOUT ``bestaetigt=1``: validate the selection + field + value, then render the full-page CONFIRM
  (state D) — field · new value · count · the article list; a Medienart change that orphans
  Dokumenttypen additionally lists each affected row and requires ``dokumenttyp_leeren=1`` on commit.
  A validation failure re-renders the ledger's drawer with the verbatim error, selection preserved.
- WITH ``bestaetigt=1``: run ``bulk.apply_bulk`` (the ONE bulk Conflict catch) and render the
  full-page RESULT (state R) — saved count + actionable conflict/missing rows.

Zero server-side session state: the selection rides as hidden ``auswahl`` inputs from the confirm
page into the commit hop. Every deny/invalid shape yields the least-visible output (spec §6): a
non-archivist gets the media 404; an unknown ``feld`` / empty selection / bad value mutates nothing.
"""

from pathlib import Path

from django.conf import settings
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from django.shortcuts import render

from bundesarchiv.app.web import browse, bulk, vocab
from bundesarchiv.app.web.media_views import _not_found
from bundesarchiv.app.web.viewers import viewer_of
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Article, Ulid
from bundesarchiv.domain.viewer import Archivist
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import ArchiveError
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository


def _canonical_store() -> ObjectStore:
    return LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))


def article_bulk_edit(request: HttpRequest) -> HttpResponseBase:
    """``POST /artikel/sammelbearbeitung`` — confirm (no ``bestaetigt``) or commit (``bestaetigt=1``).
    Archivist-only, POST-only → the byte-identical 404 otherwise (spec §6.1/§6.2)."""
    if not isinstance(viewer_of(request), Archivist) or request.method != "POST":
        return _not_found()
    store = _canonical_store()
    auswahl = _distinct_valid_ulids(request.POST.getlist("auswahl"))
    feld = request.POST.get("feld", "")
    wert = request.POST.get(bulk.value_input_of(feld), "") if bulk.is_allowed_field(feld) else ""

    error = _validate(auswahl, feld, store, wert)
    if error is not None:
        return _reject(request, store, auswahl, feld, error)

    if request.POST.get("bestaetigt") == "1":
        return _commit(request, store, auswahl, feld, wert)
    return _confirm(request, store, auswahl, feld, wert)


def bulk_dokumenttypen(request: HttpRequest) -> HttpResponseBase:
    """``GET /artikel/sammelbearbeitung/dokumenttypen?medienart=`` — the dependent Dokumenttyp option
    list for the bulk drawer (spec §0.5). ULID-FREE (pure vocab, no article), archivist-gated,
    GET-only → the byte-identical 404 otherwise. The no-JS baseline renders all optgroups + the
    server re-validates per-article; this only removes a round-trip on Medienart change."""
    if not isinstance(viewer_of(request), Archivist) or request.method != "GET":
        return _not_found()
    # htmx sends the drawer's <select name="wert_media_type"> value under that name; accept the plain
    # media_type / medienart names too so the endpoint is callable directly.
    media_type = (
        request.GET.get("wert_media_type")
        or request.GET.get("media_type")
        or request.GET.get("medienart", "")
    )
    return render(
        request,
        "workbench/_dokumenttyp_options.html",
        {"document_types": vocab.document_types_for(media_type)},
    )


def _distinct_valid_ulids(raw: list[str]) -> list[str]:
    """The selection, deduped + shape-validated in-view (spec §6.4). A malformed ulid is dropped here
    (never distinguishable, never a 500); a well-formed-but-absent one is bucketed ``missing`` later."""
    return list(dict.fromkeys(u for u in raw if is_valid_ulid(u)))


def _validate(auswahl: list[str], feld: str, store: ObjectStore, wert: str) -> str | None:
    """Return the verbatim German error for an invalid apply, or ``None`` if it may proceed. Order:
    selection present → field chosen + allowed → value-level (collection in set; Dokumenttyp-alone
    fits every article's current Medienart). Fail-closed: an unknown field is refused (zero mutation).
    """
    if not auswahl:
        return "Keine Artikel ausgewählt."
    if not feld or not bulk.is_allowed_field(feld):
        return "Bitte ein Feld wählen."
    if feld == "media_type" and (wert.strip() not in vocab.media_types()):
        return "Medienart ist erforderlich."
    if feld == "collection_id" and wert.strip() not in _collection_names(store):
        return "Bitte einen Bestand wählen."
    if feld == "document_type" and wert.strip():
        loaded = _load_all(store, auswahl)
        if not bulk.document_type_fits_all(wert.strip(), loaded):
            return (
                f'„{wert.strip()}" gehört nicht zur Medienart aller ausgewählten Artikel. '
                "Bitte zuerst die Medienart angleichen oder die Auswahl einschränken."
            )
    return None


def _confirm(
    request: HttpRequest, store: ObjectStore, auswahl: list[str], feld: str, wert: str
) -> HttpResponseBase:
    """Render the full-page confirm (state D). Loads each selected article (read-only) for the c-sig +
    Titel list and to detect Medienart orphans. Absent articles are silently skipped from the list
    (they will bucket ``missing`` on commit) — no deleted-vs-never oracle."""
    articles = _load_all(store, auswahl)
    names = _collection_names(store)
    orphans = _orphans(articles, feld, wert)
    return render(
        request,
        "workbench/sammelbearbeitung_pruefen.html",
        {
            "auswahl": [a.ulid for a in articles],
            "feld": feld,
            "wert": wert,
            "wert_field": bulk.value_input_of(feld),
            "feld_label": bulk.label_of(feld),
            "wert_display": bulk.field_display(feld, wert, names),
            "anzahl": len(articles),
            "artikel_liste": [_confirm_row(a) for a in articles],
            "orphans": [_orphan_row(a) for a in orphans],
            "abbrechen_query": browse.select_page_query({}, [a.ulid for a in articles], []),
        },
    )


def _commit(
    request: HttpRequest, store: ObjectStore, auswahl: list[str], feld: str, wert: str
) -> HttpResponseBase:
    """Run the apply (state R). If the Medienart change orphans any Dokumenttyp, the commit REQUIRES
    ``dokumenttyp_leeren=1`` (server-enforced, geprueft-idiom) — a missing flag re-confirms without
    writing. Otherwise ``bulk.apply_bulk`` runs and the result page renders. The orphan pre-check
    loads only for a media_type apply (the only field that can orphan) — every other field skips it."""
    if (
        feld == "media_type"
        and request.POST.get("dokumenttyp_leeren") != "1"
        and _orphans(_load_all(store, auswahl), feld, wert)
    ):
        return _confirm(request, store, auswahl, feld, wert)  # re-confirm, no write
    outcome = bulk.apply_bulk(store, auswahl, feld, wert)
    names = _collection_names(store)
    return render(
        request,
        "workbench/sammelbearbeitung_ergebnis.html",
        {
            "feld_label": bulk.label_of(feld),
            "wert_display": bulk.field_display(feld, wert, names),
            "saved": outcome.saved,
            "conflicted": outcome.conflicted,
            "missing": outcome.missing,
            "doctype_cleared": outcome.doctype_cleared,
            "index_lagged": outcome.index_lagged,
            "conflict_count": len(outcome.conflicted),
            "erneut_query": browse.select_page_query({}, [], [r.ulid for r in outcome.conflicted]),
        },
    )


def _reject(
    request: HttpRequest, store: ObjectStore, auswahl: list[str], feld: str, error: str
) -> HttpResponseBase:
    """A validation failure (spec §2 C): re-render the confirm page in ERROR mode — the Feld chooser
    drawer (Feld select + value widgets, the chosen field pre-selected) with the verbatim error as a
    c-field-fehler, and the selection carried as hidden ``auswahl`` inputs. The archivist fixes the
    field/value and re-submits from here — the selection is never lost, and the back-link to the
    ledger also carries ?auswahl= so leaving doesn't drop it either.

    (Not the full ledger+drawer in-context: the confirm POST does not carry the search query, so a
    ledger re-render would silently drop the archivist's filter and might not show the selected rows
    — the gate's MIN variant. This keeps the drawer + selection + verbatim error, which is the
    spec-§2-C intent, without that entanglement.)"""
    return render(
        request,
        "workbench/sammelbearbeitung_pruefen.html",
        {
            "auswahl": auswahl,
            "feld": feld,
            "feld_label": bulk.label_of(feld),
            "fehler": error,
            "anzahl": len(auswahl),
            "artikel_liste": [],
            "orphans": [],
            "drawer": True,
            "feld_options": tuple((f.target, f.label) for f in bulk.FIELDS),
            "media_type_options": (
                ("", "— Medienart wählen —"),
                *((m, m) for m in vocab.media_types()),
            ),
            "document_type_groups": vocab.grouped_document_type_options(),
            "collection_options": (
                ("", "— Bestand wählen —"),
                *sorted(_collection_names(store).items(), key=lambda kv: kv[1]),
            ),
            "abbrechen_query": browse.select_page_query({}, auswahl, []),
        },
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


def _confirm_row(article: Article) -> dict[str, str]:
    """One confirm-list row: the c-sig mark + Titel."""
    return {"ref_code": article.ref_code or "", "title": article.title}


def _orphan_row(article: Article) -> dict[str, str]:
    """One orphan row for the confirm page: `Dokumenttyp: {alt} → (leer)` (spec §7 verbatim)."""
    return {
        "ref_code": article.ref_code or "",
        "title": article.title,
        "alt": article.document_type or "",
    }


def _load_all(store: ObjectStore, ulids: list[str]) -> list[Article]:
    """Load every present article for ``ulids`` (read-only, for the confirm list + orphan/pair
    checks). An absent/unreadable ulid is silently skipped — it will bucket ``missing`` on commit."""
    repo = ArticleRepository(store)
    out: list[Article] = []
    for ulid in ulids:
        try:
            out.append(repo.load(ulid).article)
        except ArchiveError:
            continue
    return out


def _collection_names(store: ObjectStore) -> dict[Ulid, str]:
    """ULID→name map of every collection (for the collection-value validation + display)."""
    return {c.ulid: c.name for c in CollectionRepository(store).load_all()}
