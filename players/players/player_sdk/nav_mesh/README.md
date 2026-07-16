# player_sdk.nav_mesh — continuous/pixel-world navigation with inertia

Waypoint-mesh navigation for continuous worlds where movement carries
momentum: A* routing that understands per-axis speed clamping, and a
follower that exploits inertia instead of fighting it. Plus the offline
`builder/` that turns any walkability mask into a mesh. numpy only (already
a `players` dependency); opt-in — not re-exported from `players.player_sdk`.

## The pieces

| Module | Provides |
|--------|----------|
| `model` | `NavGrid` (packed-bit walkability), `NavNode`/`NavEdge`/`NavMesh` (tagged weighted graph + queries: `nearest_node`, `nodes_with_tag`, room queries over the `room:` tag namespace, `room_graph`), optional per-node visibility (`exposure`/`witnesses`, `VisReading`), `TaskStation`/`Vent` semantic overlays, `points_toward` cone matching |
| `astar` | `find_path(mesh, start, goal, params) -> NavPlan` — binary-heap A* whose edge metric blends Euclidean *length* with Chebyshev *travel time* via `diagonal_bias` (engines that clamp velX/velY independently traverse a diagonal in `max(|dx|,|dy|)` ticks); soft/hard `avoid_tags` |
| `plan` | `NavPlan` — frozen route; compute once, follow for many ticks |
| `follow` | `NavState` — the inertia follower: cursor advance with cluster collapse, **bang-bang hold-to-waypoint + release-and-coast arrival**, wall bump-and-dodge (`grid` probe over 8 directions), soft crew-separation steer, bounding-box stuck detection with replan signal |
| `params` | `NavParams` — the tuning surface, with `# GA bounds` comments consumable by `player_sdk.tuning.compose.genome_from_dataclass` |
| `io` | canonical two-file binary format (`<name>.walk` + `<name>.graph`, zlib, byte-reproducible; versioned, v2–v4 loadable) + JSON-interchange ingest; compile CLI: `python -m players.player_sdk.nav_mesh compile in.json out.walk out.graph` |
| `builder/` | offline: `build.build_graph(mask, ...)` (lattice + Bresenham corridor checks + union-find stitching + bridge routing + subdivision), `visibility` (engine-faithful truncate-toward-zero DDA line-of-sight; `SightParams` frame profile), `interchange` (the JSON seam; `pack_bits`) |

## The contract that matters

Read the **"CONTRACT FOR POLICIES"** docstring in `follow.py` before writing
movement code. Summary: give the follower ONE destination; `heading() ==
(0, 0)` is the *only* arrival signal; never brake, never act on mere
proximity, never jitter the destination per tick. The follower releases the
controls within `arrival_radius` of the final goal so residual velocity
coasts to a stop *on* it — braking and "settling" logic on top of it
re-accelerates and overshoots. (The origin project's league losses from
violating this are documented in that docstring.)

## Typical wiring

```python
from players.player_sdk import nav_mesh as nav

mesh = nav.load_mesh("map.walk", "map.graph")        # built offline, see below
state = nav.NavState(params=nav.NavParams(), grid=mesh.grid)

# per tick:
if state.plan is None or state.needs_replan:
    state.replan(mesh, me_xy, goal_xy_or_node)
state.update(me_xy)
dx, dy = state.heading(me_xy, others=teammates_xy, collision=me_collision)
if (dx, dy) == (0, 0):
    ...  # arrived: do the at-destination action
else:
    ...  # map (dx, dy) signs to your engine's input encoding
```

Building a mesh for a new map (offline, once):

```python
import numpy as np
from players.player_sdk.nav_mesh import builder

mask = ...  # bool HxW walkability
nodes, edges = builder.build_graph(mask, builder.BuildParams(grid=14, edge_max=30))
nodes, _ = builder.enrich_nodes(nodes, wall_mask, mask)      # optional LOS pass
obj = builder.build_interchange(mask, builder.BuildParams(), nodes, edges)
builder.write_interchange(obj, "map.json")
# then: python -m players.player_sdk.nav_mesh compile map.json map.walk map.graph
```

The JSON interchange is a deliberate seam: the builder never imports the
runtime model (guarded by a test), so either side can evolve independently.

Coordinate hygiene for pixel worlds: read `docs/coordinate_frames.md` (the
"(7,7) gotcha") before writing range checks.

## Origin

Extracted from Ron Dahlgren's (swgy) agent libraries — swgy-crewrift's
`swgy_base.nav` (runtime) and `swgy_tools.navmesh` (builder). Changes in the
port: the never-read `NavParams.max_speed`/`slow_radius` fields and the dead
`_axis_button`/`_axis_unit` velocity-error helpers were removed (docstrings
now describe the control law that actually shipped); the Croatoan map asset,
its room enum, and `load_default_mesh` stayed with the origin game; the
visibility pass's screen constants became `SightParams` (defaults = the
byte-faithful reference profile). Binary magics (`SWGYWALK`/`SWGYGRAF`) and
the `"swgy-navmesh-interchange"` format string are kept byte-identical so
existing assets remain loadable. The origin's 70-odd nav tests are ported to
`validation/players-tests/test_nav_mesh*.py`.

### Related in-repo prior art (not modified)

`players/players/crewrift/crewborg/nav.py` solves the same problem for the
same origin game with a different architecture (coarse node graph +
pixel-resolution string-pulling); this package is the reusable,
game-decoupled path.
