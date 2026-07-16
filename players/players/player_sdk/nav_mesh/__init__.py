"""Continuous/pixel-world navigation: walkability grid + tagged nav-mesh,
inertia-aware routing and following, with I/O and an offline mesh builder.

The data model a policy uses to path across a continuous map:

    NavGrid   -- packed-bit walkability bitmap (is_walkable, to/from mask)
    NavNode   -- a waypoint at a map pixel, with free-form tags
    NavEdge   -- a weighted (optionally directed) connection, with tags
    NavMesh   -- grid + nodes + edges + queries (nearest_node, neighbors,
                 nodes_with_tag, is_walkable, visibility_at)

Nodes built with the visibility pass (``builder.visibility``) carry baked
line-of-sight coefficients (``exposure`` 0..1 where 1 = most open, and
``witnesses``). Read them per position with ``NavMesh.visibility_at`` /
``exposure_at`` / ``witnesses_at`` (-> ``VisReading``), filter the graph with
``nodes_by_exposure`` to route toward cover / open ground, and gate on
``has_visibility``.

The mesh is *built* by the offline :mod:`.builder` subpackage
(``builder.build.build_graph`` over any walkability mask), which emits a
simple JSON interchange; this package ingests it (``mesh_from_interchange``)
and owns the canonical two-file binary format (``save_mesh`` / ``load_mesh``
over ``<name>.walk`` + ``<name>.graph``). Compile an interchange to canonical
with ``python -m players.player_sdk.nav_mesh compile``.

Routing and following build on the model:

    find_path  -- A* over the mesh -> a cacheable NavPlan (or None)
    NavPlan    -- frozen ordered route; compute once, follow for many ticks
    NavParams  -- tunable knobs: heuristic weight, static-tag avoidance,
                  waypoint arrival, crew separation, stuck detection
    NavState   -- mutable follower: advance along a plan + separation
                  steering + wall bump-and-dodge + stuck/cycle detection

Cache-and-follow: ``find_path`` once, hold the ``NavPlan`` in a ``NavState``,
then per tick ``update(me)`` + ``heading(me, others)``; map the returned
``(dx, dy)`` signs to your engine's input encoding in game code. Movement in
the target engines is acceleration-integrated with steep friction, so the
follower holds toward the current waypoint and releases within
``arrival_radius`` of the final goal -- residual velocity coasts to a stop ON
the goal, and ``heading() == (0, 0)`` is the arrival signal (read the
"CONTRACT FOR POLICIES" in :mod:`.follow` before writing policy movement
code). The tags/weights/directed-edge fields accommodate teleporters and
doors -- but a teleport edge whose weight undercuts its endpoints' euclidean
gap would break A* admissibility (see :mod:`.astar`).

This subpackage is not re-exported from ``players.player_sdk``; import it
explicitly. It needs numpy (already a ``players`` dependency). Origin:
extracted from Ron Dahlgren's (swgy) agent libraries (swgy-crewrift,
``swgy_base.nav`` + ``swgy_tools.navmesh``).
"""

from .astar import find_path
from .follow import NavState
from .io import (
    load_grid,
    load_mesh,
    mesh_from_interchange,
    save_grid,
    save_mesh,
)
from .model import (
    ROOM_TAG_PREFIX,
    NavEdge,
    NavGrid,
    NavMesh,
    NavNode,
    TaskStation,
    Vent,
    VisReading,
    points_toward,
)
from .params import NavParams
from .plan import NavPlan

__all__ = [
    "NavGrid",
    "NavNode",
    "NavEdge",
    "NavMesh",
    "TaskStation",
    "Vent",
    "VisReading",
    "points_toward",
    "ROOM_TAG_PREFIX",
    "mesh_from_interchange",
    "save_mesh",
    "load_mesh",
    "save_grid",
    "load_grid",
    "find_path",
    "NavPlan",
    "NavParams",
    "NavState",
]
