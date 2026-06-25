## Mode: `hunting`. Alive imposter default behavior.
##
## The mode is internally phase-based while preserving the existing
## directive shape:
##   - ALIBI: cooldown active; fake tasks in public / witnessed areas.
##   - SEEKING: kill ready; move toward likely isolated targets or safe rooms.
##   - STALKING: visible target; close while witness risk stays acceptable.
##   - STRIKE: in kill range; let DisciplineKillStrike press A.
##   - POST-KILL: immediately disengage and build an alibi after a strike.
##
## LLM/reflex params still matter: preferred_target biases seeking and
## stalking, max_witnesses gates strikes, and opportunistic controls
## whether non-preferred targets may be taken.

import std/[json, strutils]
import ../types
import ../action
import ../navigation
import ../tuning
import ../perception/data
import ../perception/geometry

const Name* = ModeHunting

type
  HuntCandidate = object
    valid: bool
    color: int
    x, y: int
    dist: int
    witnesses: int
    predictedWitnesses: int
    score: int

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleImposter and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeHunting,
             huntPreferredTarget: -1,
             huntMaxWitnesses: 0,
             huntOpportunistic: true,
             huntCoverMode: ModePretending)

proc initialPhase(belief: Belief): HuntingPhase =
  if belief.percep.killReady: HpSeeking else: HpAlibi

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  let phase = initialPhase(belief)
  scratch = ModeScratch(mode: ModeHunting,
                        huntPhase: phase,
                        huntPrevPhase: phase,
                        huntPhaseStartedTick: belief.tick,
                        huntPhaseChanged: true,
                        huntPhaseReason: "enter_mode",
                        huntTargetColor: params.huntPreferredTarget,
                        huntLastSightingTick: 0,
                        huntEnterTick: belief.tick,
                        huntLastSeenX: 0,
                        huntLastSeenY: 0,
                        huntCoverTargetIndex: -1,
                        huntCoverLoiterUntilTick: 0,
                        huntCoverFakeUntilTick: 0,
                        huntStrikeTick: -1,
                        huntStrikeTargetX: 0,
                        huntStrikeTargetY: 0,
                        huntPreStrikeBodyCount: 0,
                        huntPreStrikeKillReady: false,
                        huntFailedKillColor: -1,
                        huntKillConfirmed: false,
                        huntLastKillTargetColor: params.huntPreferredTarget,
                        huntPostKillUntilTick: 0,
                        huntPostKillTargetX: 0,
                        huntPostKillTargetY: 0,
                        huntPostKillTargetValid: false,
                        huntPostKillPlan: PkNone)

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

# ---------------------------------------------------------------------------
# Intent helpers
# ---------------------------------------------------------------------------

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

proc setPhase(scratch: var ModeScratch, tick: int,
              phase: HuntingPhase, reason: string) =
  if scratch.huntPhase == phase:
    return
  scratch.huntPrevPhase = scratch.huntPhase
  scratch.huntPhase = phase
  scratch.huntPhaseStartedTick = tick
  scratch.huntPhaseChanged = true
  scratch.huntPhaseReason = reason
  if phase == HpAlibi or phase == HpSeeking:
    scratch.huntCoverTargetIndex = -1
    scratch.huntCoverLoiterUntilTick = 0
    scratch.huntCoverFakeUntilTick = 0
  if phase != HpPostKill:
    scratch.huntPostKillTargetValid = false
    scratch.huntPostKillPlan = PkNone

# ---------------------------------------------------------------------------
# Target, witness, and location scoring
# ---------------------------------------------------------------------------

proc isCrewTarget(belief: Belief, color: int): bool =
  if color < 0 or color >= PlayerColorCount:
    return false
  if color == belief.self.colorIndex:
    return false
  if color in belief.self.knownImposterColors:
    return false
  let ps = belief.memory.perPlayer[color]
  if ps.role == RoleImposter or not ps.alive:
    return false
  true

proc visibleCrewTargets(belief: Belief): seq[CrewmateMatch] =
  for cm in belief.percep.visibleCrewmates:
    if isCrewTarget(belief, cm.colorIndex):
      result.add cm

proc visibleTargetColors(crewmates: openArray[CrewmateMatch]): seq[int] =
  for cm in crewmates:
    if cm.colorIndex >= 0 and cm.colorIndex notin result:
      result.add cm.colorIndex

proc knownCrewSeenCount(belief: Belief,
                        visibleCrew: openArray[CrewmateMatch]): int =
  var seen: seq[int] = @[]
  for cm in visibleCrew:
    if isCrewTarget(belief, cm.colorIndex) and cm.colorIndex notin seen:
      seen.add cm.colorIndex
  for ci in 0 ..< PlayerColorCount:
    let ps = belief.memory.perPlayer[ci]
    if ps.lastSeenTick > 0 and isCrewTarget(belief, ci) and ci notin seen:
      seen.add ci
  seen.len

proc allowedWitnesses(belief: Belief, params: ModeParams,
                      visibleCrew: openArray[CrewmateMatch]): int =
  result = max(params.huntMaxWitnesses, 0)
  let knownCrew = knownCrewSeenCount(belief, visibleCrew)
  if knownCrew > 0 and knownCrew <= HuntLateGameKnownCrewMax:
    result = max(result, HuntLateGameWitnessBonus)

proc allowedWitnesses(belief: Belief, params: ModeParams): int =
  var noVisibleCrew: seq[CrewmateMatch] = @[]
  allowedWitnesses(belief, params, noVisibleCrew)

proc visibleWitnesses(crewmates: openArray[CrewmateMatch],
                      targetColor: int): int =
  for cm in crewmates:
    if cm.colorIndex >= 0 and cm.colorIndex != targetColor:
      inc result

proc memoryThreatAt(belief: Belief, x, y, targetColor: int,
                    visibleColors: openArray[int]): int =
  ## Count players whose last-seen position is recent and close enough
  ## that they may walk into this location soon.
  for ci in 0 ..< PlayerColorCount:
    if ci == targetColor or ci in visibleColors:
      continue
    if not isCrewTarget(belief, ci):
      continue
    let ps = belief.memory.perPlayer[ci]
    if ps.lastSeenTick <= 0:
      continue
    let age = belief.tick - ps.lastSeenTick
    if age < 0 or age > HuntWitnessMemoryTicks:
      continue
    let reach = HuntWitnessBaseRadius + age * HuntWitnessPixelsPerTick
    if heuristic(ps.lastSeenX, ps.lastSeenY, x, y) <= reach:
      inc result

proc memoryThreatAt(belief: Belief, x, y, targetColor: int): int =
  var noVisibleColors: seq[int] = @[]
  memoryThreatAt(belief, x, y, targetColor, noVisibleColors)

proc memoryCrowdNear(belief: Belief, x, y, targetColor: int): int =
  for ci in 0 ..< PlayerColorCount:
    if ci == targetColor or not isCrewTarget(belief, ci):
      continue
    let ps = belief.memory.perPlayer[ci]
    if ps.lastSeenTick <= 0:
      continue
    let age = belief.tick - ps.lastSeenTick
    if age <= HuntSeekingMemoryTicks and
       heuristic(ps.lastSeenX, ps.lastSeenY, x, y) <= HuntIsolationRadius:
      inc result

proc roomTrafficScore(room: string): int =
  if room.len == 0 or room == "unknown":
    return 24
  if room.contains("Cafeteria"):
    return 45
  if room.contains("Hallway"):
    return 36
  if room.contains("Admin") or room.contains("Storage"):
    return 32
  if room.contains("Weapons") or room.contains("Shields") or
     room.contains("Coms"):
    return 24
  if room.contains("O2") or room.contains("Nav"):
    return 18
  if room.contains("Electrical") or room.contains("Electrial") or
     room.contains("Security") or room.contains("MedBay") or
     room.contains("Reactor") or room.contains("Engine"):
    return 8
  20

proc roomPrivacyScore(room: string): int =
  result = 54 - roomTrafficScore(room)
  if room.contains("Electrical") or room.contains("Electrial") or
     room.contains("Security") or room.contains("MedBay") or
     room.contains("Reactor") or room.contains("Engine") or
     room.contains("Nav"):
    result += 16
  if room.contains("Hallway"):
    result -= 22
  if room.contains("Cafeteria"):
    result -= 28

proc nearestVentDistance(x, y: int): int =
  result = high(int)
  let graph = navGraph()[]
  for wp in graph.waypoints:
    if wp.kind == WpVent:
      let d = heuristic(x, y, wp.x, wp.y)
      if d < result:
        result = d
  if result == high(int):
    result = 9999

proc killSiteScore(x, y: int): int =
  let room = roomNameAt(referenceData.map, x, y)
  result = roomPrivacyScore(room)
  let ventDist = nearestVentDistance(x, y)
  if ventDist <= HuntVentNearDistance:
    result += 24 + (HuntVentNearDistance - ventDist)

proc crewProximityScore(belief: Belief, x, y: int): int =
  ## Positive alibi score for places where a crewmate is likely to see us.
  let camX = belief.percep.cameraX
  let camY = belief.percep.cameraY
  for cm in visibleCrewTargets(belief):
    let wx = visibleCrewmateWorldX(camX, cm.x)
    let wy = visibleCrewmateWorldY(camY, cm.y)
    let d = heuristic(x, y, wx, wy)
    if d <= 140:
      result += max(0, 140 - d)
  for ci in 0 ..< PlayerColorCount:
    if not isCrewTarget(belief, ci):
      continue
    let ps = belief.memory.perPlayer[ci]
    if ps.lastSeenTick <= 0:
      continue
    let age = belief.tick - ps.lastSeenTick
    if age < 0 or age > HuntSeekingMemoryTicks:
      continue
    let d = heuristic(x, y, ps.lastSeenX, ps.lastSeenY)
    if d <= 160:
      result += max(0, 120 - d) - (age div 8)

proc isAtStation(selfX, selfY: int, stationIdx: int): bool =
  let tasks = referenceData.map.tasks
  if stationIdx < 0 or stationIdx >= tasks.len:
    return false
  let ts = tasks[stationIdx]
  (selfX >= ts.x and selfX < ts.x + ts.w and
   selfY >= ts.y and selfY < ts.y + ts.h) or
    heuristic(selfX, selfY, ts.passableCX, ts.passableCY) <= 10

proc pickAlibiStation(belief: Belief, selfX, selfY: int): int =
  let tasks = referenceData.map.tasks
  var bestScore = low(int)
  result = -1
  for i, ts in tasks:
    let cx = ts.passableCX
    let cy = ts.passableCY
    let room = roomNameAt(referenceData.map, cx, cy)
    var score = roomTrafficScore(room) * 3
    score += crewProximityScore(belief, cx, cy)
    score -= heuristic(selfX, selfY, cx, cy) div 5
    if heuristic(selfX, selfY, cx, cy) < 24:
      score -= 30
    if score > bestScore:
      bestScore = score
      result = i

proc pickSeekingStation(belief: Belief, selfX, selfY: int,
                        currentIdx: int): int =
  let tasks = referenceData.map.tasks
  var bestScore = low(int)
  result = -1
  for i, ts in tasks:
    if i == currentIdx:
      continue
    let cx = ts.passableCX
    let cy = ts.passableCY
    var score = killSiteScore(cx, cy) * 3
    score -= roomTrafficScore(roomNameAt(referenceData.map, cx, cy))
    score -= heuristic(selfX, selfY, cx, cy) div 6
    score -= memoryThreatAt(belief, cx, cy, -1) * 70
    if heuristic(selfX, selfY, cx, cy) < 30:
      score -= 40
    if score > bestScore:
      bestScore = score
      result = i

proc bestVisibleTarget(belief: Belief, params: ModeParams,
                       crewmates: openArray[CrewmateMatch]): HuntCandidate =
  let camX = belief.percep.cameraX
  let camY = belief.percep.cameraY
  let visibleColors = visibleTargetColors(crewmates)
  let allowed = allowedWitnesses(belief, params, crewmates)

  for cm in crewmates:
    let ci = cm.colorIndex
    if params.huntPreferredTarget >= 0 and ci != params.huntPreferredTarget and
       not params.huntOpportunistic:
      continue
    let wx = visibleCrewmateWorldX(camX, cm.x)
    let wy = visibleCrewmateWorldY(camY, cm.y)
    let witnesses = visibleWitnesses(crewmates, ci)
    let predicted = memoryThreatAt(belief, wx, wy, ci, visibleColors)
    let risk = witnesses + predicted
    if witnesses > allowed or risk > allowed + 1:
      continue

    var score = killSiteScore(wx, wy) * 2
    score -= risk * 120
    score -= heuristic(belief.percep.selfX, belief.percep.selfY, wx, wy) div 3
    if ci == params.huntPreferredTarget:
      score += 220
    if not result.valid or score > result.score:
      result = HuntCandidate(valid: true,
                             color: ci,
                             x: wx, y: wy,
                             dist: heuristic(belief.percep.selfX,
                                             belief.percep.selfY, wx, wy),
                             witnesses: witnesses,
                             predictedWitnesses: predicted,
                             score: score)

proc bestMemoryTarget(belief: Belief, params: ModeParams,
                      selfX, selfY: int): HuntCandidate =
  let preferredOnly = params.huntPreferredTarget >= 0 and
                      not params.huntOpportunistic
  let allowed = allowedWitnesses(belief, params)
  for ci in 0 ..< PlayerColorCount:
    if not isCrewTarget(belief, ci):
      continue
    if preferredOnly and ci != params.huntPreferredTarget:
      continue
    let ps = belief.memory.perPlayer[ci]
    if ps.lastSeenTick <= 0:
      continue
    let age = belief.tick - ps.lastSeenTick
    if age < 0 or age > HuntSeekingMemoryTicks:
      continue

    let crowd = memoryCrowdNear(belief, ps.lastSeenX, ps.lastSeenY, ci)
    let predicted = memoryThreatAt(belief, ps.lastSeenX, ps.lastSeenY, ci)
    var score = killSiteScore(ps.lastSeenX, ps.lastSeenY) * 2
    score -= heuristic(selfX, selfY, ps.lastSeenX, ps.lastSeenY) div 4
    score -= age div 3
    score -= (crowd + predicted) * 80
    if ci == params.huntPreferredTarget:
      score += 260
    if crowd <= allowed + 1:
      score += 40

    if not result.valid or score > result.score:
      result = HuntCandidate(valid: true,
                             color: ci,
                             x: ps.lastSeenX, y: ps.lastSeenY,
                             dist: heuristic(selfX, selfY,
                                             ps.lastSeenX, ps.lastSeenY),
                             witnesses: crowd,
                             predictedWitnesses: predicted,
                             score: score)

# ---------------------------------------------------------------------------
# Kill confirmation and post-kill planning
# ---------------------------------------------------------------------------

proc bodyNearTarget(belief: Belief, targetX, targetY: int,
                    preStrikeCount: int): bool =
  if belief.percep.visibleBodies.len <= preStrikeCount:
    return false
  let camX = belief.percep.cameraX
  let camY = belief.percep.cameraY
  for body in belief.percep.visibleBodies:
    let bx = visibleCrewmateWorldX(camX, body.x)
    let by = visibleCrewmateWorldY(camY, body.y)
    if heuristic(bx, by, targetX, targetY) <= HuntKillConfirmRadius:
      return true
  false

proc startStrike(belief: Belief, cand: HuntCandidate,
                 scratch: var ModeScratch) =
  if scratch.huntStrikeTick >= 0:
    return
  scratch.huntTargetColor = cand.color
  scratch.huntLastKillTargetColor = cand.color
  scratch.huntLastSightingTick = belief.tick
  scratch.huntLastSeenX = cand.x
  scratch.huntLastSeenY = cand.y
  scratch.huntStrikeTick = belief.tick
  scratch.huntStrikeTargetX = cand.x
  scratch.huntStrikeTargetY = cand.y
  scratch.huntPreStrikeBodyCount = belief.percep.visibleBodies.len
  scratch.huntPreStrikeKillReady = belief.percep.killReady
  scratch.huntFailedKillColor = -1
  setPhase(scratch, belief.tick, HpStrike, "strike_ready")

proc findVentEscape(belief: Belief, fromX, fromY, strikeX, strikeY: int):
    tuple[found: bool, x: int, y: int] =
  if belief.percep.visibleCrewmates.len > 1:
    return (false, 0, 0)
  let graph = navGraph()[]
  var entryIdx = -1
  var entryDist = high(int)
  for i, wp in graph.waypoints:
    if wp.kind != WpVent or wp.ventGroup == '\0':
      continue
    let d = heuristic(fromX, fromY, wp.x, wp.y)
    if d < entryDist:
      entryDist = d
      entryIdx = i
  if entryIdx < 0 or entryDist > HuntPostKillVentRadius:
    return (false, 0, 0)

  let group = graph.waypoints[entryIdx].ventGroup
  var exitIdx = -1
  var bestAway = -1
  for i, wp in graph.waypoints:
    if i == entryIdx or wp.kind != WpVent or wp.ventGroup != group:
      continue
    let away = heuristic(strikeX, strikeY, wp.x, wp.y)
    if away > bestAway:
      bestAway = away
      exitIdx = i
  if exitIdx < 0:
    return (false, 0, 0)
  (true, graph.waypoints[exitIdx].x, graph.waypoints[exitIdx].y)

proc pickPostKillStation(belief: Belief, selfX, selfY,
                         strikeX, strikeY: int): int =
  let tasks = referenceData.map.tasks
  var bestScore = low(int)
  result = -1
  for i, ts in tasks:
    let cx = ts.passableCX
    let cy = ts.passableCY
    let distStrike = heuristic(strikeX, strikeY, cx, cy)
    var score = roomTrafficScore(roomNameAt(referenceData.map, cx, cy)) * 2
    score += min(distStrike, 220)
    score += crewProximityScore(belief, cx, cy) div 2
    score -= heuristic(selfX, selfY, cx, cy) div 3
    if distStrike < HuntPostKillAvoidRadius:
      score -= 120
    if score > bestScore:
      bestScore = score
      result = i

proc pickOtherPlayerPoint(belief: Belief, strikeColor: int):
    tuple[found: bool, x: int, y: int] =
  var bestAge = high(int)
  for ci in 0 ..< PlayerColorCount:
    if ci == strikeColor or not isCrewTarget(belief, ci):
      continue
    let ps = belief.memory.perPlayer[ci]
    if ps.lastSeenTick <= 0:
      continue
    let age = belief.tick - ps.lastSeenTick
    if age >= 0 and age < bestAge and age <= HuntSeekingMemoryTicks:
      bestAge = age
      result = (true, ps.lastSeenX, ps.lastSeenY)

proc choosePostKillTarget(belief: Belief, scratch: var ModeScratch) =
  if scratch.huntPostKillTargetValid:
    return

  let fromX = if belief.percep.localized:
                belief.percep.selfX
              else:
                scratch.huntStrikeTargetX
  let fromY = if belief.percep.localized:
                belief.percep.selfY
              else:
                scratch.huntStrikeTargetY
  let strikeX = scratch.huntStrikeTargetX
  let strikeY = scratch.huntStrikeTargetY

  let vent = findVentEscape(belief, fromX, fromY, strikeX, strikeY)
  if vent.found:
    scratch.huntPostKillTargetX = vent.x
    scratch.huntPostKillTargetY = vent.y
    scratch.huntPostKillTargetValid = true
    scratch.huntPostKillPlan = PkVent
    return

  let stationIdx = pickPostKillStation(belief, fromX, fromY, strikeX, strikeY)
  if stationIdx >= 0:
    let ts = referenceData.map.tasks[stationIdx]
    scratch.huntCoverTargetIndex = stationIdx
    scratch.huntPostKillTargetX = ts.passableCX
    scratch.huntPostKillTargetY = ts.passableCY
    scratch.huntPostKillTargetValid = true
    scratch.huntPostKillPlan = PkStation
    return

  let other = pickOtherPlayerPoint(belief, scratch.huntLastKillTargetColor)
  if other.found:
    scratch.huntPostKillTargetX = other.x
    scratch.huntPostKillTargetY = other.y
    scratch.huntPostKillTargetValid = true
    scratch.huntPostKillPlan = PkPlayer

proc enterPostKill(belief: Belief, scratch: var ModeScratch, reason: string) =
  if scratch.huntPhase != HpPostKill:
    setPhase(scratch, belief.tick, HpPostKill, reason)
    scratch.huntPostKillUntilTick = belief.tick + HuntPostKillTicks
    scratch.huntPostKillTargetValid = false
    scratch.huntPostKillPlan = PkNone
    scratch.huntCoverTargetIndex = -1
    scratch.huntCoverLoiterUntilTick = 0
    scratch.huntCoverFakeUntilTick = 0
  scratch.huntStrikeTick = -1
  scratch.huntTargetColor = -1
  choosePostKillTarget(belief, scratch)

# ---------------------------------------------------------------------------
# Phase behavior
# ---------------------------------------------------------------------------

proc alibiIntent(belief: Belief, params: ModeParams,
                 scratch: var ModeScratch): ActionIntent =
  if params.huntCoverMode == ModeIdle:
    scratch.huntCoverTargetIndex = -1
    scratch.huntCoverLoiterUntilTick = 0
    scratch.huntCoverFakeUntilTick = 0
    return noOpIntent()

  let tasks = referenceData.map.tasks
  if tasks.len == 0:
    return noOpIntent()

  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY

  if scratch.huntCoverLoiterUntilTick > 0 and
     belief.tick < scratch.huntCoverLoiterUntilTick:
    if belief.tick < scratch.huntCoverFakeUntilTick:
      return holdIntent()
    return noOpIntent()

  if scratch.huntCoverLoiterUntilTick > 0 and
     belief.tick >= scratch.huntCoverLoiterUntilTick:
    scratch.huntCoverTargetIndex = -1
    scratch.huntCoverLoiterUntilTick = 0
    scratch.huntCoverFakeUntilTick = 0

  if scratch.huntCoverTargetIndex < 0:
    scratch.huntCoverTargetIndex = pickAlibiStation(belief, selfX, selfY)

  if scratch.huntCoverTargetIndex < 0:
    return noOpIntent()

  if isAtStation(selfX, selfY, scratch.huntCoverTargetIndex):
    scratch.huntCoverLoiterUntilTick = belief.tick + HuntCoverLoiterTicks
    scratch.huntCoverFakeUntilTick =
      belief.tick + min(HuntAlibiFakeHoldTicks, HuntCoverLoiterTicks)
    return holdIntent()

  let ts = tasks[scratch.huntCoverTargetIndex]
  moveIntent(ts.passableCX, ts.passableCY)

proc seekingIntent(belief: Belief, params: ModeParams,
                   scratch: var ModeScratch): ActionIntent =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY

  let mem = bestMemoryTarget(belief, params, selfX, selfY)
  if mem.valid:
    scratch.huntTargetColor = mem.color
    scratch.huntLastSightingTick = belief.tick
    scratch.huntLastSeenX = mem.x
    scratch.huntLastSeenY = mem.y
    return moveIntent(mem.x, mem.y)

  let tasks = referenceData.map.tasks
  if tasks.len == 0:
    return noOpIntent()

  if params.huntCoverMode == ModeIdle:
    scratch.huntCoverTargetIndex = -1
    return noOpIntent()

  if scratch.huntCoverTargetIndex >= 0 and
     isAtStation(selfX, selfY, scratch.huntCoverTargetIndex):
    scratch.huntCoverTargetIndex = -1

  if scratch.huntCoverTargetIndex < 0:
    scratch.huntCoverTargetIndex =
      pickSeekingStation(belief, selfX, selfY, scratch.huntCoverTargetIndex)

  if scratch.huntCoverTargetIndex < 0:
    return noOpIntent()

  let ts = tasks[scratch.huntCoverTargetIndex]
  moveIntent(ts.passableCX, ts.passableCY)

proc postKillIntent(belief: Belief, scratch: var ModeScratch): ActionIntent =
  if not belief.percep.localized:
    return noOpIntent()

  choosePostKillTarget(belief, scratch)
  if not scratch.huntPostKillTargetValid:
    return noOpIntent()

  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  if heuristic(selfX, selfY,
               scratch.huntPostKillTargetX,
               scratch.huntPostKillTargetY) <= 12:
    if scratch.huntPostKillPlan == PkVent:
      let stationIdx = pickPostKillStation(
        belief, selfX, selfY,
        scratch.huntStrikeTargetX, scratch.huntStrikeTargetY)
      if stationIdx >= 0:
        let ts = referenceData.map.tasks[stationIdx]
        scratch.huntCoverTargetIndex = stationIdx
        scratch.huntPostKillTargetX = ts.passableCX
        scratch.huntPostKillTargetY = ts.passableCY
        scratch.huntPostKillPlan = PkStation
        scratch.huntCoverFakeUntilTick = 0
      else:
        return noOpIntent()

    if scratch.huntPostKillPlan == PkStation:
      if scratch.huntCoverFakeUntilTick <= 0:
        scratch.huntCoverFakeUntilTick =
          belief.tick + min(HuntPostKillFakeHoldTicks,
                            max(1, scratch.huntPostKillUntilTick - belief.tick))
        return holdIntent()
      if belief.tick < scratch.huntCoverFakeUntilTick:
        return holdIntent()
      return noOpIntent()

    return noOpIntent()

  moveIntent(scratch.huntPostKillTargetX, scratch.huntPostKillTargetY)

# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let localized = belief.percep.localized
  let killReady = belief.percep.killReady

  # Strike confirmation/disengage must run even during short localization
  # drops caused by the kill animation. It uses saved strike coordinates.
  if scratch.huntStrikeTick >= 0:
    let elapsed = belief.tick - scratch.huntStrikeTick
    let gotBody = bodyNearTarget(belief,
                                 scratch.huntStrikeTargetX,
                                 scratch.huntStrikeTargetY,
                                 scratch.huntPreStrikeBodyCount)
    let cooldownReset = scratch.huntPreStrikeKillReady and not killReady
    if cooldownReset:
      scratch.huntKillConfirmed = true
      enterPostKill(belief, scratch, "cooldown_reset")
    elif gotBody and elapsed >= 1:
      enterPostKill(belief, scratch, "body_seen_near_strike")
    elif elapsed >= HuntStrikeCommitTicks:
      if scratch.huntPreStrikeKillReady and killReady and
         scratch.huntLastKillTargetColor >= 0 and not gotBody:
        scratch.huntFailedKillColor = scratch.huntLastKillTargetColor
      enterPostKill(belief, scratch, "strike_disengage")
    elif elapsed <= HuntKillConfirmTicks:
      setPhase(scratch, belief.tick, HpStrike, "strike_window")
      return moveIntent(scratch.huntStrikeTargetX,
                        scratch.huntStrikeTargetY,
                        DisciplineKillStrike)
    else:
      if scratch.huntPreStrikeKillReady and killReady and
         scratch.huntLastKillTargetColor >= 0 and not gotBody:
        scratch.huntFailedKillColor = scratch.huntLastKillTargetColor
      enterPostKill(belief, scratch, "confirm_timeout")

  if scratch.huntPhase == HpPostKill:
    if belief.tick < scratch.huntPostKillUntilTick:
      return postKillIntent(belief, scratch)
    if killReady:
      setPhase(scratch, belief.tick, HpSeeking, "post_kill_done_ready")
    else:
      setPhase(scratch, belief.tick, HpAlibi, "post_kill_done_cooldown")

  if not localized:
    return noOpIntent()

  let crewmates = visibleCrewTargets(belief)

  if not killReady:
    setPhase(scratch, belief.tick, HpAlibi, "cooldown_active")
    scratch.huntStrikeTick = -1
    scratch.huntTargetColor = -1
    return alibiIntent(belief, params, scratch)

  let visible = bestVisibleTarget(belief, params, crewmates)
  if visible.valid:
    scratch.huntTargetColor = visible.color
    scratch.huntLastSightingTick = belief.tick
    scratch.huntLastSeenX = visible.x
    scratch.huntLastSeenY = visible.y

    let allowed = allowedWitnesses(belief, params, crewmates)
    let risk = visible.witnesses + visible.predictedWitnesses
    if visible.dist <= HuntKillStrikeRange and risk <= allowed:
      startStrike(belief, visible, scratch)
      return moveIntent(visible.x, visible.y, DisciplineKillStrike)

    setPhase(scratch, belief.tick, HpStalking, "target_visible")
    return moveIntent(visible.x, visible.y, DisciplineKillStrike)

  setPhase(scratch, belief.tick, HpSeeking, "kill_ready_seek")
  seekingIntent(belief, params, scratch)

proc huntingPhaseStr(phase: HuntingPhase): string =
  case phase
  of HpAlibi: "alibi"
  of HpSeeking: "seeking"
  of HpStalking: "stalking"
  of HpStrike: "strike"
  of HpPostKill: "post_kill"

proc postKillPlanStr(plan: PostKillPlanKind): string =
  case plan
  of PkNone: "none"
  of PkVent: "vent"
  of PkStation: "station"
  of PkPlayer: "player"

proc summarizeForLlm*(belief: Belief, params: ModeParams,
                      scratch: ModeScratch): JsonNode =
  result = newJObject()
  result["status"] = newJString("imposter_hunting")
  result["phase"] = newJString(huntingPhaseStr(scratch.huntPhase))
  result["phase_reason"] = newJString(scratch.huntPhaseReason)
  result["phase_ticks"] =
    newJInt(max(0, belief.tick - scratch.huntPhaseStartedTick))
  result["ticks_in_mode"] = newJInt(max(0, belief.tick - scratch.huntEnterTick))
  result["preferred_target"] = newJInt(params.huntPreferredTarget)
  result["active_target_color"] = newJInt(scratch.huntTargetColor)
  result["max_witnesses"] = newJInt(params.huntMaxWitnesses)
  result["opportunistic"] = newJBool(params.huntOpportunistic)
  result["cover_mode"] =
    newJString(if params.huntCoverMode == ModeIdle: "idle" else: "pretending")
  if scratch.huntLastSightingTick > 0:
    result["last_sighting_age_ticks"] =
      newJInt(max(0, belief.tick - scratch.huntLastSightingTick))
    result["last_seen_position"] = %*[scratch.huntLastSeenX, scratch.huntLastSeenY]
  result["cover_target_index"] = newJInt(scratch.huntCoverTargetIndex)
  if scratch.huntCoverTargetIndex >= 0 and
     scratch.huntCoverTargetIndex < referenceData.map.tasks.len:
    let ts = referenceData.map.tasks[scratch.huntCoverTargetIndex]
    result["cover_target_name"] = newJString(ts.name)
    result["cover_target_room"] =
      newJString(roomNameAt(referenceData.map, ts.passableCX, ts.passableCY))
  result["cover_loiter_ticks_remaining"] =
    newJInt(max(0, scratch.huntCoverLoiterUntilTick - belief.tick))
  result["cover_fake_ticks_remaining"] =
    newJInt(max(0, scratch.huntCoverFakeUntilTick - belief.tick))
  result["strike_active"] = newJBool(scratch.huntStrikeTick >= 0)
  if scratch.huntStrikeTick >= 0:
    result["strike_age_ticks"] =
      newJInt(max(0, belief.tick - scratch.huntStrikeTick))
    result["strike_position"] = %*[scratch.huntStrikeTargetX,
                                   scratch.huntStrikeTargetY]
  result["failed_kill_color"] = newJInt(scratch.huntFailedKillColor)
  result["post_kill_ticks_remaining"] =
    newJInt(max(0, scratch.huntPostKillUntilTick - belief.tick))
  result["post_kill_plan"] = newJString(postKillPlanStr(scratch.huntPostKillPlan))
  if scratch.huntPostKillTargetValid:
    result["post_kill_target"] = %*[scratch.huntPostKillTargetX,
                                    scratch.huntPostKillTargetY]
