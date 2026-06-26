# Storage: files-canonical per-Article tree behind a swappable port, with a derived index

Canonical data is **plain files on disk** — one directory per Article (named by an immutable **ULID**), holding a **`README.md`** (YAML front-matter + Markdown body = the source of truth), write-once media, and a per-edit append-only change record. The metadata file is named `README.md` deliberately: file browsers, Git hosts (GitHub/GitLab), IDEs, and **Nextcloud's Rich Workspace** auto-render it, so each Article folder is **self-describing when browsed with no application at all** — reinforcing the readable-without-the-app goal. It carries a top-of-file marker (`<!-- Managed by the Bundesarchiv app — edit via the application -->`) since the app is its sole writer and any browse mount is read-only. The data must be **human-readable without the application** (the archive outlives the software). All storage access goes through a **narrow swappable port** — `read` / `writeAtomic` / `putLarge` / `list` / `exists` / `delete` (no append, move, or lock) — with adapters for **local filesystem (v1 primary)**, WebDAV/Nextcloud, and S3. The **app is the sole writer** (durable per-Article lock object + single-writer invariant; pinned write order with `README.md` written last as the commit). A **derived, fully rebuildable index** (engine TBD) serves search/audience/sort. Backup = **restic** of the tree with a rehearsed restore.

## Considered options

- **DB-canonical (Postgres) + derived file export** — rejected: the durable artifact becomes a binary dump, losing the readable-without-code goal.
- **Nextcloud as the canonical store** — rejected: ~yearly forced major upgrades and lossy file-versioning make it the wrong anchor for a decades archive. Demoted to an optional **strictly read-only** browse mount + a backup hedge; never canonical, never writable.
- **git as canonical / history layer** — deferred: not needed in v1. The on-disk shape already matches git's, so `git init` is a later upgrade if guaranteed history is ever required.

## Consequences

- Identity is the immutable ULID (directory name); `signature` is mutable metadata.
- The index is disposable; correctness rests on `README.md` alone.
- Swapping backends is a config change, which de-risks lock-in to any one backend.
