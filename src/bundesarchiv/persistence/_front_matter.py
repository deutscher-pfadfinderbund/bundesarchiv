"""The README shape both codecs share (ADR 0005, ADR 0010, ADR 0019): the YAML front matter
between two fences, the managed-by marker its first line as a comment, then the body, which opens
with the title as its H1 line.

Only `UnreadableReadme` crosses out of `text_of` and `parse`; a raw decode or `yaml` error never does.
"""

from typing import Any

import yaml

from bundesarchiv.domain.models import Audience, Ulid, Version
from bundesarchiv.persistence.errors import UnreadableReadme

MARKER = "Managed by bundesarchiv — do not edit by hand."
FENCE = "---"
#: Nextcloud Text shows front matter as such only when the fence is the very first line.
HEAD = f"{FENCE}\n# {MARKER}\n"


def text_of(name: str, data: bytes) -> str:
    """README `data` as text with LF line ends. A hand edit (ADR 0020) may add a BOM or CRLF or
    CR line ends, which are dropped; one in another encoding than UTF-8 raises `UnreadableReadme`."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnreadableReadme(f"{name}: README is not UTF-8: {exc}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


class _Dumper(yaml.SafeDumper):
    """``safe_dump`` with a NEL (U+0085) kept intact: the emitter would otherwise fold it as a line
    break inside a plain or single-quoted scalar and read back as spaces."""


def _represent_str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = '"' if "\x85" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _represent_str)


_LINE_BREAKS = "\n\r\x85\u2028\u2029"


def dump(front_matter: dict[str, Any], title: str, body: str) -> str:
    """README text: `front_matter` in key order between the fences, then `title` as the H1 line,
    one blank line and `body`. Raises `ValueError` for a title the line cannot hold: a line break
    (any an editor may break on), or a blank one, which reads as `#` once an editor trims it."""
    if not title.strip() or any(brk in title for brk in _LINE_BREAKS):
        raise ValueError(f"the title must be one non-empty line, got {title!r}")
    return f"{HEAD}{_yaml(front_matter)}\n{FENCE}\n# {title}\n\n{body}"


def _yaml(front_matter: dict[str, Any]) -> str:
    return yaml.dump(
        front_matter,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip("\n")


def split_title(ulid: Ulid, text: str, title_key: str) -> tuple[dict[str, Any], str | None, str]:
    """The mirror of `dump`: the front matter, the title and the body after it. A front matter that
    holds `title_key` is the old layout (ADR 0019): no title, the body verbatim."""
    front_matter, body = parse(ulid, text)
    if title_key in front_matter:
        return front_matter, None, body
    heading, _, rest = body.partition("\n")
    if not heading.startswith("# ") or not rest.startswith("\n"):
        raise UnreadableReadme(f"{ulid}: README body does not open with its title line")
    return front_matter, heading.removeprefix("# "), rest.removeprefix("\n")


def _split(ulid: Ulid, text: str) -> tuple[list[str], str]:
    """The front-matter lines between the fences, and the body verbatim."""
    lines = text.split("\n")
    if lines and lines[0].lstrip().startswith("<!--"):
        lines = lines[1:]  # the old marker, an HTML comment (ADR 0019)
    if not lines or lines[0].strip() != FENCE:
        raise UnreadableReadme(f"{ulid}: README has no front-matter fence")
    try:
        close = lines.index(FENCE, 1)
    except ValueError:
        raise UnreadableReadme(f"{ulid}: README front-matter is unterminated") from None
    # The single separator newline `dump` added was already consumed by split;
    # lines[close + 1:] reconstructs the body verbatim (a body may open with blank lines).
    return lines[1:close], "\n".join(lines[close + 1 :])


def is_dumped(ulid: Ulid, text: str) -> bool:
    """Whether the front matter of README `text`, the marker aside, is exactly what `dump` writes
    for the mapping it holds, so it holds nothing beside it: no comment, no duplicate key."""
    block, _ = _split(ulid, text)
    if block[:1] == [f"# {MARKER}"]:
        block = block[1:]
    return "\n".join(block) == _yaml(_load(ulid, block))


def parse(ulid: Ulid, text: str) -> tuple[dict[str, Any], str]:
    """The front matter and the body of README `text`, the body verbatim."""
    block, body = _split(ulid, text)
    return _load(ulid, block), body


def _load(ulid: Ulid, block: list[str]) -> dict[str, Any]:
    try:
        front_matter = yaml.load("\n".join(block), Loader=yaml.CSafeLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        # RecursionError is NOT a yaml.YAMLError subclass: deeply-nested flow collections
        # (a corrupt/hostile README) blow the stack inside the loader — contain it too.
        raise UnreadableReadme(f"{ulid}: README front-matter is not valid YAML: {exc}") from exc
    if not isinstance(front_matter, dict):
        raise UnreadableReadme(f"{ulid}: README front-matter is not a mapping")
    return front_matter


def version_of(fm: dict[str, Any], *, absent: Version | None = None) -> Version:
    """The stored optimistic-concurrency version: an exact non-negative int, or `absent` when the
    key is missing (None: the key is required). Raises `ValueError` otherwise; bool/float/str are
    rejected rather than coerced (int(1.5) -> 1 would silently accept a corrupt version)."""
    value = fm.get("version", absent)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"version must be a non-negative integer, got {value!r}")
    return value


def audience_to_front_matter(audience: Audience | None) -> dict[str, Any]:
    """No key for inherit (ADR 0001): absence reads as inherit."""
    if audience is None:
        return {}
    return {"audience": {"tier": audience.tier.value, "groups": list(audience.groups)}}
