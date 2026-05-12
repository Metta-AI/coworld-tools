## Mode: `alibi_building`. Imposter follows a specific non-imposter
## crewmate and fakes tasks near them without losing sight of the
## companion.

import std/json
import ../types
import ../action
import ../tuning
import ../perception/data
import ../perception/geometry

const Name* = ModeAlibiBuilding

const
  AlibiFollowMaxDistance = 72
  AlibiTaskNearTargetRadius = 72
  AlibiTaskInterruptDistance = 80
  AlibiLostSightGraceTicks = 72
  AlibiMemoryChaseTicks = 480
  AlibiStationArriveDistance = 10

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleImposter and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeAlibiBuilding,
             aliCompanionColor: -1,
             aliRoomId: -1,
             aliMinDurationTicks: 240)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeAlibiBuilding,
                        aliEnterTick: belief.tick,
                        aliTargetColor: params.aliCompanionColor,
                        aliLastSeenTick: -1,
                        aliLastSeenX: 0,
                        aliLastSeenY: 0,
                        aliFakeTargetIndex: -1,
                        aliFakeHoldUntilTick: 0,
                        aliLoiterUntilTick: 0)

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc moveIntent(x, y: int, discipline: ActionDiscipline = DisciplineNormal):
    ActionIntent =
  ActionIntent(
    steerTo: Point(x: x, y: y),
    steerValid: true,
    pressA: false, pressB: false,
    cursor: CursorNone, chat: "",
    discipline: discipline)

proc holdIntent(): ActionIntent =
  ActionIntent(
    steerTo: Point(x: 0, y: 0),
    steerValid: false,
    pressA: true, pressB: false,
    cursor: CursorNone, chat: "",
    discipline: DisciplineTaskHold)

proc resetFakeTask(scratch: var ModeScratch) =
  scratch.aliFakeTargetIndex = -1
  scratch.aliFakeHoldUntilTick = 0
  scratch.aliLoiterUntilTick = 0

proc isValidCompanion(belief: Belief, color: int): bool =
  if color < 0 or color >= PlayerColorCount:
    return false
  if color == belief.self.colorIndex:
    return false
  if color in belief.self.knownImposterColors:
    return false
  let ps = belief.memory.perPlayer[color]
  ps.role != RoleImposter and ps.alive

proc worldPosFor(belief: Belief, cm: CrewmateMatch): Point =
  Point(
    x: visibleCrewmateWorldX(belief.percep.cameraX, cm.x),
    y: visibleCrewmateWorldY(belief.percep.cameraY, cm.y))

proc visibleCompanion(belief: Belief, color: int):
    tuple[found: bool, pos: Point] =
  if not belief.isValidCompanion(color):
    return (false, Point(x: 0, y: 0))
  for cm in belief.percep.visibleCrewmates:
    if cm.colorIndex == color:
      return (true, belief.worldPosFor(cm))
  (false, Point(x: 0, y: 0))

proc nearestVisibleCompanion(belief: Belief, selfX, selfY: int):
    tuple[found: bool, color: int, pos: Point] =
  var bestDist = high(int)
  for cm in belief.percep.visibleCrewmates:
    let ci = cm.colorIndex
    if not belief.isValidCompanion(ci):
      continue
    let pos = belief.worldPosFor(cm)
    let d = heuristic(selfX, selfY, pos.x, pos.y)
    if d < bestDist:
      bestDist = d
      result = (true, ci, pos)

proc rememberCompanion(scratch: var ModeScratch, tick: int, pos: Point) =
  scratch.aliLastSeenTick = tick
  scratch.aliLastSeenX = pos.x
  scratch.aliLastSeenY = pos.y

proc stationNearTarget(stationIdx: int, target: Point): bool =
  let tasks = referenceData.map.tasks
  if stationIdx < 0 or stationIdx >= tasks.len:
    return false
  let ts = tasks[stationIdx]
  heuristic(ts.passableCX, ts.passableCY, target.x, target.y) <=
    AlibiTaskNearTargetRadius

proc stationInRoom(stationIdx, roomId: int): bool =
  let map = referenceData.map
  if stationIdx < 0 or stationIdx >= map.tasks.len or
     roomId < 0 or roomId >= map.rooms.len:
    return false
  let ts = map.tasks[stationIdx]
  roomNameAt(map, ts.passableCX, ts.passableCY) == map.rooms[roomId].name

proc pickTaskNearCompanion(belief: Belief, selfX, selfY: int,
                           target: Point, roomId: int): int =
  let tasks = referenceData.map.tasks
  var bestScore = high(int)
  result = -1
  for i, ts in tasks:
    if roomId >= 0 and not stationInRoom(i, roomId):
      continue
    let targetDist = heuristic(ts.passableCX, ts.passableCY,
                               target.x, target.y)
    if targetDist > AlibiTaskNearTargetRadius:
      continue
    let selfDist = heuristic(selfX, selfY, ts.passableCX, ts.passableCY)
    let score = targetDist * 3 + selfDist
    if score < bestScore:
      bestScore = score
      result = i

proc atStation(selfX, selfY: int, stationIdx: int): bool =
  let tasks = referenceData.map.tasks
  if stationIdx < 0 or stationIdx >= tasks.len:
    return false
  let ts = tasks[stationIdx]
  (selfX >= ts.x and selfX < ts.x + ts.w and
   selfY >= ts.y and selfY < ts.y + ts.h) or
    heuristic(selfX, selfY, ts.passableCX, ts.passableCY) <=
      AlibiStationArriveDistance

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let localized = belief.percep.localized
  let tasks = referenceData.map.tasks
  if not localized or tasks.len == 0:
    return noOpIntent()

  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY

  var targetColor = params.aliCompanionColor
  if not belief.isValidCompanion(targetColor):
    targetColor = scratch.aliTargetColor
  if not belief.isValidCompanion(targetColor):
    let fallback = belief.nearestVisibleCompanion(selfX, selfY)
    if fallback.found:
      targetColor = fallback.color
      scratch.aliTargetColor = targetColor
      scratch.rememberCompanion(belief.tick, fallback.pos)
    else:
      scratch.resetFakeTask()
      return noOpIntent()
  else:
    scratch.aliTargetColor = targetColor

  let visible = belief.visibleCompanion(targetColor)
  if visible.found:
    scratch.rememberCompanion(belief.tick, visible.pos)
  else:
    scratch.resetFakeTask()
    let ps = belief.memory.perPlayer[targetColor]
    if ps.lastSeenTick > 0 and belief.tick - ps.lastSeenTick <= AlibiMemoryChaseTicks:
      scratch.aliLastSeenTick = ps.lastSeenTick
      scratch.aliLastSeenX = ps.lastSeenX
      scratch.aliLastSeenY = ps.lastSeenY
    if scratch.aliLastSeenTick > 0 and
       belief.tick - scratch.aliLastSeenTick <= AlibiLostSightGraceTicks:
      return moveIntent(scratch.aliLastSeenX, scratch.aliLastSeenY)
    return noOpIntent()

  let target = visible.pos
  let distToTarget = heuristic(selfX, selfY, target.x, target.y)

  # Preserve the alibi: reacquire the companion before fake-tasking.
  if distToTarget > AlibiTaskInterruptDistance:
    scratch.resetFakeTask()
    return moveIntent(target.x, target.y)

  if scratch.aliFakeTargetIndex >= 0 and
     (not stationNearTarget(scratch.aliFakeTargetIndex, target) or
      (params.aliRoomId >= 0 and
       not stationInRoom(scratch.aliFakeTargetIndex, params.aliRoomId))):
    scratch.resetFakeTask()

  if scratch.aliFakeHoldUntilTick > 0 and
     belief.tick < scratch.aliFakeHoldUntilTick:
    if distToTarget <= AlibiTaskInterruptDistance:
      return holdIntent()
    scratch.resetFakeTask()
    return moveIntent(target.x, target.y)

  if scratch.aliLoiterUntilTick > 0 and belief.tick < scratch.aliLoiterUntilTick:
    if distToTarget <= AlibiFollowMaxDistance:
      return noOpIntent()
    scratch.resetFakeTask()
    return moveIntent(target.x, target.y)

  if scratch.aliFakeTargetIndex < 0:
    scratch.aliFakeTargetIndex = pickTaskNearCompanion(
      belief, selfX, selfY, target, params.aliRoomId)

  if scratch.aliFakeTargetIndex < 0:
    if distToTarget > AlibiFollowMaxDistance:
      return moveIntent(target.x, target.y)
    return noOpIntent()

  let taskIdx = scratch.aliFakeTargetIndex
  let ts = tasks[taskIdx]
  if atStation(selfX, selfY, taskIdx):
    let fakeTicks = min(PreFakeHoldTicks, max(1, params.aliMinDurationTicks))
    scratch.aliFakeHoldUntilTick = belief.tick + fakeTicks
    scratch.aliLoiterUntilTick =
      belief.tick + max(fakeTicks, params.aliMinDurationTicks)
    return holdIntent()

  if distToTarget > AlibiFollowMaxDistance:
    scratch.resetFakeTask()
    return moveIntent(target.x, target.y)

  moveIntent(ts.passableCX, ts.passableCY)

proc summarizeForLlm*(belief: Belief, params: ModeParams,
                      scratch: ModeScratch): JsonNode =
  result = newJObject()
  result["status"] = newJString("building_alibi_with_companion")
  result["directive_companion_color"] = newJInt(params.aliCompanionColor)
  result["active_companion_color"] = newJInt(scratch.aliTargetColor)
  result["requested_room_id"] = newJInt(params.aliRoomId)
  if params.aliRoomId >= 0 and params.aliRoomId < referenceData.map.rooms.len:
    result["requested_room"] =
      newJString(referenceData.map.rooms[params.aliRoomId].name)
  result["min_duration_ticks"] = newJInt(params.aliMinDurationTicks)
  result["ticks_in_mode"] = newJInt(max(0, belief.tick - scratch.aliEnterTick))
  if scratch.aliLastSeenTick >= 0:
    result["last_seen_age_ticks"] =
      newJInt(max(0, belief.tick - scratch.aliLastSeenTick))
    result["last_seen_position"] = %*[scratch.aliLastSeenX, scratch.aliLastSeenY]
  result["fake_target_index"] = newJInt(scratch.aliFakeTargetIndex)
  if scratch.aliFakeTargetIndex >= 0 and
     scratch.aliFakeTargetIndex < referenceData.map.tasks.len:
    let ts = referenceData.map.tasks[scratch.aliFakeTargetIndex]
    result["fake_target_name"] = newJString(ts.name)
    result["fake_target_room"] =
      newJString(roomNameAt(referenceData.map, ts.passableCX, ts.passableCY))
  result["fake_hold_ticks_remaining"] =
    newJInt(max(0, scratch.aliFakeHoldUntilTick - belief.tick))
  result["loiter_ticks_remaining"] =
    newJInt(max(0, scratch.aliLoiterUntilTick - belief.tick))
