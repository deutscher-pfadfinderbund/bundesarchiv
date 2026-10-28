"""A throwaway design-system tree for the Status rule: an inventory document at its real place
(``docs/design/design-system.md``) beside a ``design-system/`` contract directory."""

from pathlib import Path

LAYOUT = "layouts"
COMPONENT = "components"


def link(directory: str, stem: str) -> str:
    return f"[contract](../../design-system/{directory}/{stem}.md)"


def contract(contract_id: str = "button", status: str = "discoverable") -> str:
    return f"---\nid: {contract_id}\ndescription: A button.\nstatus: {status}\nsources: []\n---\n\nBody.\n"


def project(
    root: Path,
    *,
    components: tuple[str, ...] = ("proposed",),
    families: tuple[str, ...] = ("proposed",),
    layouts: tuple[str, ...] = ("approved (2026-10-11)",),
    contracts: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Write the document (one table row per Status cell given) and the contracts
    (``{"components/button": text}``); return the document and the contract root."""
    document = root / "docs" / "design" / "design-system.md"
    document.parent.mkdir(parents=True)
    component_rows = "\n".join(
        f"| Button {n} | `.b{n}` | inline | `components.css` b | {cell} |"
        for n, cell in enumerate(components)
    )
    family_rows = "\n".join(
        f"| Group {n} | `.b0` | `components.css` g | {cell} |" for n, cell in enumerate(families)
    )
    layout_rows = "\n".join(
        f"| Frame {n} | `.f{n}` | page | `layouts.css` f | {cell} |"
        for n, cell in enumerate(layouts)
    )
    document.write_text(
        "### Component inventory\n\n"
        "| Component | Root | Template | CSS section | Status |\n|---|---|---|---|---|\n"
        f"{component_rows}\n\n"
        "### Families\n\n"
        "| Family | Members | CSS section | Status |\n|---|---|---|---|\n"
        f"{family_rows}\n\n"
        "### Layout primitives\n\n"
        "| Primitive | Class | Where | CSS section | Status |\n|---|---|---|---|---|\n"
        f"{layout_rows}\n"
    )
    design_system = root / "design-system"
    for name, text in (contracts or {}).items():
        path = design_system / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return document, design_system
