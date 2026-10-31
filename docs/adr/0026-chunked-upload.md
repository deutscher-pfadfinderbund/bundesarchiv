# Chunked upload: tus pieces staged on local disk, one finish per file

Status: Proposed (2026-10-31). Changes the upload path of ADR 0017 and the request bound of ADR
0020 ("nginx buffers the whole request body", `client_max_body_size 8g`).

## Context

The media manager posted every file of a batch in one multipart request. The reverse proxy in
front of the stack (Traefik, outside this repository) cuts a request whose body takes longer than
60 seconds to arrive, so a large scan on an ordinary uplink never reached the app. The proxy is
not ours to change. The owner chose to cut the upload into pieces inside the app (2026-10-31).

## Decision

- **Protocol: tus core 1.0.0 with the creation extension**, served by hand-rolled Django views:
  no tus server library exists for Django. No creation-with-upload, no deferred length, no
  `OPTIONS`. The client is `tus-js-client`, sending 8 MB pieces, one file after another; it retries
  a failed piece and resumes after a reload.
- **Routes, under the Article:**
  - `POST /articles/<ulid>/media/uploads` creates an upload from `Upload-Length` (the per-file
    ceiling `BUNDESARCHIV_MAX_UPLOAD_BYTES`, 4 GiB, is checked here) and `Upload-Metadata`
    (`filename`, optional `filetype`); 201 with its `Location`.
  - `HEAD`, `PATCH` and `DELETE` on `/articles/<ulid>/media/uploads/<id>`: the offset, the next
    piece at `Upload-Offset`, discard.
  - Status codes follow tus: 412 for another protocol version, 415 for a piece of another content
    type, 400 for a malformed header, 413 over the ceiling or past the upload's length, 409 for a
    wrong offset. Every answer carries `Tus-Resumable: 1.0.0`.
  - These routes came after the 2026-10-01 rename and have no German alias.
- **Access:** an upload belongs to one Archivist and one Article. The Article gate is the upload
  route's own (`_load_gated`); the Archivist's username and the Article must then match the
  upload's. Every miss — anyone else, a foreign or marked Article, an unknown, malformed or
  swept id — is the plain 404 (deny contract). Upload ids are 128 random bits.
- **Staging:** pieces land on local disk under `BUNDESARCHIV_UPLOAD_STAGING_ROOT`, never in the
  ObjectStore: a Docker named volume shared by app and worker. One folder per upload holds the
  bytes so far (their size is the offset) and a small record: Article, owner, file name, media
  type, length. An exclusive file lock serialises every operation on one upload across gunicorn's
  threads and the worker process, so of two pieces racing at one offset exactly one lands; a
  piece at the wrong offset or past the length writes nothing.
- **Finish per file:** once a file's last piece is in, the client posts `upload_id` to the
  existing route `article-media-upload`. The server feeds the staged bytes to `add_media` (a
  seekable stream, ADR 0019 "Streaming upload"), runs the same structural save and drawer render
  as a posted file, and frees the staged bytes once the save succeeds; a file already in the
  Article's media is not listed twice. A finish that saves nothing keeps the upload for a repeat:
  a lost race answers 503, which the client retries; an Article gone answers 404. A finished upload stays known until the sweep: its offset reads
  as its length, and a repeated finish (its answer lost to a dropped connection or a proxy
  timeout) answers 200 with the same render, saving nothing. Each file lands as soon as it is
  done. A finish of an incomplete upload is the plain 404 and saves nothing.
- **Sweep:** a periodic job removes uploads untouched for 24 hours, hourly.
- **nginx:** the tus routes sit behind the same `auth_request` gate as the upload route, with
  `client_max_body_size 16m` (one piece and headroom).
- **The multipart path stays** as the no-JS fallback, with a per-file limit of 50 MB
  (`BUNDESARCHIV_MAX_MULTIPART_UPLOAD_BYTES`, owner 2026-10-31); a larger file is refused with a
  German line in the media register, and nothing of that batch is stored. Its nginx location
  drops from `client_max_body_size 8g` to `64m`.

## Consequences

- Two upload paths to keep working: tus with JS, multipart without.
- A new volume (`upload-staging`) on the deploy host. Its content is disposable: a lost staging
  folder costs the archivist a re-upload, never archive data.
- Up to a day of abandoned pieces on disk, bounded by the per-file ceiling times the uploads
  started in that day.
- An `upload_id` posted to the upload route means a finish, so a form must never carry that
  field for another purpose.
