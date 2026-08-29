"""The auth settings whose DIRECTION is the security property (ADR 0018).

The anonymous gate is ON in the base (production) settings and OFF only in ``settings_dev``, so a
production deploy that forgets an env var can never fall open to anonymous browsing — it redirects
to a login that itself falls closed. Nothing else in the fast suite pins that direction: the gate
middleware reads the flag, and a flipped default would look like a passing suite.
"""

from bundesarchiv.index import settings as prod_settings
from bundesarchiv.index import settings_dev


def test_anonymous_gate_is_on_in_production_settings() -> None:
    assert prod_settings.ANONYMOUS_GATE_ENABLED is True


def test_anonymous_gate_is_off_in_dev_settings() -> None:
    assert settings_dev.ANONYMOUS_GATE_ENABLED is False
