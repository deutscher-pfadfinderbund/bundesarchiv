"""The small forms as tool panels: the header's "+ Neu …" entries and the Bestand forms' rows.

A leaf: it imports no view module, so ``viewers.render_screen`` builds the header's panels and the
routes print the same forms as pages (debt #24).
"""

from dataclasses import dataclass

from django.urls import reverse

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import vocab
from bundesarchiv.app.web.bestand import TOP_LEVEL_LABEL, BestandChooser
from bundesarchiv.app.web.card import CardRow, card_fields
from bundesarchiv.app.web.catalog import FormErrors
from bundesarchiv.domain.identity import is_valid_ulid
from bundesarchiv.domain.models import Version
from bundesarchiv.persistence.collections import StoredCollection
from bundesarchiv.persistence.errors import ArchiveError


@dataclass(frozen=True, slots=True)
class FormPanel:
    """A small form as a tool panel (``workbench/_formpanel.html``), opened from the header's
    "+ Neu …" by the entry ``label``: its fields, its one button, and for a form over a stored record
    the version it was shown for, the record's facts and the conflict notice's ``jetzt``."""

    id: str
    label: str
    action: str
    rows: tuple[CardRow, ...]
    button: str
    version: Version | None = None
    fakten: tuple[tuple[str, str], ...] = ()
    hinweis: str = ""
    jetzt: str | None = None

    @property
    def felder(self) -> tuple[CardRow, ...]:
        """The rows as this panel prints them, with the panel's ids."""
        return tuple(row.in_panel(self.id) for row in self.rows)


def header_panels(bestand: BestandChooser, *, aktiver: str | None) -> tuple[FormPanel, ...]:
    """The "+ Neu …" menu's forms as tool panels, empty: Neuer Artikel, Neuer Bestand, and while the
    list is scoped to the Bestand ``aktiver``, Bestand bearbeiten. Archivist chrome — the caller
    (``viewers.render_screen``) builds it for archivists only; the routes stay gated on their own."""
    panels = [
        neu_artikel_panel(bestand),
        neu_bestand_panel(bestand_rows(bestand, "", "", "", "", {})),
    ]
    if aktiver is not None and is_valid_ulid(aktiver):
        try:
            stored = Archive.canonical().collections.load(aktiver)
        except ArchiveError:
            return tuple(panels)
        panels.append(
            bestand_bearbeiten_panel(bestand, stored, stored.collection.name, {}, stored.version)
        )
    return tuple(panels)


# --- Neuer Artikel ---------------------------------------------------------------------


def neu_artikel_panel(
    bestand: BestandChooser,
    *,
    title: str = "",
    collection_id: str = "",
    errors: FormErrors | None = None,
) -> FormPanel:
    """The create step as the header's "Neuer Artikel" tool panel."""
    return FormPanel(
        id="neu-artikel",
        label="Neuer Artikel …",
        action=reverse("artikel-neu"),
        rows=artikel_rows(bestand, title, collection_id, errors or {}),
        button="Anlegen",
    )


def artikel_rows(
    bestand: BestandChooser, title: str, collection_id: str, errors: FormErrors
) -> tuple[CardRow, CardRow]:
    """Titel and Bestand from the registry, with the preserved values, the field errors, and the
    server-computed autofocus target (Titel unless it already has a value)."""
    autofocus = "collection_id" if title and "title" not in errors else "title"
    fields = card_fields(
        {"title": title, "collection_id": collection_id},
        bestand,
        errors=errors,
        autofocus=autofocus,
        only=("lead", "kerndaten"),
    )
    return fields["lead"][0], next(
        row for row in fields["kerndaten"] if row.name == "collection_id"
    )


# --- Neuer Bestand ---------------------------------------------------------------------


def neu_bestand_panel(rows: tuple[CardRow, ...]) -> FormPanel:
    """The create form as the header's "Neuer Bestand" tool panel."""
    return FormPanel(
        id="neu-bestand",
        label="Neuer Bestand …",
        action=reverse("bestand-neu"),
        rows=rows,
        button="Anlegen",
    )


def bestand_rows(
    bestand: BestandChooser,
    name: str,
    parent_id: str,
    sichtbarkeit: str,
    gruppen: str,
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
            options=bestand.parent_options(),
            autofocus=autofocus == "parent_id",
        ),
        CardRow(
            "sichtbarkeit",
            "Sichtbarkeit",
            control="select",
            value=sichtbarkeit,
            error=errors.get("sichtbarkeit", ""),
            options=vocab.SICHTBARKEIT_OPTIONS,
        ),
        CardRow(
            "gruppen",
            "Gruppen",
            value=gruppen,
            hint="Mehrere durch Komma trennen (nur bei Sichtbarkeit „Gruppe(n)“)",
        ),
    )


# --- Bestand bearbeiten ----------------------------------------------------------------


def bestand_bearbeiten_panel(
    bestand: BestandChooser,
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
        id="bestand-bearbeiten",
        label="Bestand bearbeiten …",
        action=reverse("bestand-bearbeiten", args=[collection.ulid]),
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
        fakten=(
            (
                "Eltern-Bestand",
                TOP_LEVEL_LABEL if parent_id is None else bestand.name_of(parent_id) or parent_id,
            ),
            ("Sichtbarkeit", vocab.sichtbarkeit_label(collection.audience)),
        ),
        hinweis="Verschieben und Sichtbarkeit ändern folgen später.",
        jetzt=conflict_name,
    )
