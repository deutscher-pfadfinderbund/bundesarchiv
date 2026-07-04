# Part 3 — Derived Postgres Index + German FTS: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A test-proven, viewer-scoped search over a derived, disposable Postgres index
with German full-text search — no views, no URLs.

**Architecture:** Django 6 arrives as an adapter inside `src/bundesarchiv/index/` (a deep
module: public interface is `rebuild()` + `search()`, everything else private). The
indexer materializes the output of the pure `effective_audience` function into scope
columns; SQL only ever *compares* that stored scope to the viewer — it never reimplements
the cascade. Indexed text is partitioned into two tsvectors (general vs archivist-only
fields). Canonical data stays in README files; every index row is rebuildable.

**Tech Stack:** Python 3.14, Django 6.x, psycopg 3, PostgreSQL 18 (docker compose,
custom image with German Hunspell), pytest + pytest-django.

## Global Constraints

Copied from repo conventions + the approved design. Every task's requirements include these.

- Python ≥ 3.14. NO `from __future__ import annotations` (PEP 649). `except A, B:`
  paren-free is valid — do not "fix". PEP 695 `type` aliases + `assert_never` exhaustiveness.
- Import direction: `domain/` imports no internal packages and no Django;
  `persistence/` imports only `domain`; `index/` may import both. Nothing imports `index`.
  `django` may not be imported outside `src/bundesarchiv/index/`. (Task 6 adds the test
  that enforces this.)
- Fail closed: any DomainError in a visibility path → least visibility. Only the typed
  error hierarchy crosses seams (ArchiveError in persistence, DomainError in domain).
- Frozen dataclasses; functional style (comprehensions over mutating loops).
- The index is derived and disposable. Postgres never validates domain truths (no CHECK
  constraints re-stating domain invariants). No business logic on Django models.
- Scoping logic exists exactly twice, adjacently: `_scope_columns()` (write side) and
  `_viewer_scope()` (read side), both in `src/bundesarchiv/index/scope.py`. Tier
  comparisons anywhere else are a defect.
- Facet counts and result totals are computed over the viewer-scoped row set only.
- `search()` returns frozen dataclasses; no QuerySets/model instances cross the interface.
- Django settings stay minimal: database, our app, `django.contrib.postgres`. Nothing else.
- TDD per task. Self-run `uv run ruff check`, `uv run ruff format`, `uv run mypy`,
  `uv run pytest` before every commit. Conventional Commits.
- No mocking except at genuine boundaries. Index tests run against real Postgres.
- `tests/test_data/archive_items.txt` is multi-MB: NEVER read it fully. Head only
  (≤ 50 lines), or stream line-by-line with an early break.
- German UI strings / English code identifiers (see `CONTEXT.md`).

## File Structure

```
docker/postgres/Dockerfile            # postgres:18 + German hunspell dicts in tsearch_data
docker-compose.yml                    # postgres service (dev + tests)
src/bundesarchiv/domain/edtf.py       # EdtfDate value object + bounds (pure)
src/bundesarchiv/domain/models.py     # + Article.date/creator/subject_place
src/bundesarchiv/persistence/collection_readme.py  # Collection README codec
src/bundesarchiv/persistence/collections.py        # CollectionRepository
src/bundesarchiv/index/__init__.py    # exports: rebuild, search, SearchPage, SearchHit, SearchFilters
src/bundesarchiv/index/settings.py    # minimal Django settings
src/bundesarchiv/index/apps.py        # app config
src/bundesarchiv/index/models.py      # ArticleIndex (private — underscore not needed; not exported)
src/bundesarchiv/index/migrations/    # 0001 extensions/dict/collation, 0002 table
src/bundesarchiv/index/scope.py       # _scope_columns + _viewer_scope (THE seam)
src/bundesarchiv/index/indexer.py     # pure row builder + rebuild()
src/bundesarchiv/index/query.py       # search() + facet counts
manage.py                             # migrations only
tests/domain/test_edtf.py
tests/persistence/test_collection_readme.py, test_collections.py
tests/index/  (conftest.py, test_architecture.py, test_fts_german.py,
               test_indexer.py, test_search.py, test_leaks.py, test_equivalence.py)
docs/adr/0010-collections-persistence.md
docs/adr/0011-german-fts-config.md    # written by the spike, with measurements
docs/adr/0012-materialized-audience-scope.md
```

---

### Task 1: EDTF value object (domain)

**Files:** Create `src/bundesarchiv/domain/edtf.py`, `tests/domain/test_edtf.py`.

**Interfaces — Produces:**
```python
@dataclass(frozen=True, slots=True)
class EdtfDate:
    """Validated EDTF (Level 0/1 subset). Raises ValueError on invalid input."""
    value: str
    def bounds(self) -> tuple[datetime.date, datetime.date | None]: ...
    def decades(self, *, cap_year: int) -> tuple[int, ...]:  # e.g. (1960, 1970)
```

Supported subset (reject everything else, `ValueError` with the offending value):
`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, uncertain/approximate qualifiers `?` `~` `%` (suffix),
unspecified digits `197X`/`19XX`, intervals `A/B` incl. open ends `A/..` and `../B`,
seasons `YYYY-21..24`. Qualifiers do not change bounds (uncertainty is display-level).
Open upper end → `bounds()[1] is None`; `decades(cap_year=...)` caps there.

**Implementation decision (in-task gate):** first try `python-edtf` from PyPI. Adopt only
if: maintained, typed or stub-able under `mypy --strict`, works on 3.14. Otherwise
hand-roll the subset above (a small recursive-descent or regex table is fine). Record the
choice in the module docstring.

- [ ] Failing tests: table-driven over the subset — valid → `(value, earliest, latest, decades)`
      rows; invalid (`"garbage"`, `"19"`, `"1970-13"`, `"1970/"`, `""`) → `pytest.raises(ValueError)`.
      Include: `"1968/1973~"` → 1968-01-01..1973-12-31, decades (1960, 1970);
      `"197X"` → 1970-01-01..1979-12-31; `"1964/.."` → open end, decades capped;
      `"2001-22"` (summer) → 2001-06-01..2001-08-31.
- [ ] Implement. Gates green. Commit `feat(domain): EDTF Level 0/1 value object`.

### Task 2: Article gains date, creator, subject_place

**Files:** Modify `src/bundesarchiv/domain/models.py` (Article), `src/bundesarchiv/domain/factory.py`
(`create_article`), `src/bundesarchiv/persistence/readme.py` (codec), respective tests.

**Interfaces — Produces:** `Article.date: EdtfDate | None = None`,
`Article.creator: str | None = None`, `Article.subject_place: str | None = None`.
Wire keys `date`, `creator`, `subject_place` — optional; absent/None → omitted on write,
missing → None on read (same convention as `audience`). Invalid EDTF on the wire →
`ArchiveError` (codec wraps ValueError, same as Audience invariants).
All three are member-visible: they must NOT enter `ARCHIVIST_ONLY_FIELDS` — extend the
existing floor test to pin exactly `{"physical_location", "custom"}`.
`custom` reserved-key collision check in `Article.__post_init__` picks up the new field
names automatically (verify with a test: `custom=(("creator", "x"),)` → ValueError).

- [ ] Failing tests: codec round-trip with all three set; README without the keys → None;
      `date: not-a-date` in README → ArchiveError; reserved-key test above.
- [ ] Implement. Gates green. Commit `feat(domain,persistence): Article date (EDTF), creator, subject_place`.

### Task 3: Collections persistence + ADR 0010

**Files:** Create `src/bundesarchiv/persistence/collection_readme.py`,
`src/bundesarchiv/persistence/collections.py`, `docs/adr/0010-collections-persistence.md`,
tests. Read `src/bundesarchiv/persistence/readme.py` + `articles.py` first and mirror
their structure, docstring style, and error handling exactly.

**Interfaces — Produces:**
```python
# collection_readme.py — same codec pattern as readme.py
def encode_collection(collection: Collection) -> str: ...
def decode_collection(text: str, *, ulid: Ulid) -> Collection: ...

# collections.py
class CollectionRepository:
    def __init__(self, store: ObjectStore) -> None: ...
    def save(self, collection: Collection) -> None: ...
    def load(self, ulid: Ulid) -> Collection:            # ArchiveError.NotFound if absent
    def load_all(self) -> tuple[Collection, ...]: ...    # for tree assembly / rebuild
    def hard_delete(self, ulid: Ulid) -> None: ...
```
Key layout: `collections/<ulid>/README.md` (mirrors `articles/<ulid>/README.md`).
Wire keys: `name` (required), `parent_id` (optional), `audience` (optional, identical
convention to Article's). Dangling `parent_id` is NOT the repository's problem —
`resolve_chain` already fails closed (`BrokenCollectionTree`); the repository only
guarantees well-formed single Collections.

ADR 0010 records: per-Collection README tree chosen over a single collections file
(consistency with the Article pattern, WebDAV-browsable, per-node atomic writes;
single-file atomicity rejected as moot under single-writer v1).

- [ ] Failing tests: codec round-trip (with/without parent_id, with/without audience,
      invalid audience mapping → ArchiveError); repository CRUD against InMemory AND
      LocalFs stores (reuse the existing conformance-suite pattern); `load_all` returns
      every saved Collection; `load` of missing ulid → NotFound.
- [ ] Implement + ADR. Gates green. Commit `feat(persistence): Collection README codec + repository (ADR 0010)`.

### Task 4: Postgres image + compose + Django scaffold

**Files:** Create `docker/postgres/Dockerfile`, `docker-compose.yml`,
`src/bundesarchiv/index/{__init__,settings,apps}.py`, `manage.py`,
`tests/index/conftest.py`, `tests/index/test_architecture.py`.
Modify `pyproject.toml` (deps + pytest-django config), `README.md` (dev setup: one
paragraph — `docker compose up -d`, `uv run manage.py migrate`).

Dockerfile: `FROM postgres:18` + install `hunspell-de-de` (Debian package), copy/convert
the `.aff`/`.dic` files to `$(pg_config --sharedir)/tsearch_data/de_de.{affix,dict}`
(UTF-8; `iconv` if the package ships ISO-8859-1). Compose: single `postgres` service,
port 5433 (avoid host clashes), env `POSTGRES_DB=bundesarchiv`, healthcheck.
Settings: `DATABASES` from env (`BUNDESARCHIV_PG_DSN`, default
`postgresql://postgres:postgres@localhost:5433/bundesarchiv`), `INSTALLED_APPS =
["django.contrib.postgres", "bundesarchiv.index"]`, nothing else.
Dependencies: `django>=6`, `psycopg[binary]>=3.2`; dev: `pytest-django`.
Verify Django 6.x supports Python 3.14 (release notes); if only 6.x.y does, pin that floor.

`tests/index/conftest.py`: pytest-django wiring (`DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings`).
Index tests REQUIRE Postgres: if the DB is unreachable, they must FAIL with a clear
message ("docker compose up -d"), not skip. Escape hatch: `BUNDESARCHIV_SKIP_PG=1`
skips the whole `tests/index/` directory explicitly (for domain-only work).

`test_architecture.py` (runs without DB): walk `src/bundesarchiv/{domain,persistence}`
ASTs; assert no `import django...` / `from django...` and no `bundesarchiv.index`
imports. Assert `bundesarchiv.index.__init__.__all__ == ["rebuild", "search",
"SearchPage", "SearchHit", "SearchFilters"]` (stub the names now; filled by Tasks 6–8).

- [ ] Tests first where possible (architecture test); compose up; `manage.py check` clean.
- [ ] Gates green (index tests: only architecture + a trivial DB connectivity test).
      Commit `feat(index): Django 6 scaffold, Postgres 18 image with German hunspell`.

### Task 5: FTS gating spike → ADR 0011  **[DECISION GATE]**

**Files:** Create `docs/adr/0011-german-fts-config.md`, `tests/index/test_fts_german.py`.
No production code. Work directly against the compose Postgres (psql / psycopg).

Questions the spike MUST answer with measurements (record all numbers in the ADR):
1. Does the baked de_de ispell dictionary compound-split? Test `ts_lexize` on ≥ 15 real
   compounds pulled from the corpus head (`head -50 tests/test_data/archive_items.txt`;
   e.g. Fahrtenbericht, Bundeslager, Gruppenstunde…). If stock de_de does not split,
   evaluate: (a) a compound-enabled hunspell variant, (b) accepting no decomposition in
   v1 (documented consequence: whole-word matching only + german_stem), (c) prefix
   matching (`:*`) as a UX mitigation for Part 4. Choose and record.
2. Mapping order: prove with `ts_debug` that the dictionary sees umlauts BEFORE any
   unaccent folding (`fährt` must reach the ispell dict as `fährt`). Decide unaccent's
   place: separate folded lexeme, last-resort mapping, or dropped entirely.
3. Produce the final `CREATE TEXT SEARCH CONFIGURATION bundesarchiv_german ...` SQL
   (dictionary chain per token type) — this exact SQL is consumed verbatim by Task 6.
4. Sanity-check ICU collation: `CREATE COLLATION de_numeric (provider = icu, locale =
   'de-u-kn-true');` then `ORDER BY ref_code COLLATE de_numeric` over
   `('B 2', 'B 10', 'B 1', 'Ä 3')` → expect `Ä 3, B 1, B 2, B 10`.

Deliverable: ADR 0011 with measurements + decisions, plus `test_fts_german.py` pinning
the chosen behavior as executable spec (lexize/tsquery assertions per decision — these
run against the Task 6 migration and stay forever as regression guards; mark them
`pytest.mark.skip` until Task 6 lands, with reason "config migration lands in Task 6").

- [ ] Spike, measure, write ADR + pinned tests. Commit `docs(adr): 0011 German FTS config (spike measurements)`.

### Task 6: Index schema — migrations + model

**Files:** Create `src/bundesarchiv/index/models.py`,
`src/bundesarchiv/index/migrations/0001_search_infrastructure.py` (RunSQL: `CREATE
EXTENSION IF NOT EXISTS unaccent;`, the exact ADR 0011 configuration SQL, the
`de_numeric` collation), `0002_articleindex.py`. Unskip Task 5's pinned FTS tests.

Model (private; NOT exported from `bundesarchiv.index`):
```python
class ArticleIndex(models.Model):
    ulid = models.TextField(primary_key=True)
    title = models.TextField()
    body = models.TextField(blank=True, default="")
    creator = models.TextField(null=True)
    subject_place = models.TextField(null=True)
    ref_code = models.TextField(null=True)
    media_type = models.TextField(null=True)
    document_type = models.TextField(null=True)
    tags = ArrayField(models.TextField(), default=list)
    archivist_text = models.TextField(blank=True, default="")   # physical_location + custom values (indexer-built)
    date_edtf = models.TextField(null=True)
    date_earliest = models.DateField(null=True)
    date_latest = models.DateField(null=True)                   # None = open end
    decades = ArrayField(models.IntegerField(), default=list)
    collection_id = models.TextField()
    collection_ancestors = ArrayField(models.TextField(), default=list)  # leaf→root, incl. own collection
    archivist_only = models.BooleanField()
    tier = models.TextField(null=True)        # "PUBLIC" | "MEMBERS" | "GROUPS"; None iff archivist_only
    groups = ArrayField(models.TextField(), default=list)
    config_version = models.IntegerField()    # bump when FTS config changes (see indexer.CONFIG_VERSION)
    general_tsv = GeneratedField(...)         # weighted, see expression below
    archivist_tsv = GeneratedField(...)
```
`general_tsv` expression (via `SearchVector` combos or RunSQL if the ORM expression
fights back — RunSQL is acceptable, the model then declares the field with
`db_persist=True` and a matching expression):
`setweight(to_tsvector('bundesarchiv_german', coalesce(title,'')), 'A') ||
 setweight(to_tsvector('bundesarchiv_german', coalesce(ref_code,'') || ' ' || array_to_string(tags,' ')), 'B') ||
 setweight(to_tsvector('bundesarchiv_german', coalesce(creator,'') || ' ' || coalesce(subject_place,'') || ' ' || coalesce(media_type,'') || ' ' || coalesce(document_type,'')), 'C') ||
 setweight(to_tsvector('bundesarchiv_german', coalesce(body,'')), 'D')`
`archivist_tsv`: `to_tsvector('bundesarchiv_german', archivist_text)`.
GIN indexes on both tsvectors; btree on `collection_id`, `date_earliest`.

Floor-partition drift guard (import-time, in `indexer.py` but test it here):
```python
_ARCHIVIST_TEXT_SOURCES: frozenset[str] = frozenset({"physical_location", "custom"})
assert _ARCHIVIST_TEXT_SOURCES == ARCHIVIST_ONLY_FIELDS, (
    "index archivist partition drifted from domain floor"
)
```
(`media` carries no indexable text; if ARCHIVIST_ONLY_FIELDS ever grows, this assert
forces the index to follow.)

- [ ] Failing tests: migrations apply on a fresh DB (pytest-django does this);
      Task 5's unskipped FTS tests pass against `bundesarchiv_german`; collation test
      (insert 4 rows, order by `Collate("ref_code", "de_numeric")`); generated columns
      populate on INSERT (raw ORM create → tsv non-empty).
- [ ] Implement. Gates green. Commit `feat(index): index schema, German FTS config, ICU collation (ADR 0011)`.

### Task 7: Scope seam + indexer + ADR 0012

**Files:** Create `src/bundesarchiv/index/scope.py`, `src/bundesarchiv/index/indexer.py`,
`docs/adr/0012-materialized-audience-scope.md`, `tests/index/test_indexer.py`.

`scope.py` — BOTH halves of the seam, adjacent (see Global Constraints):
```python
@dataclass(frozen=True, slots=True)
class ScopeColumns:
    archivist_only: bool
    tier: str | None          # None iff archivist_only
    groups: tuple[str, ...]

def _scope_columns(effective: EffectiveAudience) -> ScopeColumns:
    match effective:
        case ArchivistOnly():
            return ScopeColumns(archivist_only=True, tier=None, groups=())
        case Audience(tier=tier, groups=groups):
            return ScopeColumns(archivist_only=False, tier=tier.name, groups=groups)
        case _:
            assert_never(effective)

def _viewer_scope(viewer: Viewer) -> Q:
    """READ-side mirror of _scope_columns — the ONLY place viewer meets SQL.
    Must stay equivalent to domain.access.can_view; test_equivalence.py pins this."""
    match viewer:
        case Archivist():
            return Q()
        case Member(groups=groups):
            return Q(archivist_only=False) & (
                Q(tier__in=("PUBLIC", "MEMBERS"))
                | (Q(tier="GROUPS") & Q(groups__overlap=list(groups)))
            )
        case Public():
            return Q(archivist_only=False, tier="PUBLIC")
        case _:
            assert_never(viewer)
```

`indexer.py`:
```python
CONFIG_VERSION = 1  # bump on any ADR 0011 config change; worker (Part 4) rebuilds on mismatch

def build_row(article: Article, chain: ResolvedChain) -> dict[str, object]:
    """Pure: article + resolved chain -> column dict. No IO, no Django imports needed
    beyond types; testable without a database."""

def rebuild(store: ObjectStore) -> RebuildReport:
    """Wipe + rebuild inside one transaction. Loads Collections via CollectionRepository,
    Articles via ArticleRepository. resolve_chain / effective_audience failure for an
    article -> fail-closed row: archivist_only=True, scope groups empty, still indexed
    (title etc.) so an Archivist can find and fix it; counted in the report."""

@dataclass(frozen=True, slots=True)
class RebuildReport:
    indexed: int
    failed_closed: tuple[str, ...]   # ulids indexed fail-closed, for the caller/CLI to surface
```
`build_row` details: `archivist_text = " ".join([physical_location or "", *custom values])`
(values only — keys are structure, not prose); date columns from `article.date.bounds()` /
`.decades(cap_year=<current year via parameter>)` — `rebuild` passes `cap_year`,
`build_row` stays pure; `collection_ancestors` from the resolved chain (leaf→root ulids).
ADR 0012 records: materialize-at-index-time over live-Python-filter and SQL-cascade
(comparison-not-reimplementation, staleness owned by rebuild in v1, Part 4 gate noted).

- [ ] Failing tests: `build_row` pure cases (explicit audience / inherit / groups /
      unpublished→ArchivistOnly / date bounds / archivist_text content / ancestors);
      `rebuild` end-to-end against InMemory store + real PG (3 collections nested, 5
      articles incl. one with dangling collection_id → fail-closed row + report entry);
      rebuild twice → idempotent (row count stable).
- [ ] Implement + ADR. Gates green. Commit `feat(index): scope seam + fail-closed rebuild (ADR 0012)`.

### Task 8: Query layer — search(), facets, sort, pagination

**Files:** Create `src/bundesarchiv/index/query.py`, `tests/index/test_search.py`.
Finalize `index/__init__.py` exports.

**Interfaces — Produces:**
```python
@dataclass(frozen=True, slots=True)
class SearchFilters:
    collection: Ulid | None = None            # matches via collection_ancestors (subtree)
    media_type: str | None = None
    document_type: str | None = None
    tag: str | None = None
    decade: int | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None

@dataclass(frozen=True, slots=True)
class SearchHit:
    ulid: str
    title: str
    ref_code: str | None
    date_edtf: str | None
    media_type: str | None
    document_type: str | None
    # floor-safe by construction: no physical_location, no custom, no archivist_text

@dataclass(frozen=True, slots=True)
class FacetCount:
    value: str
    count: int

@dataclass(frozen=True, slots=True)
class SearchPage:
    hits: tuple[SearchHit, ...]
    total: int
    facets: Mapping[str, tuple[FacetCount, ...]]  # keys: collection, media_type, document_type, tags, decades

type SortOrder = Literal["relevance", "ref_code", "date", "title"]

def search(viewer: Viewer, *, text: str | None = None,
           filters: SearchFilters | None = None, sort: SortOrder = "relevance",
           page: int = 1, page_size: int = 50) -> SearchPage: ...
```
Implementation requirements:
- Base queryset: `ArticleIndex.objects.filter(_viewer_scope(viewer))` — FIRST, always.
  Text, filters, facets, total all derive from that scoped queryset.
- Text: `websearch_to_tsquery('bundesarchiv_german', text)`; match `general_tsv`, OR
  `archivist_tsv` too iff `isinstance(viewer, Archivist)` (the match arms in
  `_viewer_scope` don't carry this — keep the tsvector choice in `query.py`, one
  `match viewer` with `assert_never`). Relevance = `ts_rank` over the matched vector(s).
- `sort="ref_code"` → `Collate("ref_code", "de_numeric")` ascending, nulls last;
  `"date"` → `date_earliest` ascending, nulls last; `"title"` → title, de collation.
- Facet counts: one aggregate query per facet over the scoped+filtered set (standard
  faceting: each facet's own filter excluded from its count query); tags/decades via
  `unnest`. `total` = scoped+filtered count before pagination.
- No `ts_headline` in v1 (Part 4 decides presentation).

- [ ] Failing tests (fixtures: 3-level collection tree, ~12 articles spanning tiers,
      groups, lifecycles, dates, tags — build via `rebuild` from an InMemory store, one
      fixture module reused by Task 9): text match (compound/stem per ADR 0011 pinned
      behavior), filters incl. subtree collection filter, each sort order (ref_code
      numeric: B 1 < B 2 < B 10), pagination window + total, facet counts per tier,
      empty query → filters-only browse, `page_size` bounds.
- [ ] Implement. Gates green. Commit `feat(index): viewer-scoped search with facets + German FTS`.

### Task 9: Leak tests + SQL ≡ can_view equivalence  **[THE §11 GUARD]**

**Files:** Create `tests/index/test_leaks.py`, `tests/index/test_equivalence.py`.
Pure test task — any production change it forces goes back through a fix cycle.

`test_leaks.py` — per-tier negative assertions (Public, Member without groups, Member
with wrong group, Member with right group, Archivist):
- A term occurring ONLY in `physical_location` / a `custom` value of an otherwise
  member-visible article: non-Archivist search → zero hits; Archivist → hit.
- Draft/unlisted-lifecycle article: invisible to every non-Archivist through every path
  (text, filters, facets, total).
- GROUPS article: found only with an overlapping group.
- Facet counts + totals per tier equal the manually-computed can_view-visible counts —
  no existence leak via aggregates.
- Fail-closed rows (dangling collection) invisible to non-Archivists.
- `SearchHit` shape: assert dataclass fields exclude floored content (static assert on
  `SearchHit.__dataclass_fields__`).

`test_equivalence.py` — property-style grid, not hypothesis: enumerate all combinations of
{explicit PUBLIC, explicit MEMBERS, explicit GROUPS(a), explicit GROUPS(a,b), inherit} ×
{parent explicit PUBLIC/MEMBERS/GROUPS(b)/inherit} × {DRAFT, PUBLISHED} (≈ 40 articles,
one nested collection pair per parent-audience case), rebuild once, then for each viewer in
{Public, Member(), Member(a), Member(b), Member(a,b), Archivist}:
`set(search(viewer, page_size=1000).hits ulids) == {a.ulid for a in articles if can_view(viewer, a, chain(a))}`.
Any mismatch prints the offending (article, viewer) pair.

- [ ] Write tests; expect green if Tasks 7–8 are honest; any red = real defect, fix via
      review loop. Commit `test(index): per-tier leak tests + SQL≡can_view equivalence grid`.

### Task 10: Migration feasibility memo (spike)

**Files:** Create `docs/plans/migration-feasibility.md`. No production code.
Data: `tests/test_data/archive_items.txt` — psql table dump, multi-MB. Read the header
+ ~10 data rows ONLY (head/stream, never the full file).

Hand-map ~10 representative rows onto the new model: which old columns land where
(`author`→`creator`, `place`→`subject_place`, `signature`→`ref_code`, `year/date/day/month`
→ EDTF composition, `keywords`→`tags`, `doctype`/`document_type_id`→`document_type`,
`medartanalog`→`media_type`, `location`→`physical_location`, `owner`/`source`/
`crossreference`/`amount`/`notes`→`custom` or body). Flag anything unrepresentable
(multi-valued fields? encodings? date oddities like month-without-day) and whether it
needs a pre-Part-7 model change or just import logic. Also: pull 30–50 German
titles/descriptions into the memo as the reference corpus snapshot for ADR 0011's
measurements (if Task 5 hasn't already).

- [ ] Write memo. Commit `docs(plans): old-dataset migration feasibility memo`.

### Task 11: Docs sync + handoff

**Files:** Modify `docs/design/bundesarchiv-v1.md` (§5: captions live in the body;
provenance + misc old-system columns via `custom`; creator/subject_place/date now real
fields), `CONTEXT.md` (glossary: EDTF, Index, Scope columns — German UI terms included),
`HANDOFF.md.local` (Part 3 state). Verify ADR 0003's field list now matches reality;
amend its v1 notes if the FTS spike changed the compound-splitting story.

- [ ] Edit, gates green (docs don't break gates; run anyway). Commit
      `docs: sync design/context with Part 3 reality`.

---

## Execution notes (for the controller, not the implementers)

- Sequence is linear except: Task 5 (spike) can start once Task 4's compose is up,
  in parallel with Task 3; Task 10 is independent after Task 2 (needs the field
  names settled) — schedule it whenever a slot is free.
- Task 5 and Task 10 are decision gates: their outputs (ADR 0011 SQL, feasibility memo)
  feed Tasks 6 and the Part 7 roadmap — the controller reads both before dispatching Task 6.
- Model guidance per subagent-driven-development: Tasks 1–3, 11 standard tier;
  Task 5, 7, 9 need judgment (standard/most-capable reviewer); Tasks 6, 8 standard with
  careful review; Task 10 cheap tier.
- Every task's reviewer gets the Global Constraints block verbatim.
