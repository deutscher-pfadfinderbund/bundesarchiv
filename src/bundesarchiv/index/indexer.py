"""The indexer — materializes the files-canonical core into ``ArticleIndex`` rows.

Two surfaces:

- ``build_row`` is PURE: an Article plus its already-resolved Collection chain becomes a column
  dict. No IO, no ORM writes — it only names ``ArticleIndex`` columns as dict keys, so it is
  fully testable without a database. ``cap_year`` is injected (not read from the clock) to keep
  the decade computation deterministic and the function pure; ``rebuild`` supplies the current
  year.
- ``rebuild`` is the IO edge: it wipes the whole table and re-reads every Collection and Article
  through the repositories, resolving each Article's chain and effective audience, in a single
  transaction. The index is derived and disposable (ADR 0003/0004, 0012): a full rebuild is how
  staleness is cleared in v1.

Fail-closed is the security invariant (ADR 0012). Any ``DomainError`` resolving an Article — a
dangling ``collection_id``, a broken tree, a mis-bound chain — does NOT drop the Article and does
NOT guess a visibility. It writes an archivist-only row (``archivist_only=True``, ``tier=None``,
no groups) that still carries the Article's text, so an Archivist can search for it and fix the
source, and records the ulid in the ``RebuildReport`` for the caller/CLI to surface.
"""

from dataclasses import dataclass

from django.db import transaction

from bundesarchiv.domain.audience import ARCHIVIST_ONLY, effective_audience
from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import Article, Collection, Ulid
from bundesarchiv.index.models import _ARCHIVIST_TEXT_SOURCES, ArticleIndex
from bundesarchiv.index.scope import ScopeColumns, _scope_columns
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

# Bump on any ADR 0011 config change (FTS config, collation, wrapper functions). The Part 4
# background worker rebuilds when a row's stored config_version does not match this value.
CONFIG_VERSION = 1

# The exact Article fields ``_archivist_text`` folds — its own declaration of what it reads. The
# assert below ties this to the domain floor ``_ARCHIVIST_TEXT_SOURCES`` (itself pinned to
# ``ARCHIVIST_ONLY_FIELDS`` at the model's import). If the floor grows a text-bearing field, or
# the builder starts reading one outside the floor, these diverge and the module fails to import
# — a fail-closed drift trip, never a silent under- or over-index.
_BUILDER_FIELDS: frozenset[str] = frozenset({"physical_location", "custom"})
assert _BUILDER_FIELDS == _ARCHIVIST_TEXT_SOURCES, (
    "archivist_text builder drifted from the domain floor"
)


@dataclass(frozen=True, slots=True)
class RebuildReport:
    """The outcome of a full ``rebuild``. ``failed_closed`` names the ulids indexed as
    fail-closed archivist-only rows (a resolution error), for the caller/CLI to surface so an
    Archivist can repair the source."""

    indexed: int
    failed_closed: tuple[str, ...]


def _archivist_text(article: Article) -> str:
    """Fold the archivist-only text sources (``_BUILDER_FIELDS``) into one blank-joined string:
    the physical location and the custom-metadata VALUES only. Custom KEYS are structure, not
    prose, so they are not indexed. Member-visible fields (title/body/creator/…) never appear
    here — the module-level assert pins this to exactly the domain floor."""
    custom_values = [value for _key, value in article.custom]
    return " ".join([article.physical_location or "", *custom_values]).strip()


def build_row(article: Article, chain: ResolvedChain, *, cap_year: int) -> dict[str, object]:
    """Pure: an Article and its resolved Collection ``chain`` -> the ``ArticleIndex`` column dict.

    Routes visibility through the single domain resolver (``effective_audience``) and the scope
    seam (``_scope_columns``) — it never re-derives a tier. Date columns come from
    ``article.date`` (bounds + decades, both capped by the injected ``cap_year``);
    ``collection_ancestors`` is the chain's ulids leaf→root, including the Article's own
    Collection. No IO — keys are ORM column names only.
    """
    ancestors = [c.ulid for c in chain.collections]
    scope = _scope_columns(effective_audience(article, chain))
    return _content_columns(article, ancestors=ancestors, cap_year=cap_year) | _scope_dict(scope)


def _content_columns(article: Article, *, ancestors: list[str], cap_year: int) -> dict[str, object]:
    """Every non-scope column: identity, member-visible text, folded archivist_text, dates, and
    the Collection ancestry. Shared by ``build_row`` and the fail-closed path (which supplies an
    empty ``ancestors`` because its chain never resolved). No IO — keys are ORM column names."""
    earliest, latest, decades = _date_columns(article, cap_year=cap_year)
    return {
        "ulid": article.ulid,
        "title": article.title,
        "body": article.body,
        "creator": article.creator,
        "subject_place": article.subject_place,
        "ref_code": article.ref_code,
        "media_type": article.media_type,
        "document_type": article.document_type,
        "tags": list(article.tags),
        "archivist_text": _archivist_text(article),
        "date_edtf": article.date.value if article.date is not None else None,
        "date_earliest": earliest,
        "date_latest": latest,
        "decades": list(decades),
        "collection_id": article.collection_id,
        "collection_ancestors": ancestors,
        "config_version": CONFIG_VERSION,
    }


def _scope_dict(scope: ScopeColumns) -> dict[str, object]:
    """The three scope columns as a dict fragment, merged into the content columns."""
    return {
        "archivist_only": scope.archivist_only,
        "tier": scope.tier,
        "groups": list(scope.groups),
    }


def _date_columns(article: Article, *, cap_year: int) -> tuple[object, object, tuple[int, ...]]:
    """(date_earliest, date_latest, decades) from the Article's EDTF date, or nulls/empty when
    it has none. ``date_latest`` is ``None`` for an open-ended interval (the EdtfDate bounds)."""
    if article.date is None:
        return None, None, ()
    earliest, latest = article.date.bounds()
    return earliest, latest, article.date.decades(cap_year=cap_year)


def _fail_closed_row(article: Article, *, cap_year: int) -> dict[str, object]:
    """The fail-closed row for an Article whose chain/audience could not be resolved: the
    archivist-only scope (no tier, no groups) folded onto its otherwise-normal columns, so it is
    still findable by an Archivist. Dates and text still index; only visibility fails closed. Its
    chain never resolved, so it carries no ancestors."""
    content = _content_columns(article, ancestors=[], cap_year=cap_year)
    return content | _scope_dict(_scope_columns(ARCHIVIST_ONLY))


def rebuild(store: ObjectStore) -> RebuildReport:
    """Wipe and rebuild the whole ``ArticleIndex`` from the files-canonical core in one
    transaction. Loads every Collection and Article through the repositories, resolves each
    Article's chain + effective audience, and writes one row per Article. A ``DomainError`` for
    any Article yields a fail-closed archivist-only row (still indexed, counted in the report)
    rather than dropping it or guessing visibility. Idempotent: the leading wipe means a repeat
    rebuild produces the same rows with no duplicates.
    """
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    lookup: dict[Ulid, Collection] = {c.ulid: c for c in collections.load_all()}
    cap_year = _current_year()

    rows: list[dict[str, object]] = []
    failed: list[str] = []
    for ulid in articles.list_ulids():
        article = articles.load(ulid).article
        try:
            chain = resolve_chain(article.collection_id, lookup)
            rows.append(build_row(article, chain, cap_year=cap_year))
        except DomainError:
            rows.append(_fail_closed_row(article, cap_year=cap_year))
            failed.append(article.ulid)

    with transaction.atomic():
        ArticleIndex.objects.all().delete()
        ArticleIndex.objects.bulk_create(ArticleIndex(**row) for row in rows)

    return RebuildReport(indexed=len(rows), failed_closed=tuple(failed))


def _current_year() -> int:
    """The current calendar year, read here (not in ``build_row``) so ``build_row`` stays pure.
    Imported locally so the pure ``build_row`` path never depends on the clock module."""
    import datetime

    return datetime.date.today().year
