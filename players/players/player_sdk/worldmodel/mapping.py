"""mapping.py — remembered-world maps under partial observability.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries. Merges the
map/POI bookkeeping that the original sm-policies stack grew three times:
``swgy_memory.is_stale`` (the staleness primitive), ``mas_memory.
SharedWorldMap`` (monotonic tag-union map), and the POI registry of
``dedicated_runtime.SharedRuntime`` (here generalized to ``PoiMap``; its
game-specific ``PoiKind`` enum, element tables, and junction-ledger side
effects did not port — kinds are a caller-supplied type parameter and kind
transitions surface through a hook instead).

Three pieces:

* :func:`is_stale` — generic staleness predicate that gates against
  ghost-POI chasing. Free function so it works against any record with a
  ``last_seen_step`` field.
* :class:`WorldMap` — union of cell tags reported by any number of agents
  observing in a **shared frame** (see ``worldmodel.frames``). A cell's tag
  set grows monotonically: once any agent sees a static tag at a cell, that
  fact stays true even when later observations only show transient overlays.
  Walls are tracked separately as a fast lookup for path planners.
* :class:`Poi` / :class:`PoiMap` — a registry of remembered *points of
  interest*, generic over the caller's kind type (an enum, a string — any
  hashable). ``upsert`` refreshes tags/kind/last-seen in place and reports
  kind transitions (e.g. a captured objective flipping owner) through the
  optional ``on_kind_change`` callback, keeping game reactions out of the
  library.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Hashable, Iterator, TypeVar

Coordinate = tuple[int, int]

K = TypeVar("K", bound=Hashable)

__all__ = ["Coordinate", "Poi", "PoiMap", "WorldMap", "is_stale"]


def is_stale(last_seen_step: int, current_step: int, ttl: int) -> bool:
    """``(current_step - last_seen_step) > ttl``.

    Free function so any record with a ``last_seen_step`` field can be aged
    without conforming to a library-specific shape.
    """
    return (current_step - last_seen_step) > ttl


class WorldMap:
    """Union map of cell tags reported by frame-anchored agents.

    A cell's tag set grows monotonically; walls are tracked separately as a
    fast lookup for path planners. Coordinates are in whatever shared frame
    the callers agree on (see ``worldmodel.frames``).
    """

    def __init__(self) -> None:
        self._tags: dict[Coordinate, set[int]] = {}
        self._last_seen: dict[Coordinate, int] = {}
        self._walls: set[Coordinate] = set()

    def record(
        self,
        cell: Coordinate,
        observed_tag_ids: set[int],
        step: int,
        wall_tag_ids: frozenset[int],
    ) -> None:
        cell_tags = self._tags.setdefault(cell, set())
        cell_tags.update(observed_tag_ids)
        self._last_seen[cell] = step
        if observed_tag_ids & wall_tag_ids:
            self._walls.add(cell)

    def cells_with_any_tag(
        self,
        include: frozenset[int],
        require: frozenset[int] | None = None,
        exclude: frozenset[int] | None = None,
    ) -> list[tuple[Coordinate, set[int]]]:
        """Return ``(cell, tags)`` pairs matching the filter.

        Caller does ranking by distance / freshness / claim status, since
        those depend on the calling agent's own frame and the live claim
        state.
        """
        results: list[tuple[Coordinate, set[int]]] = []
        for cell, cell_tags in self._tags.items():
            if not (cell_tags & include):
                continue
            if require and not (cell_tags & require):
                continue
            if exclude and (cell_tags & exclude):
                continue
            results.append((cell, cell_tags))
        return results

    def last_seen(self, cell: Coordinate) -> int | None:
        return self._last_seen.get(cell)

    @property
    def walls(self) -> set[Coordinate]:
        return self._walls

    def clear(self) -> None:
        self._tags.clear()
        self._last_seen.clear()
        self._walls.clear()


@dataclass
class Poi(Generic[K]):
    """One remembered cell: where it is, what kind of thing it is, the tag
    ids last seen on it, and when. Coordinates are in the callers' shared
    frame. ``kind`` is whatever hashable vocabulary the caller uses (an
    IntEnum, a string, ...)."""

    cell: Coordinate
    kind: K
    tags: frozenset[int]
    last_seen_step: int

    def is_stale(self, step: int, ttl: int) -> bool:
        """Aged out? ``ttl <= 0`` disables staleness (never stale)."""
        if ttl <= 0:
            return False
        return is_stale(self.last_seen_step, step, ttl)


class PoiMap(Generic[K]):
    """Registry of remembered points of interest, keyed by shared-frame cell.

    ``on_kind_change(cell, old_kind, new_kind, step)`` is invoked whenever an
    ``upsert`` changes an existing POI's kind — the hook is where a policy
    reacts to ownership flips (score a loss, arm a re-capture bonus, ...)
    without that game logic living here.
    """

    def __init__(
        self,
        on_kind_change: Callable[[Coordinate, K, K, int], None] | None = None,
    ) -> None:
        self._pois: dict[Coordinate, Poi[K]] = {}
        self._on_kind_change = on_kind_change

    def upsert(
        self, cell: Coordinate, kind: K, tags: frozenset[int], step: int
    ) -> Poi[K]:
        """Insert or refresh a POI at ``cell``, updating kind/tags/last-seen
        in place so existing references stay live."""
        existing = self._pois.get(cell)
        if existing is None:
            poi = Poi(cell, kind, tags, step)
            self._pois[cell] = poi
            return poi
        if existing.kind != kind and self._on_kind_change is not None:
            self._on_kind_change(cell, existing.kind, kind, step)
        existing.kind = kind
        existing.tags = tags
        existing.last_seen_step = step
        return existing

    def get(self, cell: Coordinate) -> Poi[K] | None:
        return self._pois.get(cell)

    def all_of_kind(self, *kinds: K) -> list[Poi[K]]:
        wanted = set(kinds)
        return [p for p in self._pois.values() if p.kind in wanted]

    def values(self) -> Iterator[Poi[K]]:
        return iter(self._pois.values())

    def forget(self, cell: Coordinate) -> None:
        """Drop a POI (e.g. observed to no longer exist)."""
        self._pois.pop(cell, None)

    def clear(self) -> None:
        self._pois.clear()

    def __contains__(self, cell: Coordinate) -> bool:
        return cell in self._pois

    def __len__(self) -> int:
        return len(self._pois)
