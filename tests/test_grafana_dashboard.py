"""The Grafana dashboard reads only log fields and values the app still writes.

The dashboard (`deploy/grafana/bundesarchiv.json`) queries the app's JSON log lines; a rename in
`src/` that leaves a panel behind blanks it unnoticed. Traefik, Prometheus and Nextcloud panels
and Procrastinate's own records are not ours and are skipped.
"""

import ast
import functools
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "bundesarchiv"
DASHBOARD = ROOT / "deploy" / "grafana" / "bundesarchiv.json"

_APP_STREAM = re.compile(r'container=~?"/bundesarchiv-[^"]*(?:app|worker)')
_FIELD_USES = (
    re.compile(r"\|\s*unwrap\s+(\w+)"),
    re.compile(r"\bby\s*\(([^)]*)\)"),
    re.compile(r"(?:\{\{|\s)\.(\w+)"),
)
_DERIVED = re.compile(r"label_format\s+(\w+)=")
_LOGGER = re.compile(r'logger\s*=\s*"([^"]+)"')
_PROCRASTINATE = re.compile(r'logger\s*=~?\s*"procrastinate')
_FILTER = re.compile(r'\b(task|message|stage|outcome|logger)\s*(=~|=)\s*"([^"]+)"')


def _panels(panels: list[dict]) -> Iterator[dict]:
    for panel in panels:
        yield panel
        yield from _panels(panel.get("panels", []))


@dataclass(frozen=True)
class _Written:
    """What `src/` can write: field names per module (dict entries and stored keys, keyword names
    as in `extra=`, annotated fields of a dataclass `asdict`ed into `extra`), and every string value."""

    fields: Mapping[str, frozenset[str]]
    values: frozenset[str]

    def fields_of(self, expr: str) -> frozenset[str]:
        """The fields `expr` can read: the module its `logger="…"` names, else any module's. A
        common word (`articles`) is a field somewhere, so a logger-scoped query checks its own."""
        logger = _LOGGER.search(expr)
        if logger and logger.group(1) in self.fields:
            return self.fields[logger.group(1)]
        return frozenset().union(*self.fields.values())


def _fields_in(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):  # a value too: a mapping may name the field (`_LEVELS`)
            yield from (
                item.value
                for item in (*node.keys, *node.values)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            yield node.slice.value  # fields["remote_bytes"] = ...
        elif isinstance(node, ast.keyword) and node.arg:
            yield node.arg
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            yield node.target.id


@functools.cache
def _written_by_src() -> _Written:
    trees = {
        ".".join(path.relative_to(SRC.parent).with_suffix("").parts).removesuffix(".__init__"): (
            ast.parse(path.read_text())
        )
        for path in SRC.rglob("*.py")
    }
    return _Written(
        fields={module: frozenset(_fields_in(tree)) for module, tree in trees.items()},
        values=frozenset(
            node.value
            for tree in trees.values()
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ),
    )


def _app_queries(dashboard: dict) -> Iterator[tuple[str, str]]:
    """(panel title, expression) of every query on the app's own log lines."""
    for panel in _panels(dashboard["panels"]):
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if _APP_STREAM.search(expr) and not _PROCRASTINATE.search(expr):
                yield panel["title"], expr


def unwritten(dashboard: dict, written: _Written) -> list[str]:
    """One line per field or value an app-log query of `dashboard` reads that `written` does not
    hold, naming the panel."""
    problems = []
    for title, expr in _app_queries(dashboard):
        read = {
            field.strip()
            for use in _FIELD_USES
            for group in use.findall(expr)
            for field in group.split(",")
        } - set(_DERIVED.findall(expr))
        problems += [
            f"{title!r}: field {field!r} is not written by src/"
            for field in sorted(read - written.fields_of(expr))
        ]
        for key, operator, value in _FILTER.findall(expr):
            pool = written.fields.keys() if key == "logger" else written.values
            if operator == "=":
                found = value in pool
            else:
                found = any(re.fullmatch(value, known) for known in pool)
            if not found:
                problems.append(f"{title!r}: {key}{operator}{value!r} matches nothing in src/")
    return problems


def test_the_dashboard_reads_only_what_the_app_writes() -> None:
    dashboard = json.loads(DASHBOARD.read_text())
    assert len(list(_app_queries(dashboard))) > 20  # the check saw the app's panels at all
    assert unwritten(dashboard, _written_by_src()) == []


def test_a_renamed_field_value_or_logger_is_reported() -> None:
    written = _written_by_src()

    def panel(expr: str) -> dict:
        return {"panels": [{"title": "P", "targets": [{"expr": expr}]}]}

    stream = '{container="/bundesarchiv-worker-1"} | json'
    bad = {
        f'{stream} | task="mirror_push" | unwrap sent_bytez': "sent_bytez",
        f'{stream} | task="mirror_pushh"': "mirror_pushh",
        f'{stream} | logger="bundesarchiv.app.nowhere"': "bundesarchiv.app.nowhere",
        f"sum by (rout) ({stream})": "rout",
    }
    for expr, missing in bad.items():
        [problem] = unwritten(panel(expr), written)
        assert "'P'" in problem
        assert missing in problem
    foreign = [
        '{container="/bundesarchiv-worker-1"} | json | logger="procrastinate.worker" | unwrap nope',
        '{service_name="traefik_access_log"} | json | unwrap nope',
    ]
    assert all(unwritten(panel(expr), written) == [] for expr in foreign)
