"""Smoke test: the package is importable and the toolchain runs."""

import bundesarchiv


def test_package_importable() -> None:
    assert bundesarchiv.__version__ == "0.1.0"
