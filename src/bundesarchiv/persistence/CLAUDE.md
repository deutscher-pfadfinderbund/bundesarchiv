# persistence — package rules

this package NEVER imports Django or reads settings (ADR 0005) — construction from settings
lives in `app/archive.py`. The README files are canonical; everything else is derived. Every save
and every hard delete goes through `_writer`, under one lock (ADR 0013, 0019, 0020).
All three ObjectStore adapters are
parametrized into the one shared conformance suite
(`tests/persistence/test_objectstore_conformance.py`) — never test an adapter its own way;
adapter-specific files cover only what the port cannot state. A README that does not decode (not
UTF-8, not YAML, wrong shape) raises `UnreadableReadme`; each repository's `scan` sorts such records
out, and `load_all` leaves such a Collection out (owner 2026-10-01). A validation rule added for new
writes never runs on the decode of stored READMEs, or older files stop loading.

Only the archive files (the canonical store and its mirror) must survive the loss of the server;
Postgres may hold admin data (sessions, audit) beside the disposable index (owner, 2026-08-30).
