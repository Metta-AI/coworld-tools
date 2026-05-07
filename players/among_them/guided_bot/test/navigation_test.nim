## Focused tests for guided_bot hierarchical navigation.
##
## Run:
##   nim c -r --nimcache:among_them/guided_bot/.nimcache \
##       -d:release --threads:on --mm:orc \
##       among_them/guided_bot/test/navigation_test.nim

import std/strformat
import ../types
import ../belief
import ../navigation
import ../action
import ../perception/geometry

var failures = 0

proc expect(cond: bool, label: string) =
  if not cond:
    stderr.writeLine "FAIL: ", label
    inc failures

proc expectEq[T](got, want: T, label: string) =
  if got != want:
    stderr.writeLine &"FAIL: {label}: got {got}, want {want}"
    inc failures

proc testGraphLoadsPaths() =
  let graph = navGraph()[]
  var walking = 0
  var vents = 0
  for edge in graph.edges:
    if edge.isVent: inc vents else: inc walking

  expect(graph.waypoints.len > 0, "graph: waypoints loaded")
  expect(graph.edges.len > 0, "graph: edges loaded")
  expect(walking > 0, "graph: has walking edges")
  expect(vents > 0, "graph: has vent edges")
  expectEq(graph.paths.len, walking, "graph: one baked path per walking edge")
  expectEq(graph.edgeToPathIndex.len, graph.edges.len,
           "graph: edgeToPathIndex size")

  for edgeIdx, edge in graph.edges:
    let pathIdx = walkingEdgeIndex(graph, edgeIdx)
    if edge.isVent:
      expectEq(pathIdx, -1, &"edge {edgeIdx}: vent has no walking path")
    else:
      expect(pathIdx >= 0 and pathIdx < graph.paths.len,
             &"edge {edgeIdx}: walking path index in range")
      if pathIdx >= 0 and pathIdx < graph.paths.len:
        let path = graph.paths[pathIdx]
        expectEq(path.src, edge.src, &"edge {edgeIdx}: path src matches")
        expectEq(path.dst, edge.dst, &"edge {edgeIdx}: path dst matches")
        expect(path.points.len > 0, &"edge {edgeIdx}: path has points")

proc testVentAdjacencyIsDirectional() =
  let graph = navGraph()[]
  for edgeIdx, edge in graph.edges:
    if edge.isVent:
      let srcIdx = if edge.src >= 0 and edge.src < graph.idToIndex.len:
        graph.idToIndex[edge.src]
      else:
        -1
      let dstIdx = if edge.dst >= 0 and edge.dst < graph.idToIndex.len:
        graph.idToIndex[edge.dst]
      else:
        -1
      expect(srcIdx >= 0 and dstIdx >= 0,
             &"vent edge {edgeIdx}: endpoint IDs resolve")
      if srcIdx >= 0 and dstIdx >= 0:
        expect(edgeIdx in graph.adjacency[srcIdx],
               &"vent edge {edgeIdx}: present from source")
        expect(edgeIdx notin graph.adjacency[dstIdx],
               &"vent edge {edgeIdx}: absent from destination")

proc testStrategicPlanning() =
  let graph = navGraph()[]

  let same = planStrategicPath(graph, 638, 68, 638, 68, VentNever)
  expectEq(same.len, 0, "plan: same nearest waypoint returns empty path")

  let path = planStrategicPath(graph, 564, 120, 638, 68, VentNever)
  expect(path.len > 0, "plan: cafeteria fixture point reaches target task")
  if path.len > 0:
    let lastWp = graph.waypoints[path[^1]]
    expectEq(lastWp.id, 40, "plan: final waypoint is Empty Garbage id 40")

proc testVentPolicyFiltering() =
  let graph = navGraph()[]
  var ventEdgeIdx = -1
  for i, edge in graph.edges:
    if edge.isVent:
      ventEdgeIdx = i
      break
  expect(ventEdgeIdx >= 0, "vent policy: graph has a vent edge")
  if ventEdgeIdx < 0:
    return

  let edge = graph.edges[ventEdgeIdx]
  let srcIdx = graph.idToIndex[edge.src]
  let dstIdx = graph.idToIndex[edge.dst]
  let src = graph.waypoints[srcIdx]
  let dst = graph.waypoints[dstIdx]

  let unsafe = planStrategicPath(graph, src.x, src.y, dst.x, dst.y,
                                 VentIfSafe, ventsSafe = false)
  let safe = planStrategicPath(graph, src.x, src.y, dst.x, dst.y,
                               VentIfSafe, ventsSafe = true)
  let always = planStrategicPath(graph, src.x, src.y, dst.x, dst.y,
                                 VentAlways)

  expect(not (unsafe.len == 1 and unsafe[0] == dstIdx),
         "vent policy: VentIfSafe excludes vent edge when unsafe")
  expect(safe.len == 1 and safe[0] == dstIdx,
         "vent policy: VentIfSafe includes direct vent edge when safe")
  expect(always.len == 1 and always[0] == dstIdx,
         "vent policy: VentAlways includes direct vent edge")

proc testReverseLookahead() =
  let graph = navGraph()[]
  var path: NavPath
  var found = false
  for edgeIdx, edge in graph.edges:
    if not edge.isVent:
      let pathIdx = walkingEdgeIndex(graph, edgeIdx)
      if pathIdx >= 0 and graph.paths[pathIdx].points.len > PathLookahead + 2:
        path = graph.paths[pathIdx]
        found = true
        break
  expect(found, "lookahead: found a long walking path")
  if not found:
    return

  let first = path.points[0]
  let last = path.points[^1]
  let fwd = selectLookahead(path, 0, first.x, first.y, 1, true)
  let rev = selectLookahead(path, 0, last.x, last.y, 1, false)

  expect(heuristic(fwd.target.x, fwd.target.y, first.x, first.y) > 0,
         "lookahead: forward target advances from first point")
  expect(heuristic(rev.target.x, rev.target.y, last.x, last.y) > 0,
         "lookahead: reverse target advances from last point")

proc testApplyIntentUsesNavPath() =
  var state = initActionState()
  var belief = initBelief()
  belief.tick = 1
  belief.self.role = RoleCrewmate
  belief.self.phase = PhaseGameplay
  belief.percep.localized = true
  belief.percep.selfX = 564
  belief.percep.selfY = 120
  belief.directive.mode = ModeTaskCompleting

  var intent = initActionIntent()
  intent.steerValid = true
  intent.steerTo = Point(x: 638, y: 68)
  intent.discipline = DisciplineNormal

  let mask = applyIntent(state, belief, intent)
  expect(mask != 0'u8, "applyIntent: emits movement for fixture route")
  expect(state.currentEdgeIdx >= 0, "applyIntent: current edge set")
  expect(state.strategicPath.len > 0, "applyIntent: strategic path set")
  expect(state.lastSelfX == belief.percep.selfX and
         state.lastSelfY == belief.percep.selfY,
         "applyIntent: last self position updated")

proc main() =
  echo "=== navigation_test ==="
  echo "1. Graph and baked path loading:"
  testGraphLoadsPaths()
  echo "2. Vent adjacency direction:"
  testVentAdjacencyIsDirectional()
  echo "3. Strategic planning:"
  testStrategicPlanning()
  echo "4. Vent policy filtering:"
  testVentPolicyFiltering()
  echo "5. Tactical lookahead direction:"
  testReverseLookahead()
  echo "6. applyIntent navigation wiring:"
  testApplyIntentUsesNavPath()

  if failures > 0:
    stderr.writeLine &"\n{failures} FAILURE(S)"
    quit(1)
  else:
    echo &"\nOK - all navigation tests passed"

when isMainModule:
  main()
