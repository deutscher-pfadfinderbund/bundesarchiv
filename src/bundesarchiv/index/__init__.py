"""Derived Postgres search index, a Django adapter (ADR 0004, ADR 0005); see the module map
for its interface.

This ``__init__`` imports nothing: both submodules load the ORM model, which needs the app
registry first.

Nothing outside ``app`` may import ``bundesarchiv.index`` and nothing inside
``domain``/``persistence`` may import Django (layering convention, enforced in review).
"""
