"""THE Collection chooser: one per-request answer to "which Collections may this be filed into?".

Every Collection ``<select>`` on the archivist's surface — the create step, the record card, the bulk
chooser's Collection widget — and every server-side check of a submitted Collection value reads ONE of
these, so the ordering, the placeholder wording, the refusal and the membership rule cannot drift
apart again (debt #7).

The rules it owns:

- ONE ordering: by name, ulid breaking a tie — the archivist reads names, not creation order.
- One placeholder, verbatim user contract: ``options`` leads with a placeholder that is always
  refused.
- No existence oracle: empty, malformed and well-formed-but-unknown are one ``False`` carrying one
  ``error()``, so a POST can never learn whether a Collection it may not have exists.

Its lifetime is ONE request: ``of`` reads the Collection set at most once and only when something is
actually asked, so a render that shows no chooser and resolves no name pays no read. Never a
process-level cache — a Collection created in this request must be choosable in the next one.
"""

from collections.abc import Callable, Mapping

from bundesarchiv.app.archive import Archive
from bundesarchiv.domain.collections import ResolvedChain, resolve_chain
from bundesarchiv.domain.errors import DomainError
from bundesarchiv.domain.models import ULID, Collection

_PLACEHOLDER = "— Sammlungsteil wählen —"
_REFUSAL = "Bitte einen Sammlungsteil wählen."

#: A ``<select>``'s options as the templates loop over them: ``(value, caption)``.
type Options = tuple[tuple[str, str], ...]


class CollectionChooser:
    """The Collections offered to a form, and the rules for choosing one."""

    __slots__ = ("_load", "_loaded")

    def __init__(self, load: Callable[[], tuple[Collection, ...]]) -> None:
        """Wrap the Collection loader; it is called at most once. Views use ``of`` — a caller that
        already holds a set passes ``lambda: collections``."""
        self._load = load
        self._loaded: dict[ULID, Collection] | None = None

    @classmethod
    def of(cls, archive: Archive) -> CollectionChooser:
        """This request's chooser over the archive's Collections."""
        return cls(archive.collections.load_all)

    def by_ulid(self) -> Mapping[ULID, Collection]:
        """Every saved Collection keyed by ulid — the whole set, for the callers that need Collections
        rather than options."""
        if self._loaded is None:
            self._loaded = {c.ulid: c for c in self._load()}
        return self._loaded

    def chain_of(self, collection_id: ULID) -> ResolvedChain | None:
        """The Collection chain above ``collection_id``, leaf first, or ``None`` when it does not
        resolve (unknown, orphaned, cyclic). ``None`` is THE publish gate: no chain, no exposure
        statement, no publishing."""
        try:
            return resolve_chain(collection_id, self.by_ulid())
        except DomainError:
            return None

    def names(self) -> Mapping[str, str]:
        return {ulid: c.name for ulid, c in self.by_ulid().items()}

    def options(self) -> Options:
        """The Collection select: the placeholder (empty value, always refused) then every Collection."""
        return (("", _PLACEHOLDER), *self._by_name())

    def resolve(self, raw: str) -> ULID | None:
        """The ulid of the Collection ``raw`` names, or ``None``: membership in the saved set is the
        parse. Surrounding whitespace is stripped first, like every other form value."""
        found = self._find(raw)
        return found.ulid if found is not None else None

    def accepts(self, raw: str) -> bool:
        """Whether ``raw`` names a Collection that may be filed into."""
        return self.resolve(raw) is not None

    def error(self) -> str:
        """THE refusal an unaccepted value earns, on every surface."""
        return _REFUSAL

    def name_of(self, raw: str) -> str | None:
        """The name of the Collection ``raw`` names, or ``None`` — the caller decides what an
        unresolvable value shows; this never raises."""
        found = self._find(raw)
        return found.name if found is not None else None

    def _find(self, raw: str) -> Collection | None:
        return self.by_ulid().get(ULID(raw.strip()))

    def _by_name(self) -> Options:
        collections = sorted(self.by_ulid().values(), key=lambda c: (c.name, c.ulid))
        return tuple((c.ulid, c.name) for c in collections)
