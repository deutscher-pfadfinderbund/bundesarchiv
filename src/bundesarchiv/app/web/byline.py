"""A linked value of a byline line, as ``components/byline_links.html`` prints it."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BylineLink:
    """One link: its text, its href, an ``aria_label`` when the text alone is too thin, and
    ``new_tab`` for a link to a file."""

    label: str
    href: str
    aria_label: str = ""
    new_tab: bool = False
