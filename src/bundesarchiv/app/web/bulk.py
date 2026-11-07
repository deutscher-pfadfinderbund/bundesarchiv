from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from bundesarchiv.app import articles
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.result import Conflicted, Missing, Updated
from bundesarchiv.app.web import card, catalog, vocab
from bundesarchiv.app.web.catalog import none_if_blank
from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.domain.models import ULID, Article
from bundesarchiv.persistence.errors import ArchiveError

#: The POST name of the plain text widget, and the one an unknown field's value is read under.
TEXT_INPUT = "value_text"


def _accept(_value: str, _selected: Sequence[Article], _chooser: CollectionChooser) -> str | None:
    return None


def _verbatim(raw: str, _chooser: CollectionChooser) -> str:
    return raw


def _keeps_document_type(_article: Article, _value: str) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class BulkField:
    """One bulk-editable field and its behaviour. ``value_input``: the POST name its value is sent
    under. ``current`` reads the field off an Article. ``validate`` refuses a value against the
    selected Articles (the German refusal) or accepts it (``None``). ``apply`` sets an accepted
    value on one Article. ``display`` spells a raw value as a person reads it.
    ``clears_document_type``: applying the value empties the Article's Dokumenttyp (spec §3).
    ``reads_selection``: ``validate`` or ``clears_document_type`` reads the selected Articles, so a
    commit loads them first."""

    target: str
    plural: str
    value_input: str
    current: Callable[[Article], str | None]
    apply: Callable[[Article, str, CollectionChooser], Article]
    validate: Callable[[str, Sequence[Article], CollectionChooser], str | None] = _accept
    display: Callable[[str, CollectionChooser], str] = _verbatim
    clears_document_type: Callable[[Article, str], bool] = _keeps_document_type
    reads_selection: bool = False

    @property
    def label(self) -> str:
        """A custom-bag key is its own label."""
        return card.LABELS.get(self.target, self.target)

    def counted(self, n: int) -> str:
        """``n`` values, spelled out: "1 Standort", "3 Standorte"."""
        return vocab.numbered(n, self.label, self.plural)

    def shown_new(self, value: str, chooser: CollectionChooser) -> str:
        return self.display(value, chooser) if value.strip() else "(geleert)"

    def shown_current(self, article: Article, chooser: CollectionChooser) -> str:
        """Empty when unset."""
        return self.display(self.current(article) or "", chooser)


def _custom(key: str, plural: str) -> BulkField:
    """A custom-bag key: an empty value removes it. The rebuilt Article runs the domain's
    sort/dedupe/reserved-key guard (spec §1)."""

    def apply(article: Article, value: str, _chooser: CollectionChooser) -> Article:
        custom = {k: v for k, v in article.custom if k != key}
        if cleaned := value.strip():
            custom[key] = cleaned
        return replace(article, custom=tuple(custom.items()))

    return BulkField(key, plural, TEXT_INPUT, lambda a: dict(a.custom).get(key), apply)


def _validate_media_type(
    value: str, _selected: Sequence[Article], _chooser: CollectionChooser
) -> str | None:
    return catalog.parse_media_type(value)[1]


def _media_type_clears(article: Article, value: str) -> bool:
    return article.document_type is not None and not vocab.is_valid_pair(
        none_if_blank(value), article.document_type
    )


def _with_media_type(article: Article, value: str) -> Article:
    """Clears the Dokumenttyp the new Medienart does not admit, never leaving an invalid pair."""
    return replace(
        article,
        media_type=none_if_blank(value),
        document_type=None if _media_type_clears(article, value) else article.document_type,
    )


def _validate_document_type(
    value: str, selected: Sequence[Article], _chooser: CollectionChooser
) -> str | None:
    """All-or-nothing: one selected Article whose Medienart does not admit it refuses the apply."""
    document_type = none_if_blank(value)
    if all(vocab.is_valid_pair(a.media_type, document_type) for a in selected):
        return None
    return (
        f"„{document_type}“ gehört nicht zur Medienart aller ausgewählten Einträge. "
        "Bitte zuerst die Medienart angleichen oder die Auswahl einschränken."
    )


def _validate_collection(
    value: str, _selected: Sequence[Article], chooser: CollectionChooser
) -> str | None:
    return catalog.parse_collection(value, chooser)[1]


def _apply_collection(article: Article, value: str, chooser: CollectionChooser) -> Article:
    collection_id, refusal = catalog.parse_collection(value, chooser)
    if collection_id is None:
        raise ValueError(refusal)
    return replace(article, collection_id=collection_id)


#: In spec §1 order; never ``audience`` or ``lifecycle`` (spec §0.7); a Collection move still changes a published
#: Article's inherited Sichtbarkeit (GitHub #73). One ``replace`` per field, not a ``**`` splat: a
#: splat type-checks as Any and would let a wrong field through.
FIELDS: tuple[BulkField, ...] = (
    BulkField(
        "physical_location",
        "Standorte",
        TEXT_INPUT,
        lambda a: a.physical_location,
        lambda a, v, _: replace(a, physical_location=none_if_blank(v)),
    ),
    BulkField(
        "creator",
        "Autoren",
        TEXT_INPUT,
        lambda a: a.creator,
        lambda a, v, _: replace(a, creator=none_if_blank(v)),
    ),
    BulkField(
        "subject_place",
        "Orte",
        TEXT_INPUT,
        lambda a: a.subject_place,
        lambda a, v, _: replace(a, subject_place=none_if_blank(v)),
    ),
    BulkField(
        "media_type",
        "Medienarten",
        "value_media_type",
        lambda a: a.media_type,
        lambda a, v, _: _with_media_type(a, v),
        validate=_validate_media_type,
        clears_document_type=_media_type_clears,
        reads_selection=True,
    ),
    BulkField(
        "document_type",
        "Dokumenttypen",
        "value_document_type",
        lambda a: a.document_type,
        lambda a, v, _: replace(a, document_type=none_if_blank(v)),
        validate=_validate_document_type,
        reads_selection=True,
    ),
    _custom("Quelle", "Quellen"),
    BulkField(
        "collection_id",
        "Sammlungsteile",
        "value_collection_id",
        lambda a: a.collection_id,
        _apply_collection,
        validate=_validate_collection,
        display=lambda raw, chooser: chooser.name_of(raw) or raw,
    ),
    _custom("Querverweis", "Querverweise"),
    _custom("Besitzer", "Besitzer"),
)

#: An unknown name finds nothing: the view refuses it before anything is read or written.
BY_TARGET: Mapping[str, BulkField] = {f.target: f for f in FIELDS}


#: The Feld ``<select>``'s options: the placeholder first (empty, server-rejected with "Bitte ein
#: Feld wählen."), then every field in spec §1 order.
_FIELD_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", "Feld wählen"),
    *((f.target, f.label) for f in FIELDS),
)

#: value_input → the space-separated targets that widget serves, the chooser's ``data-bulk-value``
#: tokens (layouts.css matches them to show exactly one widget). Derived, never typed out.
_WIDGET_TARGETS: dict[str, str] = {
    value_input: " ".join(f.target for f in FIELDS if f.value_input == value_input)
    for value_input in dict.fromkeys(f.value_input for f in FIELDS)
}


def field_picker_context(
    chooser: CollectionChooser, *, field: str = "", value: str = ""
) -> dict[str, object]:
    """The context of ``workbench/_field_picker.html``; ``field``/``value`` re-echo a submitted
    pair."""
    return {
        "field_picker_field": field,
        "field_picker_value": value,
        "field_picker_field_options": _FIELD_OPTIONS,
        "field_picker_targets": _WIDGET_TARGETS,
        "field_picker_media_type_options": vocab.media_type_options(),
        "field_picker_document_type_groups": vocab.grouped_document_type_options(),
        "field_picker_collection_options": chooser.options(),
    }


# --- the CAS loop + buckets (spec §4) ----------------------------------------------


@dataclass(frozen=True, slots=True)
class BulkRow:
    ulid: ULID
    ref_code: str
    title: str


@dataclass(frozen=True, slots=True)
class BulkOutcome:
    """Every distinct ulid is counted in ``saved`` or listed in ``conflicted`` or ``missing``,
    exactly once."""

    saved: int
    conflicted: tuple[BulkRow, ...]
    missing: tuple[ULID, ...]
    doctype_cleared: tuple[BulkRow, ...]
    index_lagged: bool


class _Unfit(Exception):
    """The freshly loaded Article refuses the value, e.g. its Medienart no longer admits the
    Dokumenttyp (spec §3): it changed since the check page validated, so it is refused unsaved."""


@dataclass
class _FieldApplication:
    """The transform ``update_article`` calls, remembering the article it was handed. The buckets are
    built from that pre-image: a ``conflicted`` row shows the record as it stood, and the cleared-
    Dokumenttyp note is a before/after comparison (spec §4)."""

    field: BulkField
    value: str
    chooser: CollectionChooser
    loaded: Article | None = None

    def __call__(self, article: Article) -> Article:
        self.loaded = article
        if self.field.validate(self.value, (article,), self.chooser) is not None:
            raise _Unfit
        return self.field.apply(article, self.value, self.chooser)


def apply_bulk(
    archive: Archive, ulids: Sequence[ULID], field: BulkField, value: str, *, changed_by: str
) -> BulkOutcome:
    """Never retries: a lost race must reach the human, not be re-applied to the winner."""
    saved = 0
    conflicted: list[BulkRow] = []
    missing: list[ULID] = []
    doctype_cleared: list[BulkRow] = []
    index_lagged = False
    chooser = CollectionChooser.of(archive)
    for ulid in dict.fromkeys(ulids):  # distinct, order-preserving
        mutation = _FieldApplication(field, value, chooser)
        try:
            outcome = articles.update_article(
                archive, ulid, mutation, changed_by=changed_by, retries=0
            )
        except _Unfit, ArchiveError:
            # a value the fresh Article refuses, or a save failure the service does not own
            outcome = Conflicted()
        loaded = mutation.loaded
        if isinstance(outcome, Missing) or loaded is None:
            missing.append(ulid)
            continue
        row = BulkRow(ulid=ulid, ref_code=loaded.ref_code or "", title=loaded.title)
        match outcome:
            case Conflicted():
                conflicted.append(row)
            case Updated(index_updated=index_updated):
                saved += 1
                if field.clears_document_type(loaded, value):
                    doctype_cleared.append(row)
                index_lagged = index_lagged or not index_updated
    return BulkOutcome(
        saved=saved,
        conflicted=tuple(conflicted),
        missing=tuple(missing),
        doctype_cleared=tuple(doctype_cleared),
        index_lagged=index_lagged,
    )
