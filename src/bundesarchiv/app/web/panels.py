"""The small forms as tool panels: the header's "+ Neu …" entries and the Bestand forms' rows.

A leaf: it imports no view module, so ``viewers.render_screen`` builds the header's panels and the
routes print the same forms as pages (debt #24).
"""

from dataclasses import dataclass

from django.urls import reverse

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import vocab
from bundesarchiv.app.web.card import CardRow, card_fields
from bundesarchiv.app.web.catalog import FormErrors
from bundesarchiv.app.web.collection_chooser import TOP_LEVEL_LABEL, CollectionChooser
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Version
from bundesarchiv.persistence.collections import StoredCollection
from bundesarchiv.persistence.errors import ArchiveError


@dataclass(frozen=True, slots=True)
class FormPanel:
    """A small form as a tool panel (``workbench/_formpanel.html``), opened from the header's
    "+ Neu …" by the entry ``label`` (or, with ``in_menu`` off, by a button of the page's own): its fields, its one button, and for a form over a stored record
    the version it was shown for, the record's facts and the conflict notice's ``current_name``."""

    id: str
    label: str
    action: str
    rows: tuple[CardRow, ...]
    button: str
    version: Version | None = None
    facts: tuple[tuple[str, str], ...] = ()
    notice: str = ""
    current_name: str | None = None
    in_menu: bool = True

    @property
    def fields(self) -> tuple[CardRow, ...]:
        """The rows as this panel prints them, with the panel's ids."""
        return tuple(row.in_panel(self.id) for row in self.rows)


def header_panels(chooser: CollectionChooser, *, active: str | None) -> tuple[FormPanel, ...]:
    """The header's forms as tool panels: Neuer Artikel (the Bestand ``aktiver`` preselected, while the
    list is scoped to one) and Neuer Bestand in the "+ Neu …" menu, and in that case Bestand
    bearbeiten, which the list's own button opens. Archivist chrome — the caller
    (``viewers.render_screen``) builds it for archivists only; the routes stay gated on their own."""
    panels = [
        new_article_panel(chooser, collection_id=active or ""),
        new_collection_panel(collection_rows(chooser, "", "", "", "", {})),
    ]
    if active is not None and is_valid_ulid(active):
        try:
            stored = Archive.canonical().collections.load(active)
        except ArchiveError:
            return tuple(panels)
        panels.append(
            edit_collection_panel(chooser, stored, stored.collection.name, {}, stored.version)
        )
    return tuple(panels)


# --- Neuer Artikel ---------------------------------------------------------------------


def new_article_panel(
    chooser: CollectionChooser,
    *,
    title: str = "",
    collection_id: str = "",
    errors: FormErrors | None = None,
) -> FormPanel:
    """The create step as the header's "Neuer Artikel" tool panel."""
    return FormPanel(
        id="neu-artikel",
        label="Neuer Artikel …",
        action=reverse("article-create"),
        rows=article_rows(chooser, title, collection_id, errors or {}),
        button="Anlegen",
    )


def article_rows(
    chooser: CollectionChooser, title: str, collection_id: str, errors: FormErrors
) -> tuple[CardRow, CardRow]:
    """Titel and Bestand from the registry, with the preserved values, the field errors, and the
    server-computed autofocus target (Titel unless it already has a value)."""
    autofocus = "collection_id" if title and "title" not in errors else "title"
    fields = card_fields(
        {"title": title, "collection_id": collection_id},
        chooser,
        errors=errors,
        autofocus=autofocus,
        only=("title", "collection_id"),
    )
    return fields["lead"][0], fields["core"][0]


# --- Neuer Bestand ---------------------------------------------------------------------


def new_collection_panel(rows: tuple[CardRow, ...]) -> FormPanel:
    """The create form as the header's "Neuer Bestand" tool panel."""
    return FormPanel(
        id="neu-bestand",
        label="Neuer Bestand …",
        action=reverse("collection-create"),
        rows=rows,
        button="Anlegen",
    )


def collection_rows(
    chooser: CollectionChooser,
    name: str,
    parent_id: str,
    audience_choice: str,
    groups_text: str,
    errors: FormErrors,
) -> tuple[CardRow, ...]:
    """The create form's fields: preserved values, the parent + Sichtbarkeit options, field errors,
    and the server-computed autofocus (Name, unless it already has a value)."""
    autofocus = "parent_id" if name and "name" not in errors else "name"
    return (
        CardRow(
            "name",
            "Name",
            value=name,
            error=errors.get("name", ""),
            required=True,
            autofocus=autofocus == "name",
        ),
        CardRow(
            "parent_id",
            "Eltern-Bestand",
            control="select",
            value=parent_id,
            error=errors.get("parent_id", ""),
            options=chooser.parent_options(),
            autofocus=autofocus == "parent_id",
        ),
        CardRow(
            "audience",
            "Sichtbarkeit",
            control="select",
            value=audience_choice,
            error=errors.get("audience", ""),
            options=vocab.AUDIENCE_OPTIONS,
        ),
        CardRow(
            "groups",
            "Gruppen",
            control="textarea",
            value=groups_text,
            hint="Eine Gruppe pro Zeile (nur bei Sichtbarkeit „Gruppe(n)“)",
        ),
    )


# --- Bestand bearbeiten ----------------------------------------------------------------


def edit_collection_panel(
    chooser: CollectionChooser,
    stored: StoredCollection,
    name: str,
    errors: FormErrors,
    version: Version | None,
    conflict_name: str | None = None,
) -> FormPanel:
    """The rename form, page and tool panel alike: the editable Name (preserved on re-render) + the
    READ-ONLY parent name + Sichtbarkeit label as facts (this slice edits neither). ``version`` is the
    one the form saves against (ADR 0013); ``conflict_name``, the winner's name, shows the conflict
    notice."""
    collection = stored.collection
    parent_id = collection.parent_id
    return FormPanel(
        id="collection-edit",
        label="Bestand bearbeiten …",
        action=reverse("collection-edit", args=[collection.ulid]),
        rows=(
            CardRow(
                "name",
                "Name",
                value=name,
                error=errors.get("name", ""),
                required=True,
                autofocus=True,
            ),
        ),
        button="Speichern",
        version=version,
        facts=(
            (
                "Eltern-Bestand",
                TOP_LEVEL_LABEL if parent_id is None else chooser.name_of(parent_id) or parent_id,
            ),
            ("Sichtbarkeit", vocab.audience_label(collection.audience)),
        ),
        notice="Verschieben und Sichtbarkeit ändern folgen später.",
        current_name=conflict_name,
        in_menu=False,
    )
