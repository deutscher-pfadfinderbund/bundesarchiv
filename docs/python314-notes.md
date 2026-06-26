# Python 3.14 — idiom notes

How to write **3.14-correct** code (vs 3.10–3.12 habits). The project targets Python ≥3.14; these are the shifts that catch experienced-but-slightly-stale authors. Sources: [What's New 3.14](https://docs.python.org/3.14/whatsnew/3.14.html), [PEP 649](https://peps.python.org/pep-0649/)/[749](https://peps.python.org/pep-0749/) (annotations), [PEP 750](https://peps.python.org/pep-0750/) (t-strings), [PEP 758](https://docs.python.org/3.14/whatsnew/3.14.html), [PEP 765](https://peps.python.org/pep-0765/).

## Annotations (PEP 649) — the big one

- **DON'T** add `from __future__ import annotations`. PEP 649 makes annotations lazy *by default*; the future import is the older PEP 563 (stringization), is now redundant, and is on a path to becoming a `SyntaxError`.
- **DO** write forward references **bare/unquoted** — `field: Model`, not `field: "Model"`. Deferred evaluation handles it.
- ⚠️ **The foot-gun for Django/DRF/dataclasses:** do **not** hide a name under `if TYPE_CHECKING:` if a *runtime* introspector reads that annotation (`typing.get_type_hints`, DRF serializers, dataclasses, pydantic, SQLAlchemy `Mapped[]`). Without the future import, annotations are deferred *but resolvable*, so `VALUE`-mode resolution raises `NameError` — and only on the introspection path, so tests can pass while production fails. Import such names normally; reserve `TYPE_CHECKING` for names *never* touched at runtime.
- **DO** use `annotationlib.get_annotations(obj, format=...)` (not raw `__annotations__`): `FORWARDREF` to tolerate undefined names, `STRING` for source form. `annotationlib.ForwardRef` supersedes `typing.ForwardRef`.

## New syntax worth using

- **t-strings (`t"..."`, PEP 750)** evaluate to `string.templatelib.Template`, **not `str`**. Use at **injection boundaries** (SQL, HTML/attribute escaping, shell) with a renderer that sees literal vs interpolated parts — makes injection structurally impossible. **DON'T** treat a `Template` as a string (no `__str__`/`__len__`, no `+ str`, can't `print`-format). Keep **f-strings** for ordinary display/logging.
- **`except A, B:`** without parentheses (PEP 758) for multi-type handlers (parens still needed with `as`).

## Foot-guns / behavior changes

- **PEP 765:** `return`/`break`/`continue` leaving a `finally` block is a `SyntaxWarning` (usually a swallowed-exception bug). Move it after the `try/finally`. Treat as error in CI.
- **`datetime.utcnow()`/`utcfromtimestamp()` deprecated** → tz-aware `datetime.now(UTC)`.
- **pathlib** gained `Path.copy`, `copy_into`, `move`, `move_into`, and `Path.info` (cached stat). **Prefer these over `shutil`** for path-centric code — relevant to the local-FS ObjectStore adapter. (`PTH` ruff rules are enabled.)
- `int()` no longer falls back to `__trunc__`; `NotImplemented` in a boolean context now raises `TypeError`.

## typing (mypy --strict)

- `int | str` **is** `Union[int, str]` at runtime (`types.UnionType` aliases `typing.Union`); `isinstance(x, Union)` is valid.
- Use **`TypeIs`** (two-sided narrowing) over `TypeGuard`, and `ReadOnly[...]` in `TypedDict` — both available on ≥3.14 (shipped in 3.13).
- **Avoid** functional/keyword `NamedTuple`/`TypedDict` forms, `typing.ByteString`/`typing.Text` (use class syntax, `collections.abc.Buffer`).

## Build / tooling

- **Free-threading (`python3.14t`)** is a separate, non-default build — a deploy concern, not a coding-style one. Pin the standard GIL build; write normal code.
- **ruff** infers its target from `requires-python` (≥3.14) — do **not** enable the `FA` (flake8-future-annotations) rules, which would re-suggest the future import.

## Not in 3.14 (don't reach for these yet)

- PEP 787 (t-string `subprocess`) — proposal, not landed.
- PEP 728 (`TypedDict` `closed=`/`extra_items`) — provisional; verify against the exact point release before relying on it.
