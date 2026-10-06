# domain — package map

Law: pure core. No IO, no Django, no settings. Errors are the typed `DomainError` hierarchy.
`effective_audience` is the ONE visibility resolver (ADR 0001) — never recompute its answer ad hoc.

- `models.py` — the domain shapes, valid by construction, no persistence DTO (ADR 0008) · interface: `Article`, `Collection`, `Audience`, `MediaRef`, `Lifecycle`, `Change` · tests: `tests/domain/test_models.py`
- `access.py` — viewer-facing access decisions composed over the resolver · interface: `can_view`, `visible`, `project`, `preview` · tests: `tests/domain/test_access.py`
- `audience.py` — THE effective-Audience resolver: lifecycle/Trash gate + inherit walk, single pure source (ADR 0001) · interface: `effective_audience`, `ArchivistOnly` · tests: `tests/domain/test_audience.py`
- `collections.py` — Collection-chain resolution with proven invariants · interface: `resolve_chain`, `ResolvedChain` · tests: `tests/domain/test_collections.py`
- `viewer.py` — who is asking: the Viewer value union · interface: `Archivist`, `Member`, `Public` · tests: `tests/domain/` (no module of its own; every suite here builds one)
- `identity.py` — Article identity: ULID mint, the one Article factory (ADR 0006/0008) · interface: `new_ulid`, `create_article`, `is_valid_ulid` · tests: `tests/domain/test_identity.py`
- `edtf.py` — EDTF Level 0/1 archival-date value object · interface: `EdtfDate` · tests: `tests/domain/test_edtf.py`

Internal: `errors.py`

A new `Article` field is classified in `tests/domain/test_access.py::_MEMBER_VISIBLE_FIELDS` (the gate goes red until it is): say whether a Member may ever see it, and why.
