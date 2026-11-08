# domain — package rules

pure core. No IO, no Django, no settings. Errors are the typed `DomainError` hierarchy.
`effective_audience` is the ONE visibility resolver (ADR 0001) — never recompute its answer ad hoc.
`Article` is the one validated shape for codec, index and form: never add a persistence DTO; fix a bad
source by tightening `Article`'s invariants, without making stored READMEs stop decoding (ADR 0008).
An Article is a leaf: no nested READMEs. Parts without identity are media entries; parts with identity
become a Collection of Articles (ADR 0015).
Never sync or validate audience group names against Keycloak: a group nobody carries matches nobody
(ADR 0018; `tests/domain/test_access.py`).
