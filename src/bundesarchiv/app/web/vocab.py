"""Controlled vocabulary + the EDTF German echo for the cataloging form (Part 4.7, spec §3/§4/§5).

Two pure presentation helpers, IO-free and request-free so the form controller and its tests read
one source with no database:

- ``MEDIENART_DOKUMENTTYP`` — the fixed-in-code Medienart→Dokumenttyp mapping (owner Q1: v1 is
  fixed-in-code; if it ever becomes archivist-editable the option source moves to a managed store
  and only this module changes). It sits behind ``media_types`` / ``document_types_for`` /
  ``is_valid_pair`` / ``grouped_document_type_options`` — ONE accessor set so the dependent-select
  render (all types as ``<optgroup>``s, no-JS baseline), the server-side pair re-validation, and any
  later HTMX ``/dokumenttypen`` endpoint never derive the vocabulary twice.
- ``edtf_to_german`` — the human-German echo rendered server-side after a submit (spec §5) AND the
  4.6 detail-page date presentation (the sentence under the title). It reads the already-validated
  ``EdtfDate`` value object; an absent date yields an empty echo. It stays a DISPLAY helper: it never
  validates (the field's error path owns that), so it can only ever return neutral body text, never
  an error. Its month/century phrasings are PROVISIONAL pending owner sign-off (4.6 §11 Q1).
"""

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Audience, AudienceTier

#: The fixed-in-code Medienart→Dokumenttyp vocabulary (owner Q1, v1). Insertion order is the render
#: order of both the Medienart select and the dependent-Dokumenttyp optgroups. German UI values.
MEDIENART_DOKUMENTTYP: dict[str, tuple[str, ...]] = {
    "Schriftgut": ("Brief", "Bericht", "Protokoll", "Rundschreiben", "Urkunde"),
    "Fotografie": ("Porträt", "Gruppenbild", "Landschaft", "Lageraufnahme"),
    "Karte": ("Wanderkarte", "Lageplan", "Geländeskizze"),
    "Plakat": ("Veranstaltungsplakat", "Werbeplakat"),
    "Tondokument": ("Lied", "Rede", "Interview"),
    "Objekt": ("Abzeichen", "Fahne", "Gerät"),
}


def media_types() -> tuple[str, ...]:
    """The Medienart values the select offers, in vocabulary order (the mapping's keys)."""
    return tuple(MEDIENART_DOKUMENTTYP)


def media_type_options() -> tuple[tuple[str, str], ...]:
    """The Medienart ``<select>`` options: the placeholder first (empty value, server-rejected), then
    the vocabulary in order. The 4.7 edit form, the workbench bulk drawer, and the bulk view all
    render the SAME options from here — one source so the placeholder string never drifts."""
    return (("", "— Medienart wählen —"), *((m, m) for m in media_types()))


def document_types_for(media_type: str) -> tuple[str, ...]:
    """The Dokumenttyp values belonging to ``media_type``, or ``()`` for an unknown/empty one."""
    return MEDIENART_DOKUMENTTYP.get(media_type, ())


def is_valid_pair(media_type: str | None, document_type: str | None) -> bool:
    """Is the (Medienart, Dokumenttyp) pair well-formed? A ``None`` Dokumenttyp is always valid (the
    field is optional). A present Dokumenttyp must belong to a present Medienart's list — the
    server-side re-validation that rejects a mismatched pair even with JS off (spec §5, §8)."""
    if document_type is None:
        return True
    if media_type is None:
        return False
    return document_type in document_types_for(media_type)


def grouped_document_type_options() -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """The dependent Dokumenttyp options as ``(medienart_label, ((value, caption), ...))`` tuples —
    one ``<optgroup>`` per Medienart carrying ALL its types. The no-JS baseline renders every group
    (spec §5), so an archivist without JS can still pick a valid pair; the server re-validates."""
    return tuple(
        (media_type, tuple((t, t) for t in types))
        for media_type, types in MEDIENART_DOKUMENTTYP.items()
    )


# --- Sichtbarkeit (audience) German labels -----------------------------------------

#: The German Sichtbarkeit rung captions — the ONE source for the ladder's user-facing words. Every
#: audience-label helper across the web slice (the archivist ledger, the CAS diff, the publish
#: preview, the read-only Bestand row) formats from these, so a wording change is a one-place edit and
#: the strings can never drift between screens. ``SICHTBARKEIT_ERBEN`` is the ADR-0001 inherit default.
SICHTBARKEIT_ERBEN = "Vom Bestand erben"
SICHTBARKEIT_PUBLIC = "Öffentlich"
SICHTBARKEIT_MEMBERS = "Alle Mitglieder"


def groups_label(groups: tuple[str, ...]) -> str:
    """The GROUPS-rung caption: ``Gruppe: <name>, <name>``. The one place the group list is joined."""
    return "Gruppe: " + ", ".join(groups)


def sichtbarkeit_label(audience: Audience | None) -> str:
    """An ``Audience`` (or ``None`` = inherit) as its human-German Sichtbarkeit caption. Shared by the
    4.7 CAS diff and the 4.8 read-only Bestand row (both hold an ``Audience | None``); the ledger and
    the publish preview, which start from other shapes, reuse the same rung strings above."""
    if audience is None:
        return SICHTBARKEIT_ERBEN
    match audience.tier:
        case AudienceTier.PUBLIC:
            return SICHTBARKEIT_PUBLIC
        case AudienceTier.MEMBERS:
            return SICHTBARKEIT_MEMBERS
        case AudienceTier.GROUPS:
            return groups_label(audience.groups)


# --- EDTF -> German echo -----------------------------------------------------------

#: EDTF season codes -> German season word (spec open-question 2; seasons 21-24).
_SEASONS: dict[str, str] = {"21": "Frühjahr", "22": "Sommer", "23": "Herbst", "24": "Winter"}

#: EDTF month numbers -> German month name (01-12), for the 4.6 detail-page date presentation
#: ("1958-07" -> "Juli 1958"). PROVISIONAL: the exact phrasing awaits owner sign-off (4.7 Q2 /
#: 4.6 §11 Q1); centralized here so a sign-off change is one edit in this file, never in a template.
_MONTHS: dict[str, str] = {
    "01": "Januar",
    "02": "Februar",
    "03": "März",
    "04": "April",
    "05": "Mai",
    "06": "Juni",
    "07": "Juli",
    "08": "August",
    "09": "September",
    "10": "Oktober",
    "11": "November",
    "12": "Dezember",
}


def edtf_to_german(date: EdtfDate | None) -> str:
    """Render an already-validated ``EdtfDate`` to a human-German echo sentence fragment (spec §5).

    A DISPLAY helper only: an absent date yields ``""`` (no echo), and any form this small mapping
    does not phrase falls back to the verbatim EDTF value — the echo is never an error surface, so it
    stays neutral body text. Handles the common Level 0/1 shapes the archivist types: plain year,
    decade (``197X`` → ``1970er``), qualifiers (``~`` → ``um``, ``?`` → ``(unsicher)``), and closed
    intervals (``A/B`` → ``A bis B``). Open intervals and unspecified centuries echo verbatim."""
    if date is None:
        return ""
    value = date.value
    if "/" in value:
        left, _, right = value.partition("/")
        if left and right and right != ".." and left != "..":
            return f"{_single_to_german(left)} bis {_single_to_german(right)}"
        return value  # open-ended interval: echo verbatim (no clean two-sided phrasing)
    return _single_to_german(value)


def _single_to_german(token: str) -> str:
    """One EDTF token (no ``/``) → German. Strips a trailing qualifier and re-attaches its phrasing.
    Falls back to the verbatim token for any shape not explicitly phrased."""
    qualifier = token[-1] if token and token[-1] in "?~%" else ""
    core = token[:-1] if qualifier else token
    phrased = _core_to_german(core)
    if qualifier == "~":
        return f"um {phrased}"
    if qualifier == "?":
        return f"{phrased} (unsicher)"
    if qualifier == "%":
        return f"{phrased} (unsicher, etwa)"
    return phrased


def _core_to_german(core: str) -> str:
    """The qualifier-stripped core token → German. Decade (``197X`` → ``1970er``), century
    (``19XX`` → ``1900-1999`` with a typographic en-dash), month (``1958-07`` → ``Juli 1958``),
    season (``1962-21`` → ``Frühjahr 1962``); anything else (plain year, open interval) echoes
    verbatim — the archivist reads the digits directly, no lossy re-phrasing.

    The month/century phrasings are PROVISIONAL (owner sign-off pending, 4.6 §11 Q1); the strings
    live in ``_MONTHS`` so a change is one edit here."""
    if len(core) == 4 and core[:3].isdigit() and core[3] == "X":
        return f"{core[:3]}0er"  # decade — check before century (197X vs 19XX)
    if len(core) == 4 and core[:2].isdigit() and core[2:] == "XX":
        return f"{core[:2]}00\N{EN DASH}{core[:2]}99"  # century, en-dash range
    if len(core) == 7 and core[4] == "-":
        year, month = core[:4], core[5:]
        if month in _MONTHS:
            return f"{_MONTHS[month]} {year}"
        if month in _SEASONS:
            return f"{_SEASONS[month]} {year}"
    return core
