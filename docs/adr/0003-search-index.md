# Search: a derived index with field-floor-aware audience scoping

Search is served by the **derived index** (rebuilt from `README.md`). **v1 indexes metadata only** — title, description, creator, subject_place, tags, signature, type labels — with **German full-text** (umlaut folding, stemming) plus **facets**: Collection (tree drill-down), media-type, document-type, tags, EDTF date range/decade, and numeric-aware signature sort.

Every query is scoped by the one **effective-audience function**, and is additionally **field-floor-aware**: a viewer must not be able to *match* an Article through a field above their floor (e.g. a Member must not find an Article via its Archivist-only `physical_location`, or they could infer hidden information). Indexed text is therefore partitioned by field-floor, and a query only searches the fields the viewer is allowed to see.

**Full-content search** (OCR of scanned images and extracted PDF text, in German) is **deferred**; the index shape keeps room for a future "document body" field.

## Consequences

- Field-floor partitioning is a **leak-prevention requirement**, not an optimization — it must be tested per viewer tier.
- **Index engine = PostgreSQL** — `to_tsvector('german')` + `unaccent` + a German Hunspell dictionary (compound splitting, e.g. *Fahrtenbericht* → *Fahrt*), and ICU numeric collation (`de-u-kn-true`) for `ref_code` sort. Because the index is derived and disposable, the engine stays swappable (e.g. add Meilisearch later if search UX needs typo-tolerance).

**Update 2026-07-04:** The Hunspell ispell dict splits **0 / 28** real compounds (Postgres implements only the legacy `compoundwords controlled` mechanism; the baked `hunspell-de-de` uses modern `COMPOUNDBEGIN/END` directives). v1 ships `unaccent + german_stem` only — no compound decomposition. See ADR 0011 for measurements and the final SQL config.
