"""Derived Postgres search index, a Django adapter (ADR 0004, ADR 0005).

This ``__init__`` imports nothing: both submodules load the ORM model, which needs the app
registry first.

Only ``app`` may import ``bundesarchiv.index``, and ``domain``/``persistence`` never import Django
(enforced by import-linter).
"""
