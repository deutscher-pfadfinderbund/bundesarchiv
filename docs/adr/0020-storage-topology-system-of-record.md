# Storage topology: Nextcloud is the system of record, the VPS holds the working copy

Status: Proposed (2026-09-24). Amends ADR 0002 (Nextcloud rejected as canonical) and
ADR 0005 ("Deployment topology"). Stage B would amend ADR 0017 ("the mirror never serves
users").

## Context

- Owner, 2026-09-24:
  - The Nextcloud (StorageShare) has TBs of space and is backed up.
  - The VPS has 50 GB, about 11 GB of it free. Its copy is not what the archive's
    durability rests on.
  - The Nextcloud is to be the source of truth.
- ADR 0005 made the VPS disk canonical and Nextcloud an async browse mirror. Durability
  was to come from restic, and backup has since been ruled out of scope (addendum
  2026-09-19). So durability rests on the Nextcloud copy.
- The mirror as built (`app/mirror.py`, 2026-09-24) runs the wrong way for a system of
  record:
  - `push_key` deletes a key on Nextcloud when the VPS lacks it.
  - `reconcile` deletes every key that exists only on Nextcloud.
  - `reconcile` compares every key byte for byte on both sides. At today's size that
    downloads 5.0 GB from WebDAV on every daily run (`0 3 * * *`).
  - Every save pushes every key of the Article (`articles._enqueue_mirror_keys` over
    `keys_for`), and `push_key` writes each key unconditionally. A caption edit on an
    Article with a 4 GiB video uploads the 4 GiB again.
  - `hard_delete` pushes the removed keys. `push_key` finds them gone and deletes them on
    Nextcloud. The `.trash/` copy never reaches Nextcloud.
- An upload occupies VPS disk up to three times over while it runs, all on the same disk
  in the deployed `compose.yml`, which has no tmpfs:
  - nginx buffers the whole request body (`client_max_body_size 8g`, request buffering
    on by default).
  - Django spills files over `FILE_UPLOAD_MAX_MEMORY_SIZE` (default 2.5 MB) to a temp
    file.
  - The canonical write stores the file itself.
  - At the 4 GiB per-file cap that is up to 12 GiB, more than the 11 GB free.

### What the StorageShare can do

Measured on 2026-09-24, full results in [`docs/nextcloud-webdav-notes.md`](../nextcloud-webdav-notes.md):

- Compare-and-swap (`If-Match`) and create-only writes (`If-None-Match: *`,
  `MOVE` with `Overwrite: F`) work.
- A `PUT` answers with the ETag that `PROPFIND` reports later.
- One `PROPFIND Depth: infinity` lists an archive-sized tree (11706 entries) with ETag and
  size in 9.2 s.
- Range and chunked upload work.
- `OC-Checksum` is stored, but the server does not verify it.

### Terms

- **System of record:** the complete, backed-up tree, history included (ADR 0019).
- **Working copy:** what the app reads to answer a request.

## Decision

### Roles

- **System of record:** the app's folder on the Nextcloud.
- **Working copy:** the VPS. It holds every current README (Articles and Collections),
  the search index, the thumbnails and the media.
- No page request queries WebDAV. Search, lists and article pages come from the index
  and the local READMEs.
- **One writer.** The app's Nextcloud user writes the folder. People get it read-only
  through the Nextcloud share permission. A hand edit there still shows up: its `version`
  token no longer matches the push record. `verify` (ADR 0019) checks the local tree.
- **The folder is archivist-level data.** It holds every record at every tier: drafts,
  group-only records, archivist-only fields, history. It is shared only with people who
  may see all of that, never through a public link and never with a members group
  (owner, 2026-09-30: no public link exists; the owner controls the share).

### Stage A — deployment 1: the VPS commits, the push follows

- `save` commits on the VPS disk, as before. The per-save push copies only what is not
  on Nextcloud yet (owner, 2026-09-24: never re-upload unchanged files):
  - the new README
  - the new history file
  - new media files
  Write-once keys that already exist there are skipped.
- **Hard delete is final for the app** (owner, 2026-09-24).
  > **Amended 2026-10-01 (ADR 0022):** "Löschen" puts the Article in the Papierkorb; the hard
  > delete below is reachable only as the Papierkorb's "Endgültig löschen".
  - The VPS removes the Article's folder. There is no local `.trash/` any more.
  - Nextcloud gets the delete as well. Nextcloud's own trash bin catches it, under the
    retention its admin sets. The app keeps no copy and no control, or it would not be a
    hard delete.
  - Order: the local folder and the index row go first, then a job deletes the folder on
    Nextcloud.
  - **Accepted risk** (owner, 2026-09-24): no durable record of a pending delete. If that
    job is lost, the Article stays on Nextcloud. The daily reconcile reports it as a
    Nextcloud-only key, and a restore would bring it back.
  - Apart from hard delete, the app deletes nothing on Nextcloud.
- **A push record in Postgres** (owner, 2026-09-24) holds, per pushed key, the SHA-256
  of the local bytes and the `version` token the write returned.
  - It is derived state, like the search index. Losing it moves no data: the next
    reconcile rebuilds it, write-once keys by existence and READMEs by one download each
    (1.47 MB for all 2506 at import).
- **What a save pushes:** every key of the Article that the record does not hold with
  the same SHA-256. In practice the new README, the new history file and new media.
- **Push order** (owner, 2026-09-24): per Article in the local save order — media, then
  history, then the README. A crash can then leave only files no README refers to yet,
  never a README that refers to a file Nextcloud lacks. Reconcile keeps the same order
  per Article.
- **Which keys are write-once is the repository's knowledge** (owner, 2026-09-24): its
  key listing marks each key as write-once (history, media) or replaceable (README). The
  push uses `create` for the first and a plain replace for the second, and hashes a
  write-once key only once, from the front matter for media. The push code holds no
  copy of the layout.
- **`reconcile` only adds, and downloads nothing in the normal case.**
  - One listing of Nextcloud with `version` tokens, one local listing, the record.
  - A key missing on Nextcloud, or a local README whose SHA-256 differs from the
    record, is pushed.
  - A `version` token that differs from the record means the file changed on
    Nextcloud, for example a hand edit. It is reported as a warning.
  - Keys that exist only on Nextcloud are reported as a warning, never deleted.
- **Loss window:** saves committed on the VPS and not yet pushed. Normally seconds. The
  job queue lives in Postgres, which is treated as rebuildable, so the daily reconcile
  is the backstop for jobs lost with it.
- **Restore:** a `restore` command pulls the tree from Nextcloud onto an empty VPS disk,
  streaming each file (no file is held in memory). The index rebuild and the thumbnails
  follow, so covers work right after a restore.
- **Disk guard:** an upload is refused with a German message when free disk space after
  it would fall below a reserve. The default is 3 GiB, set via an environment variable.
  The guard keeps Postgres, on the same disk, writable.
- **Upload buffering stays on** (owner, 2026-09-24).
  - nginx keeps buffering the request body, so a slow upload never holds an app thread.
  - With ADR 0019's streaming upload the peak is three times the file size: nginx's
    buffer, Django's temp file and the stored file. It is twice when the local adapter
    turns the temp file into the stored file without a copy.
  - Large uploads are rare. If disk space demands it, turning buffering off is one nginx
    setting (`proxy_request_buffering off`) plus a check of the 300 s timeouts.

### Stage B — on trigger: Nextcloud commits, the VPS caches media

- **Trigger:** VPS free space below 5 GiB, or canonical media above 15 GiB, whichever
  comes first.
- The layout (ADR 0019) is the same in both stages, so switching moves code, not data.
- The details get their own ADR when the trigger fires. The sketch:
  - **Reads stay local.** Requests and index writers read only the working copy. The
    system of record takes commits and fills cache misses. So the Archive gets two stores:
    a local one for reads and a remote one for commits. Stage B must not add a per-file
    `exists` inside the save lock, an upload to Nextcloud inside the request, or a Range
    request passed through to Nextcloud on a cache miss.
  - **Metadata.** `save` writes the history file with `create`, and the README with a
    conditional replace against the `version` it read. Both port additions arrive with
    stage B. That is compare-and-swap at the
    system of record, across processes. It retires `WRITER_LOCK` and tech-debt #17. The
    local README copy is updated after.
  - **Media.**
    - Upload: stored locally first, then pushed with `create` from a job, as in stage A.
    - Read: nginx serves the local cache. On a miss the whole file is fetched from the
      system of record into the cache, and ranges are served from there. For Nextcloud
      that fetch is an `internal` location that proxies WebDAV with the app user's
      credentials.
    - Authorization stays in Django.
  - **Eviction.** First, media that no current README refers to and that Nextcloud has
    confirmed. Then the least recently used.
  - **Nextcloud down.** Reads served by the index, the READMEs and the cache keep
    working. Saves fail with a German message.
  - The StorageShare supports every port operation stage B needs
    (`docs/nextcloud-webdav-notes.md`).
  - Fixity on Nextcloud needs the bytes downloaded: the server stores a client-supplied
    checksum without verifying it.

## Considered options

- **Stage B from deployment 1.** Rejected for now:
  - more code before the first deployment
  - saves would depend on Nextcloud uptime
  - 5.0 GB of media fits on the VPS today
- **Keep ADR 0005 as is.** Rejected: the copy durability rests on would be a mirror
  that deletes to match the working copy.
- **An external sync tool** (`rclone copy` is add-only, `rclone sync` deletes).
  Rejected:
  - it loses the per-save push
  - one wrong flag turns it into a deleting sync

## Consequences

- `app/mirror.py`:
  - `push_key` stops deleting, and skips write-once keys that already exist.
  - `reconcile` becomes add-only with a report, working from the two listings and the
    push record.
  - `hard_delete` deletes locally, then a job deletes on Nextcloud. The local `.trash/`
    goes.
- The port additions of ADR 0019 are used here: listing with `size` and `version`,
  `create`, `Busy`, prefix delete (an Article leaves Nextcloud as one folder), streamed
  read.
- The WebDAV adapter changes internally (measured 2026-09-24, see the notes):
  - Plain `PUT` replaces the temp-file-plus-`MOVE` write. A reader saw only the old bytes
    during a 1 GiB `PUT` over an existing file.
  - `MOVE` under contention answered `500` even when it had succeeded, and the current
    temp-plus-`MOVE` write left temp files behind with 10 parallel writers.
  - Writes are retried on `Busy`. 6 of about 14,000 parallel writes to distinct keys
    failed with `404` or `423` and needed a retry.
  - The listing is one `PROPFIND Depth: infinity`: 9.2 s for an archive-sized tree of
    11706 entries.
- New: the `restore` command, and the disk-guard setting and check in the upload view.
- The mirror warning in `deploy/production.env.example` changes: the app no longer
  deletes in that folder. Settings keep their `BUNDESARCHIV_MIRROR_*` names, so
  deployed env files stay valid.
- ADR 0002's rejection of Nextcloud as canonical rested on its forced upgrades and lossy
  file versioning. Now:
  - The history no longer depends on Nextcloud versioning (ADR 0019).
  - The app depends only on the port semantics. The WebDAV adapter uses standard HTTP
    conditional requests, so any WebDAV host with them can take over the folder.
