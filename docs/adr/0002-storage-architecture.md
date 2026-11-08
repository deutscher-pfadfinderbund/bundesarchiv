# Storage: files-canonical per-Article tree behind a swappable port, with a derived index

Status: Accepted (2026-06-26). Amended by 0019 (2026-09-24), 0020 (2026-09-24).

Canonical data is **plain files on disk** — one directory per Article (named by an immutable **ULID**), holding a **`README.md`** (YAML front-matter + Markdown body = the source of truth), write-once media, and per-edit `history/` files. The metadata file is named `README.md` deliberately: file browsers, Git hosts (GitHub/GitLab), IDEs, and **Nextcloud's Rich Workspace** auto-render it, so each Article folder is **self-describing when browsed with no application at all** — reinforcing the readable-without-the-app goal. It carries a YAML-comment marker since the app is its sole writer and any browse mount is read-only. The data must be **human-readable without the application** (the archive outlives the software). All storage access goes through a **narrow swappable port** with adapters for **local filesystem (v1 primary)**, WebDAV/Nextcloud, and S3 (future). The **app is the sole writer** (single-writer invariant; pinned write order with `README.md` written last as the commit). A **derived, fully rebuildable index** (Postgres) serves search/audience/sort.

## Considered options

- **DB-canonical (Postgres) + derived file export** — rejected: the durable artifact becomes a binary dump, losing the readable-without-code goal.
- **Nextcloud as the canonical store** — rejected: ~yearly forced major upgrades and lossy file-versioning make it the wrong anchor for a decades archive. Demoted to a non-canonical, human-read-only role; never canonical, never human-writable (reversed by 0020). _(ADR 0005 refines the connection: since the app and Nextcloud cannot share a host, Nextcloud is an **async one-way WebDAV mirror** of the canonical local-FS tree, not a local read-only mount.)_
- **git as canonical / history layer** — deferred: not needed in v1. The on-disk shape already matches git's, so `git init` is a later upgrade if guaranteed history is ever required.

## Consequences

- Identity is the immutable ULID (directory name); `signature` is mutable metadata.
- The index is disposable; correctness rests on `README.md` alone.
- Swapping backends is a config change, which de-risks lock-in to any one backend.
