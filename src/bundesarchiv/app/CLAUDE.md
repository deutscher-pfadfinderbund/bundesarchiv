# app — package law

Law: `Archive.canonical()` is the ONLY place in `src/` that builds the CANONICAL store and its index
from settings (ADR 0024) — new code takes an `Archive`, never constructs a store or an index.
(`tasks.mirror_store()` builds the system of record's WebDAV store from settings too, ADR 0020; it
is never a read path.) The write shell's
ordering is a contract (ADR 0013/0014): canonical CAS write, then `after_write.run` (index sync whose
failure must NOT re-raise, then the mirror enqueue), then the derived-file enqueues (all swallowing).
ADR 0013's split is which entry point you call: form saves carry the form's expected version straight to `save_article`, never
through the retrying `update_article` (which owns the load-mutate-save cycle for internal mutations).
Every write service that writes a version takes `changed_by`, who is acting; the version it writes records it (ADR 0019).
