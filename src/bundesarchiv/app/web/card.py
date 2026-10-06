"""THE field registry of the record card (debt #2).

The form's fields, declared ONCE, in DOM/tab order: what each one is called, where it sits, how it
renders, how it is seeded from an Article and how the CAS diff spells it. Every derivation is a
filter over it, and so is the form's own markup (``card_fields`` → ``workbench/_field.html``), so the
template holds no second enumeration. The columns are guarded against the real render or the real
behaviour — tests/app/web/test_catalog_edit.py, "the field registry's columns".
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from django.urls import reverse

from bundesarchiv.app.web import catalog, vocab
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.domain.models import Article, Lifecycle


def _audience_label(article: Article) -> str:
    """The stored audience as a human-German label for the CAS diff (inherit / rung / groups) — the
    shared ``vocab`` formatter fed the article's own audience."""
    return vocab.audience_label(article.audience)


def _seed_tags(article: Article) -> str:
    return "\n".join(article.tags)


def _seed_date(article: Article) -> str:
    return vocab.date_mono(article.date)


def _seed_groups(article: Article) -> str:
    return "\n".join(article.audience.groups) if article.audience is not None else ""


def _lifecycle_label(article: Article) -> str:
    return "Entwurf" if article.lifecycle is Lifecycle.DRAFT else "Veröffentlicht"


def _seed_lifecycle(article: Article) -> str:
    return article.lifecycle.value


#: The Status select (a1 round 4): the POST value is the Lifecycle's own value.
LIFECYCLE_OPTIONS: tuple[tuple[str, str], ...] = (
    (Lifecycle.PUBLISHED.value, "Veröffentlicht"),
    (Lifecycle.DRAFT.value, "Entwurf (nur Archivare)"),
)
LIFECYCLE_VALUES = frozenset(value for value, _ in LIFECYCLE_OPTIONS)


@dataclass(frozen=True, slots=True)
class _Field:
    """One row of the form's field registry.

    ``section`` is the part of the form that holds the field: ``lead`` (the heading field),
    ``margin`` (the record's margin), a body section, or ``""`` for the rows that are not on the form
    at all — a single string, so "a field lives in at most one section" is structural.

    ``control`` is what the form renders for it: ``text``, ``select`` (flat options), ``groups``
    (optgrouped options), ``textarea``, or ``""`` for a row that is no control. A row with a control
    carries a scalar form value — it is seeded, re-rendered from the POST and printed by that column
    alone.

    ``scanned`` marks the cataloguing spine the GET autofocus walks for its first EMPTY field (spec
    §5). Gruppen is deliberately NOT on it: it is empty on almost every record by design (it means
    something only at the GROUPS rung), so "first empty field" would park the caret there on every
    fully catalogued record.

    ``focusable`` marks every field with its own input, i.e. every field that can CARRY
    ``autofocus`` — the spine plus Gruppen, since a validation re-render focuses whatever errored.
    ``body`` is excluded (the prose is not an "empty field" in the field sense) and so are the custom
    bag's inputs (the escape hatch).

    ``span`` gives the field the whole row of its section's grid (long values).

    ``shows_with`` names the option value of a sibling select that makes the field meaningful
    (Gruppen: ``groups``); the stylesheet hides the field otherwise, keyed on the data attribute.

    ``required`` marks a field the save refuses blank; ``archivist_only`` one no viewer outside the
    archivists ever sees. Both put a marker after the label (the minority is marked). ``help`` is the
    template of the popover the hint's ⓘ opens, or ``""`` for a hint without one.

    ``suggest`` names the route whose fragment offers the archive's own values for the line being
    typed (catalog_form.js), or ``""`` for a field that suggests nothing.

    ``diff`` is the German label the CAS conflict notice names the field by, or ``""`` when a
    conflict never marks it.

    ``seed``/``shown`` are the two renderings of the field's value, reached through ``value_of`` and
    ``diff_of``; both default to the Article attribute of the same name, so only a field that does not
    simply print one — the joined tuples, the audience's two spellings, the lifecycle word — declares
    anything here.
    """

    name: str
    label: str = ""
    control: str = ""
    section: str = ""
    hint: str = ""
    options: str = ""
    blank: str = ""
    element_id: str = ""
    hx: tuple[tuple[str, str], ...] = ()
    hx_get: str = ""
    span: bool = False
    shows_with: str = ""
    required: bool = False
    archivist_only: bool = False
    help: str = ""
    suggest: str = ""
    scanned: bool = False
    focusable: bool = False
    diff: str = ""
    seed: Callable[[Article], str] | None = None
    shown: Callable[[Article], str] | None = None

    def value_of(self, article: Article) -> str:
        """The field's form value for a stored Article: its own ``seed`` where it declares one, else
        the Article attribute of the same name — ``""`` when unset (spec §8)."""
        if self.seed is not None:
            return self.seed(article)
        return str(getattr(article, self.name) or "")

    @property
    def control_id(self) -> str:
        """The id of the field's control on the edit form, as its ``CardRow`` prints it."""
        return CardRow(self.name, self.label, element_id=self.element_id).control_id

    def diff_of(self, article: Article) -> str:
        """The field's value as the CAS diff prints it — ``shown`` where the form's own spelling is
        the wrong one to put in front of a human, else the form value."""
        return self.shown(article) if self.shown is not None else self.value_of(article)


#: Every field of the form in DOM/tab order: the lead, the margin, then the body sections.
#: ``custom`` is the ``errors`` key for the bag as a whole (it maps to no single input, so it is
#: neither scanned nor focusable); ``custom_key``/``custom_value`` are its inputs, rendered by the
#: bag's own row loop.
FIELDS: tuple[_Field, ...] = (
    _Field(
        "title",
        label="Titel",
        control="text",
        section="lead",
        required=True,
        scanned=True,
        focusable=True,
        diff="Titel",
    ),
    _Field(
        "lifecycle",
        label="Status",
        control="select",
        section="margin",
        options="lifecycle_options",
        diff="Status",
        seed=_seed_lifecycle,
        shown=_lifecycle_label,
    ),
    _Field(
        "audience",
        label="Sichtbar für",
        control="select",
        section="margin",
        options="audience_options",
        diff="Sichtbarkeit",
        seed=lambda article: vocab.audience_value(article.audience),
        shown=_audience_label,
    ),
    _Field(
        "groups",
        label="Gruppen",
        control="textarea",
        section="margin",
        hint="Eine Gruppe pro Zeile",
        shows_with="groups",
        focusable=True,
        seed=_seed_groups,
    ),
    # Bestand has no diff row: a bulk/CAS diff of collection MOVES is its own surface, not this one.
    _Field(
        "collection_id",
        label="Bestand",
        control="select",
        section="core",
        required=True,
        options="collection_options",
        scanned=True,
        focusable=True,
    ),
    _Field(
        "ref_code",
        label="Signatur",
        control="text",
        section="core",
        scanned=True,
        focusable=True,
        diff="Signatur",
    ),
    _Field(
        "physical_location",
        label="Standort",
        control="text",
        section="core",
        span=True,
        archivist_only=True,
        scanned=True,
        focusable=True,
        diff="Standort",
    ),
    _Field(
        "body",
        label="Beschreibung",
        control="textarea",
        section="description",
        diff="Beschreibung",
    ),
    _Field(
        "media_type",
        label="Medienart",
        control="select",
        section="filing",
        required=True,
        options="media_type_options",
        # On change, swap in the dependent Dokumenttyp options. No-JS baseline unchanged: the full
        # grouped optgroup list + server pairing re-validation still stand.
        hx_get="article-document-types",
        hx=(
            ("hx-trigger", "change"),
            ("hx-target", "#document-type-select"),
            ("hx-swap", "innerHTML"),
        ),
        scanned=True,
        focusable=True,
        diff="Medienart",
    ),
    _Field(
        "document_type",
        label="Dokumenttyp",
        control="groups",
        section="filing",
        options="document_type_groups",
        blank="— kein Dokumenttyp —",
        element_id="document-type-select",
        scanned=True,
        focusable=True,
        diff="Dokumenttyp",
    ),
    _Field(
        "tags",
        label="Schlagworte",
        control="textarea",
        section="filing",
        hint="Ein Schlagwort pro Zeile",
        suggest="tag-suggestions",
        span=True,
        scanned=True,
        focusable=True,
        diff="Schlagworte",
        seed=_seed_tags,
    ),
    _Field(
        "creator",
        label="Autor",
        control="text",
        section="provenance",
        scanned=True,
        focusable=True,
        diff="Autor",
    ),
    _Field(
        "subject_place",
        label="Ort",
        control="text",
        section="provenance",
        scanned=True,
        focusable=True,
        diff="Ort",
    ),
    _Field(
        "date",
        label="Datierung",
        control="text",
        section="provenance",
        hint="z. B. 1962, 1984/1995, 1970~",
        help="workbench/_date_help.html",
        scanned=True,
        focusable=True,
        diff="Datierung",
        seed=_seed_date,
    ),
    _Field("custom", section="more"),
    _Field("custom_key", section="more"),
    _Field("custom_value", section="more"),
)


def first_empty_field(values: dict[str, object]) -> str:
    """The first field of the cataloguing spine (DOM order) whose value is empty — the fresh-edit
    autofocus target (spec §5). Falls back to Titel when every field is filled."""
    for field in FIELDS:
        if field.scanned and not str(values.get(field.name) or "").strip():
            return field.name
    return "title"


def first_error_field(errors: catalog.FormErrors) -> str:
    """The first errored field in DOM order that can carry the focus — the validation-re-render
    autofocus target (spec §5). ``custom`` maps to no single input, so it focuses nothing (empty)."""
    for field in FIELDS:
        if field.focusable and field.name in errors:
            return field.name
    return ""


#: What a card ``<select>`` renders: flat ``(value, caption)`` rows, or one ``(group, rows)`` pair per
#: ``<optgroup>``. Which one a field takes is its ``control`` (``select`` / ``groups``).
type _Options = tuple[tuple[str, str], ...] | tuple[tuple[str, tuple[tuple[str, str], ...]], ...]


@dataclass(frozen=True, slots=True)
class CardRow:
    """One field of the form, ready to render: the registry's declaration joined to THIS render's
    value, error, conflict and focus. ``workbench/_field.html`` prints it and nothing else, so a field
    is on the form exactly when the registry says so. ``was`` is the winner's stored value when a
    CAS conflict touches the field, else ``None``. A row built outside the registry (the Bestand
    forms) sets only what it uses."""

    name: str
    label: str
    control: str = "text"
    value: str = ""
    hint: str = ""
    error: str = ""
    was: str | None = None
    autofocus: bool = False
    options: _Options = ()
    blank: str = ""
    hx: tuple[tuple[str, str], ...] = ()
    span: bool = False
    shows_with: str = ""
    required: bool = False
    archivist_only: bool = False
    help: str = ""
    suggest: str = ""
    element_id: str = ""
    prefix: str = "field"

    @property
    def base(self) -> str:
        """The stem of the ids around the control (label, hint, error), unique on the page."""
        return f"{self.prefix}-{self.name}"

    @property
    def control_id(self) -> str:
        """The id of the control: the registry's ``element_id`` where it declares one."""
        return self.element_id or self.base

    def in_panel(self, panel: str) -> CardRow:
        """This field in the tool panel ``panel``: its ids carry the panel's, so a page may hold the
        panel beside a form of its own."""
        return replace(self, prefix=panel, element_id="")


def card_fields(
    values: Mapping[str, object],
    chooser: CollectionChooser,
    *,
    errors: catalog.FormErrors,
    autofocus: str,
    conflicts: Mapping[str, str] | None = None,
    audience_options: _Options = vocab.AUDIENCE_OPTIONS,
    lifecycle_options: _Options = LIFECYCLE_OPTIONS,
    only: tuple[str, ...] | None = None,
) -> dict[str, tuple[CardRow, ...]]:
    """The form's fields grouped by section, in DOM order — the ONE list the template loops over.
    ``only`` limits it to the fields of those names (the create step renders two).

    Only ``focusable`` rows can carry the caret, so a target the registry does not mark focusable
    focuses nothing rather than nothing-visible."""
    option_lists: dict[str, Callable[[], _Options]] = {
        "collection_options": chooser.options,
        "media_type_options": vocab.media_type_options,
        "document_type_groups": vocab.grouped_document_type_options,
        "audience_options": lambda: audience_options,
        "lifecycle_options": lambda: lifecycle_options,
    }
    ulid = str(values.get("ulid") or "")
    conflicts = conflicts or {}
    sections: dict[str, list[CardRow]] = {}
    for registered in FIELDS:
        if not registered.control or (only is not None and registered.name not in only):
            continue
        value = str(values.get(registered.name) or "")
        hx = registered.hx
        if registered.hx_get:
            hx = (("hx-get", reverse(registered.hx_get, args=[ulid])), *hx)
        sections.setdefault(registered.section, []).append(
            CardRow(
                name=registered.name,
                label=registered.label,
                control=registered.control,
                element_id=registered.element_id,
                value=value,
                hint=registered.hint,
                error=errors.get(registered.name, ""),
                was=conflicts.get(registered.name),
                autofocus=registered.focusable and registered.name == autofocus,
                options=option_lists[registered.options]() if registered.options else (),
                blank=registered.blank,
                hx=hx,
                span=registered.span,
                shows_with=registered.shows_with,
                required=registered.required,
                archivist_only=registered.archivist_only,
                help=registered.help,
                suggest=reverse(registered.suggest) if registered.suggest else "",
            )
        )
    return {name: tuple(rows) for name, rows in sections.items()}
