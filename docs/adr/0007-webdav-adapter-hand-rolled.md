# The WebDAV mirror adapter is hand-rolled on httpx, not a client library

## Context

`WebDavObjectStore` (the Nextcloud mirror backend, ADR 0005) is ~160 lines of our own
code on `httpx`. We evaluated replacing it with a maintained Python WebDAV client
library (webdav4, webdavclient3, fsspec-webdav, nc-py-api, pyncclient, aiodav,
easywebdav). The minimal-deps convention sets a high bar for adding a runtime dependency.

## Decision

**Keep the hand-rolled adapter.** Three reasons:

1. **No library delivers the deferred Nextcloud hardening for free.** The only motive to
   adopt one is the unbuilt items — chunked-v2 upload, 423-Locked retry, 507 handling, the
   lock object. No maintained library provides them: webdav4 only *maps* 423/507 to
   exceptions (no retry) and has no Nextcloud chunking; the lock is our store-level
   protocol, not a client feature; off-the-shelf chunking exists only in an inactive package.
2. **A library never removes the adapter.** The `ObjectStore` port + shared conformance
   suite mean any library is wrapped behind `WebDavObjectStore` regardless — we'd swap
   stdlib-on-httpx for third-party-on-httpx: same code shape, plus a dependency, minus types.
3. **The adapter already clears the bar a dependency must clear.** Sync (matches the WSGI
   convention), `mypy --strict`-clean, zero deps beyond httpx (already present), tested
   against a real in-process WebDAV server, errors wrapped at the port.

Best candidate `webdav4` (sync, httpx-based, 3.14-compatible, maintained) is the only one
that breaks no convention — but it ships **no `py.typed`** (forcing an
`ignore_missing_imports` override on a runtime dep), brings no chunking, and saves only
~40–60 lines. A worse trade.

## Consequences

- We own the deferred Nextcloud hardening either way. Chunked-v2 is a documented Nextcloud
  protocol that slots into the existing PUT+MOVE shape and the `put_large(stream, size)`
  signature (the `size` hint exists for exactly this) in ~30–50 lines, zero new deps —
  build it inside the adapter when large-media volume justifies it.
- **Reconsider `webdav4`** only the day it ships both a `py.typed` marker and Nextcloud
  chunked upload; until then the hand-rolled adapter is the better trade.
