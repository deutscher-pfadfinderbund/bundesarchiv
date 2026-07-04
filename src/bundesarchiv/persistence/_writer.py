"""The one process-wide write mutex the repositories share (ADR 0013).

Both `ArticleRepository` and `CollectionRepository` write the SAME canonical store
through the SAME `ObjectStore` port, and the port offers no compare-and-swap. Their
`save` is a load-check-write critical section: read the current version → compare to
the caller's `expected_version` → `write_atomic` the commit. Two genuinely-interleaved
saves could otherwise both pass the check and the second would silently clobber the
first — the one unforgivable failure for an archive (ADR 0013 "Why not:
last-writer-wins").

`WRITER_LOCK` serializes that critical section across BOTH repositories. It is one
module-level `threading.Lock` so the two repos share a single lock — they must, since
they write one store; a per-repo lock would leave the check-then-write interleavable
across repositories. It is held ONLY across the critical section (version read →
compare → commit write), never across anything slow that is not the check-and-write.

This closes the intra-process race. The cross-process race is out of scope by the
single-app-process deploy rule (ADR 0013 runbook item): one app process writes the
canonical store; a second writer host would need real distributed CAS (deferred with a
trigger). Media blobs are exempt — content-addressed, write-once, idempotent — so
`add_media` does not take the lock.
"""

import threading

# The single writer mutex. Module-level so `import`ing it from either repository yields
# the same object; both repositories acquire THIS lock around their critical section.
WRITER_LOCK = threading.Lock()
