"""The small forms as tool panels: the header's "+ Neu …" panel.

A leaf: it imports no view module, so ``viewers.render_screen`` builds the header's panels and the
routes print the same forms as pages (debt #24).
"""

from dataclasses import dataclass

from django.urls import reverse

from bundesarchiv.app.web.card import CardRow, card_fields
from bundesarchiv.app.web.catalog import FormErrors
from bundesarchiv.app.web.collection_chooser import CollectionChooser


@dataclass(frozen=True, slots=True)
class FormPanel:
    """A small form as a tool panel (``workbench/_formpanel.html``): its fields and its one
    button."""

    id: str
    action: str
    rows: tuple[CardRow, ...]
    button: str

    @property
    def fields(self) -> tuple[CardRow, ...]:
        """The rows as this panel prints them, with the panel's ids."""
        return tuple(row.in_panel(self.id) for row in self.rows)


def new_article_panel(
    chooser: CollectionChooser,
    *,
    title: str = "",
    collection_id: str = "",
    errors: FormErrors | None = None,
) -> FormPanel:
    """The create step as the header's "Neuer Artikel" tool panel."""
    return FormPanel(
        id="new-article",
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
