"""Navigation data model: walkability grid + nav-mesh (nodes, edges).

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift; original module ``swgy_base.nav.model``).

This is the robust, ergonomic surface a policy uses. It carries *meaning*
(tags, weights, queries) but knows nothing about how the mesh was built --
the offline ``builder`` subpackage emits a simple interchange and ``io.py`` ingests it.

Coordinates are map/world pixels (the same frame the protocol world model uses,
``camera = -map_obj.x, -map_obj.y``). Tags are free-form strings and edge
weights are floats, so future vent/door edges drop in without a format change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# Nodes tagged during the offline build carry their room in the ``room:`` tag
# namespace (e.g. ``room:Reactor``). A mesh rebuilt from a bare walk grid has no
# such tags, so anything reading rooms must treat "none" as normal, not an error.
ROOM_TAG_PREFIX = "room:"


def _rooms_of(tags) -> list[str]:
    """Room names embedded in a node's tags (``room:<name>`` -> ``<name>``)."""
    return [
        t[len(ROOM_TAG_PREFIX) :]
        for t in tags
        if t.startswith(ROOM_TAG_PREFIX) and t[len(ROOM_TAG_PREFIX) :]
    ]


@dataclass
class NavGrid:
    """Packed-bit walkability bitmap, LSB-first (``walks.bin`` layout).

    Bit ``i`` is pixel ``(x = i % width, y = i // width)``; set => walkable.
    """

    width: int
    height: int
    bits: bytes  # ceil(width*height / 8) bytes

    def __post_init__(self) -> None:
        expected = (self.width * self.height + 7) // 8
        if len(self.bits) != expected:
            raise ValueError(
                f"NavGrid bits length {len(self.bits)} != expected {expected} "
                f"for {self.width}x{self.height}"
            )

    def is_walkable(self, x: int, y: int) -> bool:
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            return False
        i = y * self.width + x
        return bool((self.bits[i >> 3] >> (i & 7)) & 1)

    def to_mask(self) -> np.ndarray:
        """Return a ``(height, width)`` bool array of walkability."""
        count = self.width * self.height
        unpacked = np.unpackbits(np.frombuffer(self.bits, dtype=np.uint8), bitorder="little")[
            :count
        ]
        return unpacked.reshape(self.height, self.width).astype(bool)

    @classmethod
    def from_mask(cls, mask: np.ndarray) -> NavGrid:
        """Build a grid from a ``(height, width)`` truthy walkability array."""
        if mask.ndim != 2:
            raise ValueError(f"mask must be 2-D (height, width), got {mask.ndim}-D")
        height, width = mask.shape
        bits = np.packbits(mask.astype(bool).reshape(-1), bitorder="little")
        return cls(width=width, height=height, bits=bits.tobytes())


@dataclass(frozen=True)
class NavNode:
    """A waypoint at map-pixel ``(x, y)`` carrying free-form tags.

    ``exposure`` and ``witnesses`` are optional visibility coefficients baked on
    by the offline visibility pass (``None`` when the mesh predates that pass).
    ``exposure`` in ``[0, 1]`` is the fraction of nearby *walkable* area visible
    from here under the engine's line-of-sight (``1`` = wide open, ``0`` =
    enclosed; vision *restriction* is ``1 - exposure``). ``witnesses`` counts the
    other nodes that have line-of-sight to this one. See
    ``builder.visibility``.
    """

    id: int
    x: int
    y: int
    tags: frozenset[str] = field(default_factory=frozenset)
    exposure: float | None = None
    witnesses: int | None = None


@dataclass(frozen=True)
class NavEdge:
    """A weighted connection ``src -> dst``. Undirected unless ``directed``."""

    src: int
    dst: int
    weight: float
    directed: bool = False
    tags: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class TaskStation:
    """A static task location (one per ``task`` rect), at map-pixel ``(x, y)``."""

    id: int
    x: int
    y: int
    room: str | None = None
    name: str = ""


@dataclass(frozen=True)
class Vent:
    """A static vent location (one per ``vent`` rect), at map-pixel ``(x, y)``.

    ``group`` is the engine's teleport-connectivity cluster (the ``vent:<n>`` tag):
    an imposter can travel between vents that share a group. Centres are the exact
    rect centres the engine uses (matching ``WorldState.vents``), not the grid-snapped
    ``vent``-tagged nav nodes.
    """

    id: int
    x: int
    y: int
    room: str | None = None
    group: str = ""


@dataclass(frozen=True)
class VisReading:
    """Baked visibility at a queried point, resolved to the nearest nav node.

    ``exposure`` in ``[0, 1]`` (``1`` = the most-open spot on the map) and
    ``witnesses`` (count of other nodes with line-of-sight to here) come from the
    offline visibility pass; ``distance`` is how far the query point sat
    from the resolving node. Low exposure / few witnesses == easy to be killed
    unseen or cornered alone. See ``builder.visibility``.
    """

    node_id: int
    x: int
    y: int
    exposure: float
    witnesses: int
    distance: float

    @property
    def restriction(self) -> float:
        """How vision-restricted (hidden) the spot is: ``1 - exposure``."""
        return 1.0 - self.exposure


def points_toward(
    origin: tuple[int, int],
    bearing: tuple[float, float],
    candidates,
    half_angle_deg: float = 20.0,
    max_dist: float | None = None,
):
    """Candidates lying within an angular cone of ``bearing`` from ``origin``.

    ``bearing`` is a direction vector (need not be unit). Each candidate is a
    ``(x, y)`` pair or an object with ``.x``/``.y``. Returns the candidates whose
    bearing from ``origin`` is within ``half_angle_deg`` of ``bearing``, sorted
    best-aligned first, then nearest first. Frame-independent in direction: a
    bearing measured in screen coords ranks world-coord candidates correctly.
    """
    ox, oy = origin
    bx, by = bearing
    blen = math.hypot(bx, by)
    if blen == 0.0:
        return []
    cos_thresh = math.cos(math.radians(half_angle_deg))
    scored = []
    for c in candidates:
        cx, cy = (c.x, c.y) if hasattr(c, "x") else c
        vx, vy = cx - ox, cy - oy
        d = math.hypot(vx, vy)
        if d == 0.0 or (max_dist is not None and d > max_dist):
            continue
        cos_a = (vx * bx + vy * by) / (d * blen)
        if cos_a < cos_thresh:
            continue
        scored.append((c, cos_a, d))
    scored.sort(key=lambda t: (-t[1], t[2]))  # most-aligned, then nearest
    return [c for c, _cos, _d in scored]


class NavMesh:
    """Walkability grid + tagged, weighted waypoint graph with ergonomic queries."""

    def __init__(
        self,
        grid: NavGrid,
        nodes: list[NavNode],
        edges: list[NavEdge],
        meta: dict | None = None,
        tasks: list[TaskStation] | None = None,
        vents: list[Vent] | None = None,
    ) -> None:
        self.grid = grid
        self.nodes = nodes
        self.edges = edges
        self.meta = meta or {}
        self.tasks = tasks or []
        self.vents = vents or []
        self._by_id: dict[int, NavNode] = {n.id: n for n in nodes}
        # Adjacency: node id -> list of (neighbor id, weight, tags). An
        # undirected edge contributes both directions.
        self._adj: dict[int, list[tuple[int, float, frozenset[str]]]] = {n.id: [] for n in nodes}
        for e in edges:
            self._adj.setdefault(e.src, []).append((e.dst, e.weight, e.tags))
            if not e.directed:
                self._adj.setdefault(e.dst, []).append((e.src, e.weight, e.tags))
        # Node coordinates as an array for vectorized nearest-node queries.
        self._coords = (
            np.array([(n.x, n.y) for n in nodes], dtype=np.int64)
            if nodes
            else np.empty((0, 2), dtype=np.int64)
        )

    def __len__(self) -> int:
        return len(self.nodes)

    def node(self, node_id: int) -> NavNode:
        return self._by_id[node_id]

    def neighbors(self, node_id: int) -> list[tuple[int, float, frozenset[str]]]:
        """Outgoing ``(neighbor_id, weight, tags)`` for ``node_id``."""
        return self._adj.get(node_id, [])

    def nodes_with_tag(self, tag: str) -> list[NavNode]:
        return [n for n in self.nodes if tag in n.tags]

    # --- rooms (derived from the ``room:`` node-tag namespace) --------------

    def rooms(self) -> list[str]:
        """Distinct room names carried by node tags (``room:<name>``), sorted.

        Rooms come from the ``room:`` tags the offline build stamps on nodes. A
        mesh rebuilt from a bare walk grid (no tagger) carries none, so this
        returns ``[]`` -- callers should treat "no rooms" as normal, not an error.
        """
        return sorted({r for n in self.nodes for r in _rooms_of(n.tags)})

    def room_nodes(self, room: str) -> list[NavNode]:
        """Nodes tagged as belonging to ``room`` (empty if unknown/untagged)."""
        return [n for n in self.nodes if room in _rooms_of(n.tags)]

    def room_centroid(self, room: str) -> tuple[int, int] | None:
        """Integer centroid ``(x, y)`` of ``room``'s nodes, or ``None`` if it has none.

        The mean of the room's node positions -- granularity-independent: it works
        at any mesh density and returns ``None`` for a room no node carries (e.g.
        one dropped when the graph was coarsened, or on an untagged rebuild), so it
        never raises. The centroid snaps to the nearest node only if you ask
        (``nearest_node(*centroid)``); on a non-convex room the raw mean may land
        on a wall, which is fine as a routing goal (``find_path`` snaps it).
        """
        ns = self.room_nodes(room)
        if not ns:
            return None
        return (round(sum(n.x for n in ns) / len(ns)), round(sum(n.y for n in ns) / len(ns)))

    def room_centroids(self) -> dict[str, tuple[int, int]]:
        """Every known room mapped to its centroid (see :meth:`room_centroid`)."""
        return {r: c for r in self.rooms() if (c := self.room_centroid(r)) is not None}

    def room_graph(self) -> dict[str, set[str]]:
        """Room adjacency: each room -> the rooms directly reachable from it.

        A *quotient* of the nav graph. Rooms never share a nav edge directly
        (they connect through corridor nodes), so we assign every node to its
        nearest room -- a multi-source BFS over the walkable edges seeded from all
        room-tagged nodes -- and make two rooms neighbours wherever their claimed
        territories touch across an edge. Corridors thus become the connective
        tissue between the rooms they border, giving a sparse, map-faithful graph
        (on the origin game's Croatoan map, Storage Deck came out as the central hub).

        A policy can plan at the room level (BFS/shortest-path over this dict) for a
        legible named route, then hand each leg to :func:`find_path`.

        Granularity-independent (it runs off whatever nodes/edges exist) and fails
        soft: a mesh with no room tags -- e.g. one rebuilt from a bare walk grid --
        has no rooms, so this returns ``{}``. The graph is symmetric and self-loop
        free.
        """
        from collections import deque

        rooms = self.rooms()
        graph: dict[str, set[str]] = {r: set() for r in rooms}
        if not rooms:
            return graph

        # Multi-source BFS: owner[node] = nearest room by hop count; ties go to the
        # first room to reach the node (deterministic given node/edge order).
        owner: dict[int, str | None] = {n.id: None for n in self.nodes}
        seen: set[int] = set()
        queue: deque[int] = deque()
        for n in self.nodes:
            claimed = _rooms_of(n.tags)
            if claimed:
                owner[n.id] = claimed[0]
                seen.add(n.id)
                queue.append(n.id)
        while queue:
            u = queue.popleft()
            for nid, _w, _t in self._adj.get(u, ()):
                if nid not in seen:
                    seen.add(nid)
                    owner[nid] = owner[u]
                    queue.append(nid)

        for e in self.edges:
            a, b = owner.get(e.src), owner.get(e.dst)
            if a and b and a != b:
                graph[a].add(b)
                graph[b].add(a)
        return graph

    def nearest_node(self, x: int, y: int) -> int | None:
        """Id of the node closest (Euclidean) to ``(x, y)``, or None if empty."""
        if len(self._coords) == 0:
            return None
        d = self._coords - np.array((x, y), dtype=np.int64)
        idx = int(np.argmin((d * d).sum(axis=1)))
        return self.nodes[idx].id

    def is_walkable(self, x: int, y: int) -> bool:
        return self.grid.is_walkable(x, y)

    @property
    def bounds(self) -> tuple[int, int]:
        return self.grid.width, self.grid.height

    def tasks_toward(
        self,
        origin: tuple[int, int],
        bearing: tuple[float, float],
        half_angle_deg: float = 20.0,
        max_dist: float | None = None,
    ) -> list[TaskStation]:
        """Task stations along a UI task-arrow ``bearing`` from ``origin``.

        Turns the on-screen arrow clue into candidates: pass the player's world
        position and the arrow direction (``arrow_pos - my_screen_pos``) to get
        the task stations consistent with that arrow, best-aligned first.
        """
        return points_toward(origin, bearing, self.tasks, half_angle_deg, max_dist)

    def task_node(self, task: TaskStation) -> int | None:
        """Nearest nav node to a task station (where a policy routes to)."""
        return self.nearest_node(task.x, task.y)

    def vent_node(self, vent: Vent) -> int | None:
        """Nearest nav node to a vent (where a policy routes to reach it)."""
        return self.nearest_node(vent.x, vent.y)

    # --- baked visibility (builder.visibility) -----------------------------

    @property
    def has_visibility(self) -> bool:
        """True iff nodes carry baked exposure/witnesses (see ``builder.visibility``)."""
        return bool(self.nodes) and self.nodes[0].exposure is not None

    def visibility_at(self, x: int, y: int) -> VisReading | None:
        """Baked visibility at ``(x, y)``, resolved to the nearest node.

        Returns ``None`` if the mesh is empty or carries no visibility data. Snaps
        to the nearest node (cheap, per-node granularity), so a policy can read the
        risk of its current spot each tick: low ``exposure`` / few ``witnesses``
        means easy to be killed unseen or cornered alone with a sus crewmate.
        """
        nid = self.nearest_node(x, y)
        if nid is None:
            return None
        n = self._by_id[nid]
        if n.exposure is None or n.witnesses is None:
            return None
        return VisReading(
            node_id=n.id,
            x=n.x,
            y=n.y,
            exposure=n.exposure,
            witnesses=n.witnesses,
            distance=math.hypot(n.x - x, n.y - y),
        )

    def exposure_at(self, x: int, y: int) -> float | None:
        """Baked exposure (0..1, 1 = most open) at the nearest node, or None."""
        r = self.visibility_at(x, y)
        return None if r is None else r.exposure

    def witnesses_at(self, x: int, y: int) -> int | None:
        """Baked witness count at the nearest node to ``(x, y)``, or None."""
        r = self.visibility_at(x, y)
        return None if r is None else r.witnesses

    def nodes_by_exposure(
        self,
        *,
        max_exposure: float | None = None,
        min_exposure: float | None = None,
    ) -> list[NavNode]:
        """Nodes whose baked exposure lies within ``[min_exposure, max_exposure]``.

        Either bound is optional; nodes without visibility data are skipped. Handy
        for routing toward cover (``max_exposure=0.3``) or open ground
        (``min_exposure=0.7``).
        """
        out = []
        for n in self.nodes:
            e = n.exposure
            if e is None:
                continue
            if max_exposure is not None and e > max_exposure:
                continue
            if min_exposure is not None and e < min_exposure:
                continue
            out.append(n)
        return out
