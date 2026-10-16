"""READMEs the app does not write today, for every suite: as a hand edit on the system of record
may leave them (ADR 0020)."""

import pytest

UNREADABLE_README = [
    pytest.param(b"---\ntitle: [unclosed\n---\n", id="not-yaml"),
    pytest.param("---\ntitle: Größe\n---\n".encode("cp1252"), id="not-utf8"),
]

#: How a hand edit may save a README the app wrote with LF line ends and no BOM.
HAND_SAVED = [
    pytest.param(lambda text: text.replace("\n", "\r\n").encode(), id="crlf"),
    pytest.param(lambda text: text.replace("\n", "\r").encode(), id="lone-cr"),
    pytest.param(lambda text: "\N{BYTE ORDER MARK}".encode() + text.encode(), id="bom"),
]
