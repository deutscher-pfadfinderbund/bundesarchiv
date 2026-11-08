# Search: a derived index with field-floor-aware audience scoping

Status: Accepted (2026-06-26). Amended by 0011 (2026-07-04), 0023 (2026-10-11).

Search is served by the **derived index** (rebuilt from `README.md`). **It indexes metadata** — title, description, creator, subject_place, tags, signature, type labels — with **German full-text** (umlaut folding, stemming) plus **facets**: Collection (tree drill-down), media-type, document-type, tags, EDTF date range/decade, and numeric-aware signature sort.

Every query is scoped by the one **effective-audience function**, and is additionally **field-floor-aware**: a viewer must not be able to *match* an Article through a field above their floor (e.g. a Member must not find an Article via its Archivist-only `physical_location`, or they could infer hidden information). Indexed text is therefore partitioned by field-floor, and a query only searches the fields the viewer is allowed to see.

PDF page text is searched (0023); OCR of scans stays deferred.

## Consequences

- Field-floor partitioning is a **leak-prevention requirement**, not an optimization — it must be tested per viewer tier.
- **Index engine = PostgreSQL** — `public.bundesarchiv_german`: `unaccent` + `german_stem`, and ICU numeric collation (`de-u-kn-true`) for `ref_code` sort. Because the index is derived and disposable, the engine stays swappable (e.g. add Meilisearch later if search UX needs typo-tolerance).

**Update 2026-08-30 — "disposable" means the index, not the database.** Every
citation of this ADR ("the index is disposable") is about the derived
search-index tables, which `manage.py rebuild_index` recreates from the files at any time.
The Postgres *instance* around them is not disposable: it also holds admin data
— worker jobs today, an audit trail or capability tokens later — which nothing
can rebuild from the files. Only the archive files (media + Markdown) must
survive total loss (owner, 2026-08-30). Rebuilding the index is routine;
dropping the database is an emergency measure and takes everything else with it.
