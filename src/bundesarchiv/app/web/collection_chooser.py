"""THE Bestand chooser: one per-request answer to "which Bestände may this be filed into?".

Every Bestand ``<select>`` on the archivist's surface — the create step, the record card, the
Eltern-Bestand row of the Bestand form, the bulk chooser's Bestand widget — and every
server-side check of a submitted Bestand value reads ONE of these, so the ordering, the placeholder
wording, the refusal and the membership rule cannot drift apart again (debt #7).

The rules it owns:

- ONE ordering: by name, ulid breaking a tie — the archivist reads names, not creation order.
- One placeholder per ROLE, both verbatim user contract: ``options`` leads with a placeholder that
  is always refused, ``parent_options`` with the top-level marker, whose empty value is a VALID
  choice (a top-level Bestand has no parent). That difference is the reason for two methods.
- No existence oracle: empty, malformed and well-formed-but-unknown are one ``False`` carrying one
  ``error()``, so a POST can never learn whether a Bestand it may not have exists.

Its lifetime is ONE request: ``of`` reads the Collection set at most once and only when something is
actually asked, so a render that shows no chooser and resolves no name pays no read. Never a
process-level cache — a Bestand created in this request must be choosable in the next one.
"""

from collections.abc import Callable, Mapping

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import Collection, Ulid

#: The Eltern-Bestand top-level marker — a Bestand with no parent. Public because the Bestand form's
#: read-only parent row displays it too, and the two may not drift.
TOP_LEVEL_LABEL = "Oberste Ebene"

_PLACEHOLDER = "— Bestand wählen —"
_REFUSAL = "Bitte einen Bestand wählen."

#: A ``<select>``'s options as the templates loop over them: ``(value, caption)``.
type Options = tuple[tuple[str, str], ...]


class CollectionChooser:
    """The Bestände offered to a form, and the rules for choosing one."""

    __slots__ = ("_load", "_loaded")

    def __init__(self, load: Callable[[], tuple[Collection, ...]]) -> None:
        """Wrap the Collection loader; it is called at most once. Views use ``of`` — a caller that
        already holds a set passes ``lambda: collections``."""
        self._load = load
        self._loaded: dict[Ulid, Collection] | None = None

    @classmethod
    def of(cls, archive: Archive) -> CollectionChooser:
        """This request's chooser over the archive's Collections."""
        return cls(archive.collections.load_all)

    def by_ulid(self) -> Mapping[Ulid, Collection]:
        """Every saved Bestand keyed by ulid — the whole set, for the callers that need Collections
        rather than options."""
        if self._loaded is None:
            self._loaded = {c.ulid: c for c in self._load()}
        return self._loaded

    def chain_of(self, collection_id: Ulid) -> ResolvedChain | None:
        """The Bestand chain above ``collection_id``, leaf first, or ``None`` when it does not
        resolve (unknown, orphaned, cyclic). ``None`` is THE publish gate: no chain, no exposure
        statement, no publishing."""
        try:
            return resolve_chain(collection_id, self.by_ulid())
        except DomainError:
            return None

    def names(self) -> Mapping[Ulid, str]:
        """ULID → name for every saved Bestand — how a screen showing raw collection values (the
        Bestand facet) resolves them."""
        return {ulid: c.name for ulid, c in self.by_ulid().items()}

    def options(self) -> Options:
        """The Bestand select: the placeholder (empty value, always refused) then every Bestand."""
        return (("", _PLACEHOLDER), *self._by_name())

    def parent_options(self) -> Options:
        """The Eltern-Bestand select: the top-level marker (empty value — a real choice, not a
        refusal) then every Bestand."""
        return (("", TOP_LEVEL_LABEL), *self._by_name())

    def accepts(self, raw: str) -> bool:
        """Whether ``raw`` names a Bestand that may be filed into. Surrounding whitespace is stripped
        first, like every other form value."""
        return raw.strip() in self.by_ulid()

    def error(self) -> str:
        """THE refusal an unaccepted value earns, on every surface."""
        return _REFUSAL

    def name_of(self, ulid: str) -> str | None:
        """The Bestand's name, or ``None`` when the ulid names none — the caller decides what an
        unresolvable value shows; this never raises."""
        found = self.by_ulid().get(ulid.strip())
        return found.name if found is not None else None

    def _by_name(self) -> Options:
        collections = sorted(self.by_ulid().values(), key=lambda c: (c.name, c.ulid))
        return tuple((c.ulid, c.name) for c in collections)
