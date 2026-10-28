# domain — package law

Law: pure core. No IO, no Django, no settings. Errors are the typed `DomainError` hierarchy.
`effective_audience` is the ONE visibility resolver (ADR 0001) — never recompute its answer ad hoc.
