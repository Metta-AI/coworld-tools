# Navigation System Design

Living design document for the guided_bot hierarchical navigation system.
Replaces the single-layer A* in `action.nim`.

> **Status:** Fully implemented. Runtime code in `navigation.nim`
> (482 LOC) + `action.nim` (429 LOC). Baked data in
> `perception/baked/nav_graph.json` + `nav_paths.bin`. Tools in
> `tools/waypoint_editor.py` + `tools/bake_nav.py`.

---

## 1. Problem Statement

The previous navigation system (`action.nim`) ran A* over the full
952x534 walk mask (508K cells) every time it needs a path. For paths
that required navigating around long walls, A* hit its runtime
expansion cap and returned empty. The bot then fell back to greedy
direct-steering into the wall, where it slides laterally (resetting
stuck detection via non-zero velocity) and never reaches its goal.

In a 3-minute test match, 5 of 6 crewmates spent 65-89% of their time
stuck against walls. The two impostors (which patrol rather than
pathfind to distant goals) were unaffected but also never killed anyone
(separate bug, unrelated to navigation).

## 2. Design Principles

1. **The map is static.** Players do not block each other (`sim.nim`
   confirms: only the walk mask blocks movement). Dead bodies don't
   block either. Therefore all paths are deterministic and can be
   precomputed offline.

2. **No direct wall-steering fallback.** The navigation system must
   always produce a valid path to any reachable destination. If a path
   cannot be found, that is a data error (disconnected waypoint graph)
   to be fixed offline, not papered over at runtime.

3. **Two-level hierarchy.** Strategic planning over a small precomputed
   waypoint graph (85 nodes in the current bake), tactical execution via precomputed
   pixel-paths between adjacent waypoints. Runtime pathfinding cost is
   near-zero.

4. **Ghost and vent special cases.** Ghosts use greedy straight-line
   steering (no obstacles). Impostors can optionally route through
   vents when belief state permits (no witnesses).

5. **Interface-preserving.** The `ActionIntent` struct, `ActionDiscipline`
   enum, and `applyIntent(state, belief, intent): uint8` signature do
   not change. The rebuild is entirely internal to the action layer.

---

## 3. Architecture Overview

```text
Mode layer (unchanged)
    │
    │  ActionIntent { steerTo: Point, discipline: DisciplineNormal, ... }
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  Navigation Layer (new action.nim internals)                    │
│                                                                 │
│  ┌─────────────┐     ┌──────────────┐     ┌────────────────┐  │
│  │  Strategic   │────▶│   Tactical   │────▶│  Mask Emitter  │  │
│  │  Planner     │     │   Follower   │     │                │  │
│  └─────────────┘     └──────────────┘     └────────────────┘  │
│        │                     │                     │            │
│        ▼                     ▼                     ▼            │
│  Waypoint Graph       Precomputed          uint8 button mask   │
│  (baked data)         pixel-paths                              │
│                       (baked data)                              │
└─────────────────────────────────────────────────────────────────┘
```

### 3.1 Strategic Planner

Given a goal point in world coordinates (`steerTo`), determine the
sequence of waypoints to traverse:

1. Find the nearest waypoint to the bot's current position.
2. Find the nearest waypoint to the goal.
3. Run shortest-path (Dijkstra) on the waypoint graph.
4. Return the ordered list of waypoints from current to goal.

The waypoint graph currently has 85 nodes and 277 edges. Dijkstra
completes in microseconds. It is recomputed whenever `steerTo`
changes (new goal) or when the bot arrives at a waypoint and needs the
next segment.

### 3.2 Tactical Follower

Given the current waypoint target (the next waypoint in the strategic
path), follow the precomputed pixel-path from the bot's approximate
position to that waypoint:

1. Look up the precomputed path for the current edge (source waypoint
   -> target waypoint).
2. Find the closest point on that path to the bot's actual position
   (snap-to-path, handles localization drift).
3. Select the lookahead point (18 pixels ahead on the path).
4. Emit direction buttons via the momentum-aware `axisMask` controller
   which uses coast prediction, active braking, and a 2px deadband.

**Waypoint arrival:** The bot has "arrived" at a waypoint when its
position is within `WaypointArrivalRadius` (tunable, default 12px) of
the waypoint center. On arrival, advance to the next segment.

**Hysteresis:** Once the bot commits to heading toward waypoint N+1,
it does not revert to N unless explicitly replanned (goal change).

### 3.3 Mask Emitter

Converts the tactical follower's steering decision into the uint8
button mask. Handles:

- Direction buttons (up/down/left/right combinations)
- Button A/B overlays from the intent
- Meeting cursor (passthrough, non-navigation)
- Discipline dispatch (TaskHold, KillStrike, Report bypass the
  path-following pipeline; NoOp emits zero)

### 3.4 Ghost Mode

When `belief.self.isGhost == true`:
- Skip the waypoint graph entirely
- Steer directly toward `steerTo` (greedy straight-line)
- No walk mask, no path following
- Maximum speed in all directions

### 3.5 Vent Routing (Impostor)

Vents are modeled as conditional edges in the waypoint graph:

- Each vent location is a waypoint node
- Vent connections (same group, sequential index) are edges with near-
  zero cost but a traversal condition: `role == impostor AND
  canVentSafely(belief)`
- `canVentSafely` checks: no visible crewmates within a radius (the
  witnesses check)
- When the strategic planner includes a vent edge, the tactical
  follower:
  1. Navigates to the vent entry waypoint
  2. On arrival (within VentRange=16px), emits ButtonB to activate
  3. After teleport (position jumps to destination vent), resumes
     normal path following from the new position

The strategic planner accepts a `ventPolicy` parameter:
- `VentNever` — exclude vent edges (crewmate, or impostor playing safe)
- `VentIfSafe` — include vent edges only if `canVentSafely` is true
  at planning time
- `VentAlways` — always include vent edges (for flee-routing)

---

## 4. Precomputed Data

All navigation data is baked offline (like `walk_mask.bin`,
`map.json`) and loaded at bot init time.

### 4.1 Waypoint Graph (`nav_graph.json`)

```json
{
  "version": 1,
  "waypoints": [
    {
      "id": 0,
      "x": 536, "y": 120,
      "kind": "home",
      "room": "Cafeteria",
      "label": "home"
    },
    {
      "id": 1,
      "x": 524, "y": 131,
      "kind": "button",
      "room": "Cafeteria",
      "label": "emergency_button"
    },
    {
      "id": 5,
      "x": 600, "y": 339,
      "kind": "vent",
      "room": "Coms Hallway",
      "label": "vent_A1",
      "vent_group": "A",
      "vent_index": 1
    },
    ...
  ],
  "edges": [
    {
      "src": 0, "dst": 1,
      "cost": 42,
      "is_vent": false
    },
    {
      "src": 5, "dst": 6,
      "cost": 5,
      "is_vent": true,
      "vent_group": "A"
    },
    ...
  ]
}
```

Waypoint kinds:
- `doorway` — transition between rooms (corridor entrances/exits)
- `intersection` — corridor junction with 3+ exits
- `task` — task station center (passable pixel)
- `vent` — vent center
- `button` — emergency button
- `home` — spawn point
- `poi` — manually-placed point of interest

Edges are bidirectional (stored once; graph is undirected for walking
edges). Vent edges are directional (A1 -> A2 -> A3 -> A1 wraps).

### 4.2 Precomputed Paths (`nav_paths.bin`)

For each non-vent edge in the graph, the full pixel-path (sequence of
(x, y) world coordinates from src waypoint to dst waypoint) computed
via offline 8-connected A* on the walk mask with no node cap.
Corner-cutting is prevented (diagonal moves blocked if either adjacent
cardinal cell is a wall). Costs use 10/14 integer scaling; edge costs
in nav_graph.json are the descaled approximate pixel distance.

Storage format: a binary blob keyed by the non-vent walking edges in
graph edge order.

```text
Header:
  u32  num_walking_edges
  u32  total_points
Per walking edge (in graph edge order):
  u32  offset_into_points
  u16  num_points_in_path
  u16  src_waypoint_id
  u16  dst_waypoint_id
Points array:
  [i16 x, i16 y] * total_points
```

Estimated size: ~80 edges * ~200 avg path length * 4 bytes/point
= ~64 KB. Trivial.

### 4.3 Waypoint Editor Tool (implementation aid)

A Python tool (`tools/waypoint_editor.py`) that:
1. Renders the walk mask as an image
2. Auto-suggests waypoint placements (doorway detection, task
   stations, vents, intersections)
3. Displays edges between connected waypoints
4. Allows manual creation/editing/removal of waypoints via click
5. Validates the graph (connectivity, all tasks reachable)
6. Exports `nav_graph.json`

`tools/bake_nav.py` then computes and exports `nav_paths.bin` from
`nav_graph.json` + `walk_mask.bin`.

---

## 5. Runtime Data Structures

### 5.1 NavGraph (loaded at init)

```nim
type
  WaypointKind* = enum
    WpDoorway, WpIntersection, WpTask, WpVent,
    WpButton, WpHome, WpPoi

  Waypoint* = object
    id*: int
    x*, y*: int
    kind*: WaypointKind
    room*: string
    label*: string
    ventGroup*: char      ## '\0' if not a vent
    ventIndex*: int       ## 0 if not a vent

  NavEdge* = object
    src*, dst*: int       ## waypoint IDs
    cost*: int            ## precomputed walk distance (pixels)
    isVent*: bool
    ventGroup*: char

  NavPath* = object
    ## Precomputed pixel-path for one walking edge. Points go from
    ## src waypoint toward dst waypoint (exclusive of src, inclusive
    ## of dst). Simplified via Douglas-Peucker at bake time.
    src*, dst*: int             ## Waypoint IDs from the baked path record.
    points*: seq[Point]

  NavGraph* = object
    waypoints*: seq[Waypoint]
    edges*: seq[NavEdge]
    paths*: seq[NavPath]       ## Indexed same as edges (walking only).
    ## Acceleration structures built at load time:
    adjacency*: seq[seq[int]]  ## waypoint index -> list of edge indices.
    idToIndex*: seq[int]       ## waypoint ID -> waypoint index, -1 if absent.
    edgeToPathIndex*: seq[int] ## edge index -> paths index, -1 for vent edges.
    waypointCount*: int
```

### 5.2 ActionState (conceptual NavState)

The design originally called this `NavState`, but the implementation
kept the existing exported name `ActionState` so callers did not need
to change. It is the same conceptual navigation state.

```nim
type
  VentPolicy* = enum
    VentNever, VentIfSafe, VentAlways

  ActionState* = object
    ## Strategic state
    currentGoal*: Point
    currentGoalValid*: bool
    strategicPath*: seq[int]       ## waypoint indices, head = next target
    currentEdgeIdx*: int           ## index into NavGraph.edges
    currentEdgeFrom*: int          ## waypoint index departed from
    currentEdgeTo*: int            ## waypoint index being targeted
    ventPolicy*: VentPolicy

    ## Tactical state
    pathProgress*: int             ## index into current edge's NavPath.points
    lastSelfX*, lastSelfY*: int   ## for velocity / drift detection
    lastPlanTick*: int
    lastProgressTick*: int
    lastWaypointDistance*: int
    ventAttemptTicks*: int

    ## Output
    lastEmittedMask*: uint8

    ## Diagnostics
    arrivedAtWaypoint*: bool       ## set on the tick we cross a wp
    navNoopUntilTick*: int         ## defensive pause after nav data errors
    navErrorReason*: string        ## last defensive nav error
    taskHoldTicks*: int            ## counter for TaskHold discipline
```

---

## 6. Algorithm Detail

### 6.1 Per-Tick Flow (DisciplineNormal)

```nim
proc applyIntent(state: var ActionState, belief: Belief, intent: ActionIntent): uint8 =
  if intent.discipline == DisciplineNoOp:    return handleNoOp(intent)
  if intent.discipline == DisciplineTaskHold: return ButtonA
  if intent.discipline == DisciplineKillStrike: return handleKillStrike(...)
  if intent.discipline == DisciplineReport:  return handleReport(...)
  if intent.discipline == DisciplineWander:  return handleWander(...)

  # --- DisciplineNormal: hierarchical navigation ---

  if belief.self.isGhost:
    return ghostSteer(belief, intent)

  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  if not belief.percep.localized:
    return handleWander(...)  # can't navigate without position

  let goalX = intent.steerTo.x
  let goalY = intent.steerTo.y

  # 1. Check if goal changed -> replan strategic path
  if goalChanged(state, goalX, goalY) or periodicReplan or progressStall:
    state.strategicPath = planStrategicPath(
      navGraph, selfX, selfY, goalX, goalY, state.ventPolicy)
    state.currentGoalValid = true
    state.currentGoal = Point(x: goalX, y: goalY)
    advanceToNextEdge(state, navGraph, selfX, selfY)

  # 2. Check waypoint arrival -> advance to next edge
  if arrivedAtCurrentWaypoint(state, navGraph, selfX, selfY):
    if isVentEdge(state, navGraph):
      return handleVentTraversal(state, navGraph, selfX, selfY)
    advanceToNextEdge(state, navGraph, selfX, selfY)

  # 3. Follow the precomputed path for the current edge
  # If the bot starts near, but not on, the baked edge path, first
  # steer back to the edge's start waypoint. This handles localization
  # drift and fixture starts without direct wall steering.
  let target = selectLookahead(state, navGraph, selfX, selfY)
  let mask = steerButtons(selfX, selfY, target.x, target.y)

  # 4. Apply button overrides
  if intent.pressA: mask = mask or ButtonA
  if intent.pressB: mask = mask or ButtonB

  state.lastEmittedMask = mask
  return mask
```

### 6.2 Strategic Planning

```nim
proc planStrategicPath(graph: NavGraph, sx, sy, gx, gy: int,
                       ventPolicy: VentPolicy): seq[int] =
  let startWp = graph.nearestWp(sx, sy)
  let goalWp = graph.nearestWp(gx, gy)

  # Dijkstra on the waypoint graph (85 nodes in the current bake)
  # Filter vent edges based on ventPolicy
  # Returns seq of waypoint IDs from startWp to goalWp (inclusive)
```

### 6.3 Tactical Path Following

```nim
proc selectLookahead(state: ActionState, graph: NavGraph,
                     selfX, selfY: int): Point =
  let edge = graph.edges[state.currentEdgeIdx]
  let path = graph.paths[state.currentEdgeIdx]

  # Snap to nearest point on the path (handle drift)
  let snapIdx = findNearestPathPoint(path, selfX, selfY)

  # Advance pathProgress to at least snapIdx (never go backward)
  state.pathProgress = max(state.pathProgress, snapIdx)

  # Select lookahead point (18 pixels ahead)
  let lookaheadIdx = min(state.pathProgress + PathLookahead, path.points.len - 1)
  var target = path.points[lookaheadIdx]

  # Steer via momentum-aware controller (coast/brake/accelerate per axis)
  return target
```

### 6.4 Waypoint Arrival

```nim
proc arrivedAtCurrentWaypoint(state: ActionState, graph: NavGraph,
                              selfX, selfY: int): bool =
  if state.strategicPath.len == 0: return false
  let targetWp = graph.waypoints[state.strategicPath[0]]
  heuristic(selfX, selfY, targetWp.x, targetWp.y) <= WaypointArrivalRadius
```

### 6.5 Final-Goal Proximity

When the bot is within `WaypointArrivalRadius` of the final
destination (`steerTo`), skip waypoint logic and steer directly to the
exact pixel. This handles the "last meter" — navigating from the last
waypoint to the precise task station position.

### 6.6 Ghost Steering

```nim
proc ghostSteer(belief: Belief, intent: ActionIntent): uint8 =
  if not intent.steerValid: return 0
  steerButtons(belief.percep.selfX, belief.percep.selfY,
               intent.steerTo.x, intent.steerTo.y)
```

### 6.7 Vent Traversal

When the next edge in the strategic path is a vent edge:

1. Navigate to the vent entry waypoint (walk path).
2. On arrival within `VentActivationRadius` (16px, matches server's
   `VentRange`): emit `ButtonB`.
3. Detect teleportation: position jumps discontinuously (distance
   from previous position exceeds threshold). This signals the vent
   was used.
4. After teleport: pop the vent edge from the strategic path, snap to
   the destination vent waypoint, continue with the next walking edge.

If vent activation fails (pressed B but didn't teleport — maybe
cooldown), retry for a few ticks, then replan without vents.

---

## 7. Error Handling (Defensive, Not Fallback)

The system is designed to never need fallback steering. But defensive
checks catch data errors:

| Condition | Response |
|-----------|----------|
| `nearestWp` returns a waypoint >100px away | Log error, emit noop for 12 ticks, retry |
| Strategic path returns empty (disconnected graph) | Log error, steer toward goal naively for diagnostics. This indicates a bake-time graph bug. |
| Path progress overshoots (snapIdx > path.len) | Treat as arrived, advance to next edge |
| Bot position is on an impassable pixel (localization glitch) | Use last known good position, emit noop until relocalised |
| Vent failed after 24 ticks of pressing B | Replan without vents |

None of these are "normal" code paths. They exist to surface bugs
loudly (via trace logging) rather than silently misbehaving.

---

## 8. Tuning Parameters

All in one place (top of `action.nim` or `tuning.nim`):

```nim
const
  # Strategic
  WaypointArrivalRadius* = 12     ## px; bot considers itself "at" a waypoint

  # Tactical
  PathLookahead* = 18             ## Points ahead on path to aim at
  PathSnapRadius* = 30            ## Max distance to snap to path (drift tolerance)
  PerturbationChance* = 0         ## Disabled; perturbation conflicts with momentum control

  # Steering (momentum-aware controller)
  SteerDeadband* = 2              ## px; within this, only brake residual velocity
  BrakeDeadband* = 1              ## Extra pixel tolerance for braking condition
  CoastLookaheadTicks* = 8        ## Ticks of friction simulation for coast prediction
  CoastArrivalPadding* = 1        ## Extra pixel tolerance for coast-arrival check
  StuckFrameThreshold* = 8        ## Frames of zero movement before jiggle triggers
  JiggleDuration* = 16            ## Frames of perpendicular correction when stuck

  # Vent
  VentActivationRadius* = 16     ## Must be within this to press B (server VentRange)
  VentActivationTimeout* = 24    ## Ticks to wait for teleport before replanning

  # Ghost
  ## (none — ghost steering has no tunable params)
```

---

## 9. Tracing Additions

The trace system currently logs `steerTo`, `discipline`, and `mask`.
The new system adds optional diagnostic fields to `decisions.jsonl`
(only when present, to avoid bloating normal traces):

```json
{
  "t": 500,
  "mode": "task_completing",
  "directive_source": "default",
  "intent": { "steer_to": [678, 314], "discipline": "DisciplineNormal" },
  "discipline": "normal",
  "mask": 10,
  "self_x": 660, "self_y": 230,
  "localized": true,
  "nav": {
    "strategic_path": [12, 8, 5, 3],
    "goal_x": 678,
    "goal_y": 314,
    "current_wp_from": 14,
    "current_wp": 12,
    "edge_progress": 45,
    "edge_length": 112,
    "lookahead_x": 662,
    "lookahead_y": 238,
    "arrived": false
  }
}
```

The `"nav"` sub-object is emitted only at `TraceDecisions` level and
only when DisciplineNormal is active. The top-level `"discipline"`
field is always emitted, including non-navigation disciplines, so
trace viewers can explain missing nav records. It adds ~100 bytes per
line and provides full replay visibility into pathfinding decisions.

---

## 10. What Changed vs What Stayed

### Replaced entirely

| File/Entity | Notes |
|-------------|-------|
| `action.nim` internals | The per-pixel runtime planner, local collision recovery, and path-stuck logic were replaced by hierarchical routing. |
| `ActionState` fields in `types.nim` | The type name stayed `ActionState`, but its fields now hold waypoint-route and edge-progress state. |

### Added files/data

| File | Contents |
|------|----------|
| `navigation.nim` | NavGraph loading, strategic planner, tactical follower |
| `perception/baked/nav_graph.json` | Waypoint graph definition |
| `perception/baked/nav_paths.bin` | Precomputed pixel-paths |
| `tools/waypoint_editor.py` | GUI tool for graph editing |
| `tools/bake_nav.py` | Computes nav_paths.bin from nav_graph.json + walk_mask |

### Stayed unchanged

| File | Why |
|------|-----|
| All mode files (`modes/*.nim`) | They produce `ActionIntent` with the same interface |
| `bot.nim` | Still calls `applyIntent(state, belief, intent)` |
| `trace.nim` | Additive nav sub-object; existing schema untouched |
| `types.nim` (mostly) | `ActionIntent`, `ActionDiscipline`, `Point` unchanged |
| All perception code | Still produces position; nav consumes it |
| `tuning.nim` | Cross-mode tuning stayed there; nav-local constants live in `navigation.nim`. |

### Minor touch-ups

| File | Change |
|------|--------|
| `action.nim` | Retained `snapToPassable` as a utility for `fleeing.nim`; `DisciplineNormal` now calls `navigation.nim`. |
| `types.nim` | Added `NavGraph`/`NavEdge`/`NavPath`/`Waypoint` types and repurposed `ActionState`. |
| `bot.nim` | Kept the `applyIntent(state, belief, intent)` call shape. |
| `navigation.nim` | Loads `nav_graph.json` and `nav_paths.bin` via `staticRead`. |

---

## 11. Relationship to Existing Code

### `heuristic()` (geometry.nim)

Retained as a shared utility. Used by:
- Strategic planner (nearest-waypoint lookup)
- Modes (distance checks for kill range, target selection)
- Waypoint arrival test

### `steerButtons()` (currently in action.nim)

Momentum-aware steering controller. Converts (selfX, selfY, targetX,
targetY, velX, velY) into direction button bits using per-axis
coast prediction, active braking, and deadband logic. Supported by
`axisMask`, `preciseAxisMask`, `coastDistance`, and `shouldCoast`
helper procs. See `action.nim` for the full implementation.

### `snapToPassable()` (currently in action.nim)

Retained as a utility but demoted — only used at bake time (waypoint
editor, nav_paths computation) and by `fleeing.nim` for snap targets.
Not part of the runtime hot path.

### Walk mask (`referenceData.map.walkMask`)

Still loaded at runtime (the localizer uses it for patch scoring). The
navigation system no longer runs A* on it at runtime, but it's
available for any defensive checks.

---

## 12. Implementation Status

### Phase 0: Bake Infrastructure (complete)

Created the waypoint graph and precomputed paths. Runtime consumes the
baked files via `staticRead`.

#### 0.1 Waypoint Editor Tool (`tools/waypoint_editor.py`)

- Renders the walk mask as grayscale.
- Supports manual waypoint and edge editing.
- Validates graph connectivity and task reachability.
- Exports `nav_graph.json`.

#### 0.2 Path Baker (`tools/bake_nav.py`)

- Reads `nav_graph.json` + `walk_mask.bin`.
- Runs offline 8-connected A* for each non-vent edge (no node cap,
  corner-cutting prevention, octile heuristic with 10/14 cost scaling).
- Validates that every walking edge has a path.
- Writes `nav_paths.bin` and edge costs.

#### 0.3 Graph Authoring

- Ran waypoint_editor, placed/adjusted waypoints.
- Ran bake_nav and verified all paths compute.
- Committed `nav_graph.json` and `nav_paths.bin` to
  `perception/baked/`

### Phase 1: Runtime Navigation (complete)

The bot uses precomputed paths to navigate. The `ActionIntent` and
`applyIntent` interfaces stayed stable.

#### 1.1 Type Definitions

- Added `Waypoint`, `WaypointKind`, `NavEdge`, `NavPath`, `NavGraph`,
  and `VentPolicy`.
- Kept the public `ActionState` name and changed its fields to hold
  navigation state.

#### 1.2 Data Loading

- `navigation.nim` loads `nav_graph.json` and `nav_paths.bin` via
  `staticRead`.
- Parses waypoints, edges, paths into `NavGraph`.
- Builds adjacency lists, `idToIndex`, and `edgeToPathIndex`.

#### 1.3 Core Navigation (`navigation.nim`)

- `initActionState*(): ActionState`
- `planStrategicPath*(graph, sx, sy, gx, gy, ventPolicy, ventsSafe)`
- `selectLookahead*(path, progress, selfX, selfY, tick, forward)`
- `setCurrentEdge*(state, graph, fromWp, toWp)`
- `findNearestPathPoint*(path, x, y)`
- `nearestWaypoint*(graph, x, y)`

#### 1.4 New `applyIntent`

- Rewrote `action.nim:applyIntent` to use `navigation.nim` for
  `DisciplineNormal`.
- Kept `steerButtons` and discipline dispatch for TaskHold,
  KillStrike, Report, Wander, and NoOp.
- Ghost mode uses direct straight-line steering.

#### 1.5 Bot Integration

- `bot.nim` call shape stayed unchanged:
  `applyIntent(state, belief, intent)`.
- `snapToPassable` stayed exported for `fleeing.nim`.

#### 1.6 Trace Integration

- Added optional `"nav"` sub-object to `logDecision` when
  DisciplineNormal is active
- Fields: strategic_path, current_wp, edge_progress, edge_length,
  arrived

### Phase 2: Vent Support (complete)

Impostors can route through vents when the active vent policy permits
it.

#### 2.1 Vent Edge Filtering

- Strategic planner accepts `VentPolicy`.
- `VentIfSafe` uses the action layer's witness check before including
  vent edges.
- Vent edges are represented as conditional graph edges with low cost.

#### 2.2 Vent Traversal Logic

- Detects when the current edge is a vent edge.
- Walks to the vent entry waypoint before the vent edge.
- Emits ButtonB inside `VentActivationRadius`.
- Detects teleport by position discontinuity / exit proximity.
- Replans without vents if activation times out.

#### 2.3 Vent Policy Integration

- Hunting sets `VentIfSafe`.
- Fleeing sets `VentAlways`.
- Crewmate and other modes use `VentNever`.

### Phase 3: Testing and Validation (complete)

#### 3.1 Unit Tests

- Unit coverage exists in `test/navigation_test.nim` for graph/path
  loading, strategic planning, reverse edge following, and
  `ActionIntent` wiring.
- Ghost and vent behavior are covered structurally by the action-layer
  paths.

#### 3.2 Integration Tests

- Live verification is available through `test/live_test.py` and the
  normal `play_local.py` trace workflow.
- Current live gaps are tracked in `TODO.md` rather than here.

#### 3.3 Regression

- Regression checks use trace output for route progress, action mix,
  and mode distribution.
- Localization, task detection, and meeting behavior remain owned by
  their respective modules and docs.

### Phase 4: Polish (complete)

- Tunables live in `navigation.nim`.
- Current bake has 85 waypoints and 277 edges.
- Old action-layer planner code was removed from runtime.

---

## 13. Open Questions

1. **Nearest-waypoint spatial index:** A flat linear scan over 85
   waypoints is fine. If perf matters, a
   grid-based spatial hash would work, but probably unnecessary.

2. **~~Path perturbation details~~:** Resolved — perturbation disabled
   (`PerturbationChance = 0`). It conflicted with momentum-aware
   steering by introducing spurious direction changes that compounded
   with the game's velocity/friction physics.

3. **Multiple goals in sequence:** Some modes might benefit from
   "visit these N waypoints in order" (patrol loops for impostors).
   The current design handles this by replanning when `steerTo`
   changes. A future enhancement could accept a waypoint sequence
   directly, bypassing nearest-waypoint lookup for intermediate
   targets.

4. **Edge cases at map boundaries:** The walk mask has a 1px margin
   (`passable` checks `x + 1 >= MapWidth`). Waypoints should be
   placed at least 2px from map edges.
