"""The indexer — materializes the files-canonical core into ``ArticleIndex`` rows.

Surfaces:

- ``build_row`` is PURE: an Article plus its already-resolved Collection chain becomes a column
  dict. No IO, no ORM writes — it only names ``ArticleIndex`` columns as dict keys, so it is
  fully testable without a database. ``cap_year`` is injected (not read from the clock) to keep
  the decade computation deterministic and the function pure; ``rebuild`` supplies the current
  year.
- ``rebuild`` is the IO edge: it wipes the whole table and re-reads every Collection and Article
  through the repositories, resolving each Article's chain and effective audience, in a single
  transaction. The index is derived and disposable (ADR 0003/0004, 0012): a full rebuild is how
  staleness is cleared in v1.
- ``index_article`` / ``index_subtree`` are the INCREMENTAL edges (ADR 0014, Part 4.2):
  performance sugar over the same ``build_row`` + fail-closed code path. Both take a REFERENCE
  (a ulid) and re-read canonical truth at execution — never a payload — so a stale job simply
  recomputes the current truth. ``index_article`` upserts one row (or deletes it when the ulid
  is gone from canonical); ``index_subtree`` recomputes every Article whose resolved chain
  passes through the named Collection (audience/parent edits move descendants).

Fail-closed is the security invariant (ADR 0012). Any ``DomainError`` resolving an Article — a
dangling ``collection_id``, a broken tree, a mis-bound chain — does NOT drop the Article and does
NOT guess a visibility. It writes an archivist-only row (``archivist_only=True``, ``tier=None``,
no groups) that still carries the Article's text, so an Archivist can search for it and fix the
source, and records the ulid in the ``RebuildReport`` for the caller/CLI to surface.

Writer coordination (ADR 0014 v2). Every index writer — ``rebuild``, ``index_article``,
``index_subtree`` — takes the SAME Postgres transaction-scoped advisory lock
(``pg_advisory_xact_lock`` on ``_INDEX_WRITER_LOCK_KEY``) inside its transaction, so a sync
upsert can never interleave with a running rebuild and lose to the rebuild's older file snapshot.
One lock, one rule, no lost updates between index writers. Canonical-file writers are governed by
ADR 0013's ``WRITER_LOCK``, not this lock.
"""

from dataclasses import dataclass

from django.db import connection, transaction

from bundesarchiv.domain.audience import ARCHIVIST_ONLY, effective_audience
from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import Article, Collection, Ulid
from bundesarchiv.index.models import _ARCHIVIST_TEXT_SOURCES, ArticleIndex
from bundesarchiv.index.scope import ScopeColumns, _scope_columns
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.errors import NotFound
from bundesarchiv.persistence.objectstore import ObjectStore
from bundesarchiv.persistence.repository import ArticleRepository

# Bump on any ADR 0011 config change (FTS config, collation, wrapper functions). The Part 4
# background worker rebuilds when a row's stored config_version does not match this value.
CONFIG_VERSION = 1

# THE ONE project-wide index-writer advisory-lock key (ADR 0014 v2). Every index writer takes
# ``pg_advisory_xact_lock(_INDEX_WRITER_LOCK_KEY)`` inside its transaction so writes serialize and
# a rebuild can never clobber a concurrent incremental upsert. Chosen arbitrary-but-fixed; it must
# never change, and no other advisory lock in the system may reuse this key.
_INDEX_WRITER_LOCK_KEY = 0x42554E44  # "BUND" — stable, documented, index-writer-only


def _take_writer_lock() -> None:
    """Acquire the transaction-scoped index-writer advisory lock. MUST be called first inside
    every index writer's ``transaction.atomic()`` block; it releases automatically at commit or
    rollback (``pg_advisory_xact_lock``), so no explicit unlock is ever needed."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_INDEX_WRITER_LOCK_KEY])


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


def _row_for(
    article: Article, lookup: dict[Ulid, Collection], *, cap_year: int
) -> tuple[dict[str, object], bool]:
    """Compute one Article's row + whether it failed closed, from a Collection lookup. The single
    resolve-chain-then-build-or-fail-closed decision shared by ``rebuild`` and the incremental
    writers, so all three keep identical fail-closed semantics (ADR 0012/0014)."""
    try:
        chain = resolve_chain(article.collection_id, lookup)
        return build_row(article, chain, cap_year=cap_year), False
    except DomainError:
        return _fail_closed_row(article, cap_year=cap_year), True


def rebuild(store: ObjectStore) -> RebuildReport:
    """Wipe and rebuild the whole ``ArticleIndex`` from the files-canonical core in one
    transaction. Loads every Collection and Article through the repositories, resolves each
    Article's chain + effective audience, and writes one row per Article. A ``DomainError`` for
    any Article yields a fail-closed archivist-only row (still indexed, counted in the report)
    rather than dropping it or guessing visibility. Idempotent: the leading wipe means a repeat
    rebuild produces the same rows with no duplicates.

    Takes the shared index-writer advisory lock (ADR 0014 v2) so a concurrent ``index_article`` /
    ``index_subtree`` cannot interleave and lose to this rebuild's older file snapshot.
    """
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)

    lookup: dict[Ulid, Collection] = {c.ulid: c for c in collections.load_all()}
    cap_year = _current_year()

    rows: list[dict[str, object]] = []
    failed: list[str] = []
    for ulid in articles.list_ulids():
        article = articles.load(ulid).article
        row, failed_closed = _row_for(article, lookup, cap_year=cap_year)
        rows.append(row)
        if failed_closed:
            failed.append(article.ulid)

    with transaction.atomic():
        _take_writer_lock()
        ArticleIndex.objects.all().delete()
        ArticleIndex.objects.bulk_create(ArticleIndex(**row) for row in rows)

    return RebuildReport(indexed=len(rows), failed_closed=tuple(failed))


def index_article(store: ObjectStore, ulid: Ulid) -> None:
    """Incrementally reindex ONE Article by reference (ADR 0014): re-read canonical truth for
    ``ulid`` and upsert its single row, or DELETE the row when the ulid is gone from canonical.

    Reference semantics — the caller passes only a ulid, never a payload, so a stale enqueued job
    recomputes whatever canonical says NOW. Routes through the same ``build_row`` + fail-closed
    branch as ``rebuild`` (a broken chain becomes an archivist-only row). Idempotent. Takes the
    shared index-writer advisory lock inside its transaction.
    """
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    cap_year = _current_year()

    try:
        article = articles.load(ulid).article
    except NotFound:
        with transaction.atomic():
            _take_writer_lock()
            ArticleIndex.objects.filter(ulid=ulid).delete()  # gone from canonical -> drop the row
        return

    lookup: dict[Ulid, Collection] = {c.ulid: c for c in collections.load_all()}
    row, _failed = _row_for(article, lookup, cap_year=cap_year)
    with transaction.atomic():
        _take_writer_lock()
        ArticleIndex.objects.update_or_create(ulid=ulid, defaults=row)


def index_subtree(store: ObjectStore, collection_ulid: Ulid) -> None:
    """Incrementally reindex every Article in the subtree rooted at ``collection_ulid`` (ADR 0014).

    An audience or parent edit on a Collection changes the effective audience of every descendant
    Article, so the whole subtree must be recomputed. Reference semantics: re-read ALL canonical
    Collections + Articles, then upsert each Article whose resolved chain passes through
    ``collection_ulid``. An Article whose chain cannot resolve is upserted as a fail-closed row
    IFF its own ``collection_id`` is the target (a broken chain has no resolvable ancestry to test
    against, so only the directly-targeted orphan is touched — non-descendants stay untouched).
    Idempotent; takes the shared index-writer advisory lock inside its transaction.
    """
    collections = CollectionRepository(store)
    articles = ArticleRepository(store)
    lookup: dict[Ulid, Collection] = {c.ulid: c for c in collections.load_all()}
    cap_year = _current_year()

    updates: list[tuple[str, dict[str, object]]] = []
    for ulid in articles.list_ulids():
        article = articles.load(ulid).article
        if not _in_subtree(article, collection_ulid, lookup):
            continue
        row, _failed = _row_for(article, lookup, cap_year=cap_year)
        updates.append((article.ulid, row))

    with transaction.atomic():
        _take_writer_lock()
        for ulid, row in updates:
            ArticleIndex.objects.update_or_create(ulid=ulid, defaults=row)


def _in_subtree(article: Article, collection_ulid: Ulid, lookup: dict[Ulid, Collection]) -> bool:
    """True iff ``article``'s resolved Collection chain passes through ``collection_ulid`` — i.e.
    the Article sits in that Collection's subtree. A chain that cannot resolve counts only when the
    Article's own ``collection_id`` IS the target (an orphan directly under the edited Collection);
    otherwise a broken chain is not a descendant and is left untouched."""
    try:
        chain = resolve_chain(article.collection_id, lookup)
    except DomainError:
        return article.collection_id == collection_ulid
    return any(c.ulid == collection_ulid for c in chain.collections)


def _current_year() -> int:
    """The current calendar year, read here (not in ``build_row``) so ``build_row`` stays pure.
    Imported locally so the pure ``build_row`` path never depends on the clock module."""
    import datetime

    return datetime.date.today().year
