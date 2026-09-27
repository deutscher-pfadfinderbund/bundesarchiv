"""Controlled vocabulary + the human-German date (Part 4.7, spec §3/§4).

Two pure presentation helpers, IO-free and request-free so the form controller and its tests read
one source with no database:

- ``MEDIENART_DOKUMENTTYP`` — the Medienart→Dokumenttyp vocabulary. The words are the ARCHIVISTS'
  data, not a design decision: ``MEDIENARTEN`` and ``DOKUMENTTYPEN`` are the legacy archive's own
  lists, verbatim and in legacy order, so the imported records keep the terms their catalogers
  wrote. Every Medienart offers the whole Dokumenttyp list until the archivists narrow it; the
  mapping, not the accessors, is what changes then. It sits behind ``media_types`` /
  ``document_types_for`` / ``is_valid_pair`` / ``grouped_document_type_options`` — ONE accessor set
  so the dependent-select render (no-JS baseline), the server-side pair re-validation, and the HTMX
  ``/dokumenttypen`` endpoint never derive the vocabulary twice.
- ``edtf_to_german`` — the 4.6 detail-page date presentation (the sentence under the title). It
  reads the already-validated ``EdtfDate`` value object; an absent date yields ``""``. It stays a
  DISPLAY helper: it never validates (the field's error path owns that), so it can only ever return
  neutral body text, never an error. Its month/century phrasings are PROVISIONAL pending owner
  sign-off (4.6 §11 Q1).
"""

from bundesarchiv.domain.edtf import EdtfDate
from bundesarchiv.domain.models import Audience, AudienceTier

#: The Medienarten, verbatim and in the legacy archive's order — the words its catalogers used.
MEDIENARTEN: tuple[str, ...] = (
    "Audiodatei",
    "Buch",
    "CD / DVD",
    "Dia(s)",
    "Fahne / Wimpel",
    "Filmspule",
    "Foto(s)",
    "Gegenstand",
    "Kassette",
    "Schallplatte",
    "Schrifttum",
    "Sonstiges",
    "Stempel",
    "Tonband",
    "VHS",
    "Videodatei",
    "Wappen und Zeichen",
)

#: The Dokumenttypen, verbatim and in the legacy lookup table's order.
DOKUMENTTYPEN: tuple[str, ...] = (
    "Adressverzeichnis",
    "Chronik / Dokumentation",
    "Fahrtenbericht",
    "Kalender",
    "Lagerheft",
    "Lebensbericht",
    "Liederbuch",
    "Ordnung",
    "Protokoll",
    "Reden",
    "Schöpferisches (Gedicht, Lieder, ...)",
    "Schriftwechsel",
    "Sonstiges",
    "Zeitschrift",
    "Zeitungsartikel",
    "Urkunde",
)

#: Medienart → the Dokumenttypen it offers. Insertion order is the render order of the Medienart
#: select. Uniform today: narrowing a Medienart is the archivists' call, and until they make it no
#: legacy pair can be refused by a narrowing nobody asked for.
MEDIENART_DOKUMENTTYP: dict[str, tuple[str, ...]] = dict.fromkeys(MEDIENARTEN, DOKUMENTTYPEN)

#: The single optgroup's label while every Medienart shares one Dokumenttyp list.
ALLE_MEDIENARTEN = "Alle Medienarten"


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
    """The dependent Dokumenttyp options as ``(label, ((value, caption), ...))`` tuples — the
    ``<optgroup>``s of the no-JS baseline, which renders every choice so an archivist without JS can
    still pick a valid pair (spec §5); the server re-validates either way.

    While every Medienart offers the same list there is ONE group: 17 identical optgroups would be
    noise, not guidance. Once the archivists narrow a Medienart the grouping is per Medienart again.
    """
    offered = set(MEDIENART_DOKUMENTTYP.values())
    if len(offered) == 1:
        return ((ALLE_MEDIENARTEN, tuple((t, t) for t in offered.pop())),)
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
#: The GROUPS rung's caption where no group NAMES are known yet — the Sichtbarkeit ``<select>``'s own
#: option, chosen together with the Gruppen field. ``groups_label`` spells the same rung once the
#: names exist; both live here so the form's option list is not a second source (law C7).
SICHTBARKEIT_GRUPPEN = "Gruppe(n)"


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


# --- EDTF: the two spellings, one renderer each (law C7) ---------------------------


def datierung_mono(date: EdtfDate | None) -> str:
    """The MACHINE date: the EDTF value verbatim, or ``""`` when absent. The ONE renderer for the
    mono machine spelling — the ledger's date column, the preview pane's meta line, the detail record
    card's mono row, the CAS diff and the Datierung field's own value all print it, so a single
    spelling of the fact cannot fork into inline copies of ``date.value if date is not None else
    ""``. Its sibling is ``edtf_to_german`` — the HUMAN spelling, the other licensed rendering of the
    same fact."""
    return date.value if date is not None else ""


# --- EDTF -> German ----------------------------------------------------------------

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
    """Render an already-validated ``EdtfDate`` to a human-German sentence fragment.

    A DISPLAY helper only: an absent date yields ``""``, and any form this small mapping does not
    phrase falls back to the verbatim EDTF value — it is never an error surface, so it stays neutral
    body text. Handles the common Level 0/1 shapes the archivist types: plain year, decade (``197X``
    → ``1970er``), qualifiers (``~`` → ``um``, ``?`` → ``(unsicher)``), and closed intervals (``A/B``
    → ``A bis B``). Open intervals and unspecified centuries print verbatim."""
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
