## Navigation module — hierarchical waypoint-based pathfinding.
##
## Provides the strategic planner (Dijkstra on waypoint graph) and
## tactical follower (precomputed path lookup + lookahead steering).
## See NAVIGATION_DESIGN.md for full design.
##
## Also owns the NavGraph singleton: loaded lazily on first access
## via navGraph(). The graph data comes from the baked nav_graph.json
## blob embedded in perception/data.nim.

import std/[json, math, strformat]
import types
import perception/geometry

# ---------------------------------------------------------------------------
# NavGraph singleton (lazy-loaded)
# ---------------------------------------------------------------------------

# Nav blobs live here (not in perception/data.nim) to avoid a Nim
# compiler/linker issue where large staticRead consts in the same
# module as the perception blobs corrupt those blobs at runtime.
const
  NavGraphJsonBlob = staticRead("perception/baked/nav_graph.json")
  NavPathsBlob = staticRead("perception/baked/nav_paths.bin")

static:
  doAssert NavGraphJsonBlob.len > 0, "nav_graph.json baked blob is empty"
  doAssert NavPathsBlob.len > 0, "nav_paths.bin baked blob is empty"

var navGraphData: ref NavGraph = nil

proc blobByte(blob: string, pos: int): int {.inline.} =
  if pos < 0 or pos >= blob.len:
    raise newException(ValueError, &"nav_paths.bin truncated at byte {pos}")
  ord(blob[pos])

proc readU16(blob: string, pos: int): int {.inline.} =
  blobByte(blob, pos) or (blobByte(blob, pos + 1) shl 8)

proc readI16(blob: string, pos: int): int {.inline.} =
  let u = readU16(blob, pos)
  if u >= 0x8000: u - 0x10000 else: u

proc readU32(blob: string, pos: int): int {.inline.} =
  blobByte(blob, pos) or
    (blobByte(blob, pos + 1) shl 8) or
    (blobByte(blob, pos + 2) shl 16) or
    (blobByte(blob, pos + 3) shl 24)

proc buildIdToIndex(waypoints: seq[Waypoint]): seq[int] =
  ## Build a compact waypoint ID -> index lookup. Missing IDs map to -1.
  var maxId = -1
  for wp in waypoints:
    if wp.id > maxId:
      maxId = wp.id
  if maxId < 0:
    return @[]
  result = newSeq[int](maxId + 1)
  for i in 0 ..< result.len:
    result[i] = -1
  for i, wp in waypoints:
    if wp.id >= 0:
      result[wp.id] = i

proc waypointIndex(idToIndex: seq[int], id: int): int {.inline.} =
  if id >= 0 and id < idToIndex.len: idToIndex[id] else: -1

proc parseNavPathsBlob(blob: string, edges: seq[NavEdge]):
    tuple[paths: seq[NavPath], edgeToPathIndex: seq[int]] =
  ## Parse perception/baked/nav_paths.bin.
  ##
  ## The authoritative format is the one written by tools/bake_nav.py:
  ##   u32 num_walking_edges
  ##   u32 total_points
  ##   repeated num_walking_edges:
  ##     u32 point_offset, u16 point_count, u16 src_id, u16 dst_id
  ##   repeated total_points:
  ##     i16 x, i16 y
  const
    HeaderSize = 8
    RecordSize = 10
    PointSize = 4

  if blob.len < HeaderSize:
    raise newException(ValueError, "nav_paths.bin missing header")

  let numPaths = readU32(blob, 0)
  let totalPoints = readU32(blob, 4)
  let pointBase = HeaderSize + numPaths * RecordSize
  let expectedLen = pointBase + totalPoints * PointSize
  if blob.len != expectedLen:
    raise newException(ValueError,
      &"nav_paths.bin size mismatch: got {blob.len}, expected {expectedLen}")

  var walkingEdges: seq[int] = @[]
  result.edgeToPathIndex = newSeq[int](edges.len)
  for i in 0 ..< result.edgeToPathIndex.len:
    result.edgeToPathIndex[i] = -1
  for i, edge in edges:
    if not edge.isVent:
      walkingEdges.add(i)

  if numPaths != walkingEdges.len:
    raise newException(ValueError,
      &"nav_paths.bin path count mismatch: got {numPaths}, expected {walkingEdges.len}")

  result.paths = newSeq[NavPath](numPaths)
  for pathIdx in 0 ..< numPaths:
    let recPos = HeaderSize + pathIdx * RecordSize
    let offset = readU32(blob, recPos)
    let pointCount = readU16(blob, recPos + 4)
    let srcId = readU16(blob, recPos + 6)
    let dstId = readU16(blob, recPos + 8)
    if offset + pointCount > totalPoints:
      raise newException(ValueError,
        &"nav_paths.bin record {pathIdx} points out of range")

    let edgeIdx = walkingEdges[pathIdx]
    let edge = edges[edgeIdx]
    if edge.src != srcId or edge.dst != dstId:
      raise newException(ValueError,
        &"nav_paths.bin record {pathIdx} edge mismatch: " &
        &"blob {srcId}->{dstId}, graph {edge.src}->{edge.dst}")

    var points = newSeq[Point](pointCount)
    for j in 0 ..< pointCount:
      let p = pointBase + (offset + j) * PointSize
      points[j] = Point(x: readI16(blob, p), y: readI16(blob, p + 2))

    result.paths[pathIdx] = NavPath(src: srcId, dst: dstId, points: points)
    result.edgeToPathIndex[edgeIdx] = pathIdx

proc loadNavGraphFromBlob(): NavGraph =
  ## Parse NavGraphJsonBlob into a NavGraph.
  let root = parseJson(NavGraphJsonBlob)

  var waypoints: seq[Waypoint] = @[]
  for wj in root["waypoints"]:
    let kindStr = wj["kind"].getStr("poi")
    let kind = case kindStr
      of "doorway":      WpDoorway
      of "intersection": WpIntersection
      of "task":         WpTask
      of "vent":         WpVent
      of "button":       WpButton
      of "home":         WpHome
      else:              WpPoi
    let ventGroup = if wj.hasKey("vent_group"):
      let s = wj["vent_group"].getStr("")
      if s.len > 0: s[0] else: '\0'
    else: '\0'
    waypoints.add(Waypoint(
      id: wj["id"].getInt,
      x: wj["x"].getInt,
      y: wj["y"].getInt,
      kind: kind,
      room: wj.getOrDefault("room").getStr(""),
      label: wj.getOrDefault("label").getStr(""),
      ventGroup: ventGroup,
      ventIndex: wj.getOrDefault("vent_index").getInt(0),
    ))

  var edges: seq[NavEdge] = @[]
  for ej in root["edges"]:
    let isVent = ej.getOrDefault("is_vent").getBool(false)
    let ventGroupStr = ej.getOrDefault("vent_group").getStr("")
    let ventGroup = if ventGroupStr.len > 0: ventGroupStr[0] else: '\0'
    edges.add(NavEdge(
      src: ej["src"].getInt,
      dst: ej["dst"].getInt,
      cost: ej.getOrDefault("cost").getInt(0),
      isVent: isVent,
      ventGroup: ventGroup,
    ))

  let wpCount = waypoints.len
  var adjacency = newSeq[seq[int]](wpCount)
  for i in 0 ..< wpCount:
    adjacency[i] = @[]

  # ID -> index map (IDs may be non-contiguous)
  let idToIndex = buildIdToIndex(waypoints)

  for i, edge in edges:
    let srcIdx = waypointIndex(idToIndex, edge.src)
    let dstIdx = waypointIndex(idToIndex, edge.dst)
    if srcIdx >= 0 and srcIdx < wpCount:
      adjacency[srcIdx].add(i)
    if not edge.isVent and dstIdx >= 0 and dstIdx < wpCount:
      adjacency[dstIdx].add(i)

  let parsedPaths = parseNavPathsBlob(NavPathsBlob, edges)

  NavGraph(
    waypoints: waypoints,
    edges: edges,
    paths: parsedPaths.paths,
    adjacency: adjacency,
    idToIndex: idToIndex,
    edgeToPathIndex: parsedPaths.edgeToPathIndex,
    waypointCount: wpCount
  )

proc navGraph*(): ptr NavGraph =
  ## Access the shared NavGraph singleton. Loaded on first call.
  ## Returns a ptr (not copied) for zero-cost access.
  if navGraphData == nil:
    navGraphData = new(NavGraph)
    navGraphData[] = loadNavGraphFromBlob()
  addr(navGraphData[])

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

const
  WaypointArrivalRadius* = 12   ## px; bot considers itself "at" a waypoint.
  PathLookahead* = 18           ## Points ahead on path to aim at.
  PathSnapRadius* = 30          ## Max distance to snap to path (drift tolerance).
  PerturbationChance* = 0       ## 1-in-N pseudo-random perturbation chance.
  FinalApproachRadius* = 12     ## Within this of steerTo, steer directly to it.
  ReplanIntervalTicks* = 72      ## Periodic drift recovery cadence.
  StallProgressTicks* = 48       ## Replan if waypoint distance does not improve.
  NavErrorNoopTicks* = 12        ## Brief pause after defensive nav errors.
  VentActivationRadius* = 16     ## Server-side vent activation range.
  VentActivationTimeout* = 24    ## Ticks to retry ButtonB before replanning.
  VentTeleportDistance* = 50     ## Position jump that indicates vent travel.

# ---------------------------------------------------------------------------
# Nearest waypoint lookup
# ---------------------------------------------------------------------------

proc nearestWaypoint*(graph: NavGraph, x, y: int): int =
  ## Find the waypoint closest (Manhattan) to world point (x, y).
  ## Returns waypoint index (not ID).
  var bestDist = high(int)
  var bestIdx = 0
  for i, wp in graph.waypoints:
    let d = heuristic(x, y, wp.x, wp.y)
    if d < bestDist:
      bestDist = d
      bestIdx = i
  bestIdx

proc nearestWaypointDistance*(graph: NavGraph, x, y: int): int =
  ## Distance to the closest waypoint. Used by defensive checks.
  if graph.waypoints.len == 0:
    return high(int)
  let idx = nearestWaypoint(graph, x, y)
  let wp = graph.waypoints[idx]
  heuristic(x, y, wp.x, wp.y)

# ---------------------------------------------------------------------------
# Strategic planner (Dijkstra on waypoint graph)
# ---------------------------------------------------------------------------

proc planStrategicPath*(graph: NavGraph, selfX, selfY: int,
                        goalX, goalY: int,
                        ventPolicy: VentPolicy,
                        ventsSafe: bool = false): seq[int] =
  ## Compute shortest waypoint path from current position to goal.
  ## Returns sequence of waypoint IDs to visit (not including start).
  ## Empty if already at goal waypoint or no path exists.
  let startWp = nearestWaypoint(graph, selfX, selfY)
  let goalWp = nearestWaypoint(graph, goalX, goalY)

  if startWp == goalWp:
    return @[]

  let n = graph.waypointCount
  var dist = newSeq[int](n)
  var prev = newSeq[int](n)
  var visited = newSeq[bool](n)

  for i in 0 ..< n:
    dist[i] = high(int) div 2
    prev[i] = -1
  dist[startWp] = 0

  # Simple Dijkstra (N is small, ~50-85 nodes — O(N^2) is fine)
  for _ in 0 ..< n:
    # Find unvisited node with minimum distance
    var u = -1
    var uDist = high(int)
    for i in 0 ..< n:
      if not visited[i] and dist[i] < uDist:
        u = i
        uDist = dist[i]
    if u < 0 or u == goalWp:
      break
    visited[u] = true

    # Relax edges from u
    for edgeIdx in graph.adjacency[u]:
      let edge = graph.edges[edgeIdx]
      # Determine neighbor index. Edge stores waypoint IDs.
      let neighborId = if edge.src == graph.waypoints[u].id: edge.dst
                       else: edge.src
      let neighbor = waypointIndex(graph.idToIndex, neighborId)
      if neighbor < 0: continue

      # Skip vent edges based on policy
      if edge.isVent:
        case ventPolicy
        of VentNever: continue
        of VentIfSafe:
          if not ventsSafe:
            continue
        of VentAlways: discard

      let newDist = dist[u] + max(edge.cost, 1)
      if newDist < dist[neighbor]:
        dist[neighbor] = newDist
        prev[neighbor] = u

  # Reconstruct path from goalWp back to startWp
  if prev[goalWp] < 0 and goalWp != startWp:
    return @[]  # unreachable

  var path: seq[int] = @[]
  var cur = goalWp
  while cur != startWp and cur >= 0:
    path.add(cur)
    cur = prev[cur]
  # Reverse to get start->goal order
  var lo = 0
  var hi = path.len - 1
  while lo < hi:
    swap(path[lo], path[hi])
    inc lo
    dec hi
  path

# ---------------------------------------------------------------------------
# Edge lookup
# ---------------------------------------------------------------------------

proc findEdge*(graph: NavGraph, srcWp, dstWp: int): int =
  ## Find the edge index connecting two waypoints (by INDEX, not ID).
  ## Returns -1 if none. Checks adjacency list of srcWp.
  if srcWp < 0 or srcWp >= graph.waypointCount:
    return -1
  let srcId = graph.waypoints[srcWp].id
  let dstId = graph.waypoints[dstWp].id
  for i in graph.adjacency[srcWp]:
    let e = graph.edges[i]
    if e.isVent:
      if e.src == srcId and e.dst == dstId:
        return i
    else:
      if (e.src == srcId and e.dst == dstId) or
         (e.src == dstId and e.dst == srcId):
        return i
  -1

proc walkingEdgeIndex*(graph: NavGraph, edgeIdx: int): int =
  ## Map a global edge index to the walking-edge index (for path lookup).
  if edgeIdx < 0 or edgeIdx >= graph.edgeToPathIndex.len:
    return -1
  graph.edgeToPathIndex[edgeIdx]

# ---------------------------------------------------------------------------
# Tactical path following
# ---------------------------------------------------------------------------

proc findNearestPathPoint*(path: NavPath, selfX, selfY: int): int =
  ## Find the index of the nearest point on the path to (selfX, selfY).
  ## Linear scan — paths are short (typically <50 simplified points).
  if path.points.len == 0:
    return 0
  var bestDist = high(int)
  var bestIdx = 0
  for i, p in path.points:
    let d = heuristic(selfX, selfY, p.x, p.y)
    if d < bestDist:
      bestDist = d
      bestIdx = i
  bestIdx

proc clampUnit(v: float): float {.inline.} =
  if v < 0.0: 0.0 elif v > 1.0: 1.0 else: v

proc rounded(v: float): int {.inline.} =
  int(round(v))

proc segmentProjectionT(px, py, ax, ay, bx, by: int): float {.inline.} =
  ## Euclidean projection parameter on A->B, clamped to the segment.
  let dx = bx - ax
  let dy = by - ay
  let lenSq = dx * dx + dy * dy
  if lenSq <= 0:
    return 0.0
  clampUnit(((px - ax) * dx + (py - ay) * dy).float / lenSq.float)

proc distToSegment*(px, py, ax, ay, bx, by: int): int =
  ## Manhattan distance from P to the closest point on segment A->B.
  ## Projection uses Euclidean geometry; thresholding stays Manhattan to match
  ## `heuristic` and the rest of the navigation code.
  if ax == bx and ay == by:
    return heuristic(px, py, ax, ay)
  let t = segmentProjectionT(px, py, ax, ay, bx, by)
  let cx = ax.float + t * (bx - ax).float
  let cy = ay.float + t * (by - ay).float
  rounded(abs(px.float - cx) + abs(py.float - cy))

proc segmentLength(a, b: Point): int {.inline.} =
  heuristic(a.x, a.y, b.x, b.y)

proc pathLength(path: NavPath): int =
  if path.points.len <= 1:
    return 0
  for i in 0 ..< path.points.len - 1:
    result += segmentLength(path.points[i], path.points[i + 1])

proc pointAtPathProgress(path: NavPath, progress: int): Point =
  ## Interpolate a world point at `progress` Manhattan pixels from path start.
  if path.points.len == 0:
    return Point(x: 0, y: 0)
  if progress <= 0 or path.points.len == 1:
    return path.points[0]

  var remaining = progress
  for i in 0 ..< path.points.len - 1:
    let a = path.points[i]
    let b = path.points[i + 1]
    let segLen = segmentLength(a, b)
    if segLen <= 0:
      continue
    if remaining <= segLen:
      let t = remaining.float / segLen.float
      return Point(
        x: rounded(a.x.float + t * (b.x - a.x).float),
        y: rounded(a.y.float + t * (b.y - a.y).float),
      )
    remaining -= segLen

  path.points[^1]

proc findNearestSegmentSnap*(path: NavPath, selfX, selfY: int):
    tuple[idx: int, progress: int, dist: int] =
  ## Snap to the nearest path segment and return path-start progress in pixels.
  if path.points.len == 0:
    return (0, 0, high(int))
  if path.points.len == 1:
    return (0, 0, heuristic(selfX, selfY, path.points[0].x, path.points[0].y))

  var bestDist = high(int)
  var bestIdx = 0
  var bestProgress = 0
  var cumulative = 0
  for i in 0 ..< path.points.len - 1:
    let a = path.points[i]
    let b = path.points[i + 1]
    let segLen = segmentLength(a, b)
    let t = segmentProjectionT(selfX, selfY, a.x, a.y, b.x, b.y)
    let d = distToSegment(selfX, selfY, a.x, a.y, b.x, b.y)
    let along = if segLen <= 0: 0 else: min(rounded(t * segLen.float), segLen)
    let segProgress = cumulative + along
    if d < bestDist:
      bestDist = d
      bestIdx = i
      bestProgress = segProgress
    cumulative += segLen

  (bestIdx, bestProgress, bestDist)

proc findNearestPathPointWithDistance*(path: NavPath, selfX, selfY: int):
    tuple[idx: int, dist: int] =
  ## Find the nearest path vertex/segment and its Manhattan snap distance.
  ## For simplified paths, long straight segments may have sparse vertices;
  ## segment-aware distance keeps on-course bots snapped to the path corridor.
  let snap = findNearestSegmentSnap(path, selfX, selfY)
  (snap.idx, snap.dist)

proc selectLookahead*(path: NavPath, progress: int,
                      selfX, selfY: int, tick: int,
                      forward: bool): tuple[target: Point,
                                            newProgress: int,
                                            snapIdx: int,
                                            snapDist: int] =
  ## Select the lookahead target point on the current path segment.
  ## Snaps to nearest path segment, advances progress, picks lookahead
  ## ahead, and applies small perturbation for localization.
  if path.points.len == 0:
    return (Point(x: selfX, y: selfY), 0, 0, high(int))

  # Snap to nearest point on the path polyline (handles drift without
  # requiring every intermediate pixel to survive path simplification).
  let snap = findNearestSegmentSnap(path, selfX, selfY)
  let totalProgress = pathLength(path)
  let traversalSnap = if forward: snap.progress else: totalProgress - snap.progress
  # Never go backward: use max of progress and snap.
  let effectiveProgress = max(progress, traversalSnap)

  # Lookahead
  let traversalLookahead = min(effectiveProgress + PathLookahead, totalProgress)
  let pathLookahead = if forward:
    traversalLookahead
  else:
    max(totalProgress - traversalLookahead, 0)
  var target = pointAtPathProgress(path, pathLookahead)

  # Small deterministic pseudo-random perturbation to aid localization.
  # Uses tick hashing instead of a fixed cadence so it behaves like a
  # reproducible 1-in-N chance per tick.
  let h = (tick * 1103515245 + 12345) and 0x7fffffff
  if PerturbationChance > 0 and (h mod PerturbationChance) == 0:
    let sign = if ((h shr 8) and 1) == 0: 1 else: -1
    target.x += sign
    if ((h shr 9) and 1) == 0:
      target.y += sign

  (target, effectiveProgress, snap.idx, snap.dist)

proc setNavError*(state: var ActionState, tick: int, reason: string) =
  ## Defensive pause used when baked nav data and runtime position disagree.
  state.navNoopUntilTick = tick + NavErrorNoopTicks
  state.navErrorReason = reason
  state.currentGoalValid = false
  state.currentEdgeIdx = -1
  state.currentEdgeFrom = -1
  state.currentEdgeTo = -1
  state.pathProgress = 0

proc setCurrentEdge*(state: var ActionState, graph: NavGraph,
                     fromWp, toWp: int) =
  ## Update current-edge state for a waypoint-index transition.
  state.currentEdgeFrom = fromWp
  state.currentEdgeTo = toWp
  state.currentEdgeIdx = findEdge(graph, fromWp, toWp)
  state.pathProgress = 0

# ---------------------------------------------------------------------------
# State management helpers
# ---------------------------------------------------------------------------

proc initActionState*(): ActionState =
  ActionState(
    currentGoalValid: false,
    strategicPath: @[],
    currentEdgeIdx: -1,
    currentEdgeFrom: -1,
    currentEdgeTo: -1,
    ventPolicy: VentNever,
    pathProgress: 0,
    lastSelfX: 0,
    lastSelfY: 0,
    lastPlanTick: -1000000,
    lastProgressTick: 0,
    lastWaypointDistance: high(int),
    arrivedAtWaypoint: false,
    navNoopUntilTick: 0,
    navErrorReason: "",
    ventAttemptTicks: 0,
    lastEmittedMask: 0,
    haveMotionSample: false,
    previousSelfX: 0,
    previousSelfY: 0,
    velocityX: 0,
    velocityY: 0,
    stuckFrames: 0,
    jiggleTicks: 0,
    jiggleSide: 0,
    taskHoldTicks: 0,
    lastLookahead: Point(x: 0, y: 0),
    lastLookaheadValid: false,
  )

proc goalChanged*(state: ActionState, goalX, goalY: int): bool =
  ## True if the goal has changed since last plan.
  not state.currentGoalValid or
    state.currentGoal.x != goalX or
    state.currentGoal.y != goalY
