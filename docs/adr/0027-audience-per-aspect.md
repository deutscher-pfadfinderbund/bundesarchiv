# Audience per aspect: the record and the files of an Article get their own rung

Status: Accepted (owner, 2026-11-07). Amends ADR 0001, 0015 and 0023.

## Context

The archivists asked (2026-11-07) for Articles every Member may read whose files only one
Keycloak group may open, to prevent distribution of the scans. ADR 0001 gives an Article one
Audience; files and page text follow it (ADR 0017, 0023).

## Decision

- **Two aspects, each a rung on the ADR 0001 ladder.** `RECORD`: the metadata, including
  captions, filenames, file kinds and counts. `FILES`: the bytes (original, display, thumbnail)
  and everything derived from them (page text, page hits, page links).
- **Resolution per aspect is the ADR 0001 walk.** Lifecycle and deletion gate first. Then the
  nearest explicit rung for that aspect along Article → Sammlung → root; none → the effective
  `RECORD` rung. v1 stores a `FILES` rung on Articles only.
- **A viewer sees an aspect when they clear the `RECORD` rung and the aspect's rung.** A wider
  `FILES` rung is inert. Rungs are never compared or intersected.
- **One resolver and one restated index predicate, per aspect** (ADR 0012). Scope columns per
  aspect; the equivalence test proves (viewer, article, aspect).
- **A Member who clears the record but not the files sees locked tiles:** caption and kind, no
  thumbnail, one hint. The preview probes each aspect.
- **On disk:** one optional README key per aspect beside `audience`; absent means inherit.

## Consequences

- An app image older than this ADR drops the key on save: after the deploy, no older image
  may write Articles.
- A file a Member fetched before the restriction stays in their browser cache (ADR 0017).
- Prerequisite: `docs/tech-debt.md` #54 (issue #91), or a save after a conflict can drop the
  `FILES` rung silently.
