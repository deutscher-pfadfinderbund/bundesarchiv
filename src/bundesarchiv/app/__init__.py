"""The application-service layer — the imperative shell the Part 4.5+ views call (ADR 0014).

This is the ONLY package allowed to import ``bundesarchiv.index``: it wires the pure domain +
persistence core to the derived Postgres index. Each service is a thin, explicit two-step — the
canonical repo write (CAS, ADR 0013) THEN the synchronous index update (ADR 0014) — and returns a
``SaveResult`` whose ``index_updated`` flag lets the view show the ADR-mandated specific warning
when the index update failed but the canonical write stood.

It IS an installed Django app (so Procrastinate autodiscovers ``tasks.py`` and Django discovers
its management commands), so this ``__init__`` imports nothing: the services pull in the
``ArticleIndex`` ORM model, which cannot load at app-``populate()`` time. Import them from their
submodules (``articles``, ``collections``, ``result``).
"""
