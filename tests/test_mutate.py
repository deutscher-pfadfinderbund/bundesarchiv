"""``scripts/mutate.py`` puts the mutated file back byte for byte."""

import os
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent / "scripts" / "mutate.py"


def test_a_caught_mutation_leaves_the_file_byte_identical(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    original = b"# \xc3\xa4 unicode survives\r\nVALUE = 1\n"
    target.write_bytes(original)
    probe = tmp_path / "test_target.py"
    probe.write_text("import target\n\ndef test_value():\n    assert target.VALUE == 1\n")
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}

    result = subprocess.run(  # noqa: S603 — fixed arguments
        [sys.executable, str(_SCRIPT), str(target), "VALUE = 1", "VALUE = 2", str(probe)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CAUGHT" in result.stdout
    assert target.read_bytes() == original
    assert sorted(p.name for p in tmp_path.iterdir()) == ["target.py", "test_target.py"]
