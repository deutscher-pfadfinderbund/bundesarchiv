"""The web layer — the HTTP-facing sibling of ``bundesarchiv.app`` (the service shell).

``app/`` is the imperative service layer (it may import index/persistence/domain); ``app/web/``
is its HTTP-facing sibling and follows the SAME import direction — nothing outside ``app`` imports
``app`` (the architecture test pins it). This package holds the request→Viewer trust boundary
(``viewers.viewer_of``) plus the dev-only viewer switcher (``dev`` — referenced ONLY from
``settings_dev``, never reachable under production settings).
"""
