## Mode: `hunting`. Imposter closing on a kill. Also the imposter
## default directive (DESIGN.md §9.1) with `opportunistic: true` and no
## specific target.
##
## Phase 6.4 rewrite: cover patrol (station-to-station rotation),
## short-term target memory (2s pursuit after losing visual), and
## kill confirmation (body appeared near target + killReady went false).
## See HUNTING_DESIGN.md.
##
## Strategy:
##   - If a preferred target is set and visible, steer toward them.
##   - If opportunistic and a lone crewmate is visible with kill ready
##     and few enough witnesses, close and strike.
##   - If a target was recently visible (within HuntMemoryTicks),
##     pursue their last-known position.
##   - Otherwise, patrol between task stations (cover behavior) to
##     find isolated crewmates.
##
## Kill flow:
##   1. Target acquired (visible, killReady, witnesses ok) → pursue
##      with DisciplineKillStrike (action layer presses A at ≤20px).
##   2. Once within HuntKillStrikeRange → record strike state, start
##      confirmation timer.
##   3. During confirm window: watch for new body + killReady→false.
##   4. Confirmed → drop to cover. Missed → resume patrol.

import ../types
import ../action
import ../tuning
import ../perception/data
import ../perception/geometry

const Name* = ModeHunting

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleImposter and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeHunting,
             huntPreferredTarget: -1,
             huntMaxWitnesses: 0,
             huntOpportunistic: true,
             huntCoverMode: ModePretending)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeHunting,
                        huntTargetColor: params.huntPreferredTarget,
                        huntLastSightingTick: 0,
                        huntEnterTick: belief.tick,
                        huntLastSeenX: 0,
                        huntLastSeenY: 0,
                        huntCoverTargetIndex: -1,
                        huntCoverLoiterUntilTick: 0,
                        huntStrikeTick: -1,
                        huntStrikeTargetX: 0,
                        huntStrikeTargetY: 0,
                        huntPreStrikeBodyCount: 0,
                        huntPreStrikeKillReady: false,
                        huntKillConfirmed: false)

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

# ---------------------------------------------------------------------------
# Cover patrol helpers
# ---------------------------------------------------------------------------

proc pickCoverStation(selfX, selfY: int, currentIdx: int): int =
  ## Pick a cover patrol station. Avoids re-picking the current one
  ## and stations that are too close (d <= 30).
  let tasks = referenceData.map.tasks
  if tasks.len == 0:
    return -1
  # Rotate based on a simple offset from the current station.
  let startOffset = if currentIdx >= 0: (currentIdx + 1) mod tasks.len else: 0
  var bestDist = high(int)
  var bestIdx = -1
  for i in 0 ..< tasks.len:
    let idx = (startOffset + i) mod tasks.len
    if idx == currentIdx:
      continue
    let ts = tasks[idx]
    let cx = ts.passableCX
    let cy = ts.passableCY
    let d = heuristic(selfX, selfY, cx, cy)
    if d > 30 and d < bestDist:
      bestDist = d
      bestIdx = idx
  # Fallback: if everything is too close, pick the farthest.
  if bestIdx < 0:
    var maxDist = 0
    for i in 0 ..< tasks.len:
      if i == currentIdx: continue
      let ts = tasks[i]
      let cx = ts.passableCX
      let cy = ts.passableCY
      let d = heuristic(selfX, selfY, cx, cy)
      if d > maxDist:
        maxDist = d
        bestIdx = i
  bestIdx

proc isAtStation(selfX, selfY: int, stationIdx: int): bool =
  let tasks = referenceData.map.tasks
  if stationIdx < 0 or stationIdx >= tasks.len:
    return false
  let ts = tasks[stationIdx]
  const margin = 8
  selfX >= ts.x - margin and selfX < ts.x + ts.w + margin and
  selfY >= ts.y - margin and selfY < ts.y + ts.h + margin

# ---------------------------------------------------------------------------
# Kill confirmation helpers
# ---------------------------------------------------------------------------

proc bodyNearTarget(belief: Belief, targetX, targetY: int,
                    preStrikeCount: int): bool =
  ## True if a new body appeared near the strike target position.
  if belief.percep.visibleBodies.len <= preStrikeCount:
    return false
  let camX = belief.percep.cameraX
  let camY = belief.percep.cameraY
  for body in belief.percep.visibleBodies:
    let bx = visibleCrewmateWorldX(camX, body.x)
    let by = visibleCrewmateWorldY(camY, body.y)
    let d = heuristic(bx, by, targetX, targetY)
    if d <= HuntKillConfirmRadius:
      return true
  false

# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let localized = belief.percep.localized
  let killReady = belief.percep.killReady

  if not localized:
    return noOpIntent()

  # Filter visible crewmates to exclude known fellow imposters.
  # witnessCount only counts actual crewmates (potential witnesses/targets).
  let knownImps = belief.self.knownImposterColors
  var crewmatesOnly: seq[CrewmateMatch]
  for cm in belief.percep.visibleCrewmates:
    if cm.colorIndex notin knownImps:
      crewmatesOnly.add cm
  let witnessCount = crewmatesOnly.len

  # =======================================================================
  # Kill confirmation check (runs only after A was pressed — strike sent)
  # =======================================================================
  if scratch.huntStrikeTick >= 0:
    let elapsed = belief.tick - scratch.huntStrikeTick
    if elapsed <= HuntKillConfirmTicks:
      let gotBody = bodyNearTarget(belief,
                                   scratch.huntStrikeTargetX,
                                   scratch.huntStrikeTargetY,
                                   scratch.huntPreStrikeBodyCount)
      let cooldownReset = scratch.huntPreStrikeKillReady and not killReady
      if gotBody and cooldownReset:
        # Kill confirmed. Drop to cover, wait out cooldown.
        scratch.huntKillConfirmed = true
        scratch.huntStrikeTick = -1
        scratch.huntTargetColor = -1
        # Fall through to cover behavior below.
      else:
        # Still waiting for confirmation — keep DisciplineKillStrike
        # at the target position so we stay close if kill didn't land.
        return ActionIntent(
          steerTo: Point(x: scratch.huntStrikeTargetX,
                         y: scratch.huntStrikeTargetY),
          steerValid: true,
          pressA: false, pressB: false,
          cursor: CursorNone, chat: "",
          discipline: DisciplineKillStrike)
    else:
      # Confirm window expired — kill missed or not confirmed.
      scratch.huntStrikeTick = -1

  # =======================================================================
  # Look for a kill target — pursue with DisciplineKillStrike
  # =======================================================================

  # Check preferred target first.
  if params.huntPreferredTarget >= 0 and killReady:
    for cm in crewmatesOnly:
      if cm.colorIndex == params.huntPreferredTarget:
        let otherWitnesses = witnessCount - 1
        if otherWitnesses <= params.huntMaxWitnesses:
          let targetWX = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
          let targetWY = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
          scratch.huntTargetColor = cm.colorIndex
          scratch.huntLastSightingTick = belief.tick
          scratch.huntLastSeenX = targetWX
          scratch.huntLastSeenY = targetWY
          # Check if we just entered kill range → start confirm timer.
          let dist = heuristic(selfX, selfY, targetWX, targetWY)
          if dist <= HuntKillStrikeRange and scratch.huntStrikeTick < 0:
            scratch.huntStrikeTick = belief.tick
            scratch.huntStrikeTargetX = targetWX
            scratch.huntStrikeTargetY = targetWY
            scratch.huntPreStrikeBodyCount = belief.percep.visibleBodies.len
            scratch.huntPreStrikeKillReady = killReady
          return ActionIntent(
            steerTo: Point(x: targetWX, y: targetWY),
            steerValid: true,
            pressA: false, pressB: false,
            cursor: CursorNone, chat: "",
            discipline: DisciplineKillStrike)

  # Opportunistic: if any lone crewmate and kill is ready.
  if params.huntOpportunistic and killReady and witnessCount == 1:
    let cm = crewmatesOnly[0]
    let targetWX = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
    let targetWY = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
    scratch.huntTargetColor = cm.colorIndex
    scratch.huntLastSightingTick = belief.tick
    scratch.huntLastSeenX = targetWX
    scratch.huntLastSeenY = targetWY
    # Check if we just entered kill range → start confirm timer.
    let dist = heuristic(selfX, selfY, targetWX, targetWY)
    if dist <= HuntKillStrikeRange and scratch.huntStrikeTick < 0:
      scratch.huntStrikeTick = belief.tick
      scratch.huntStrikeTargetX = targetWX
      scratch.huntStrikeTargetY = targetWY
      scratch.huntPreStrikeBodyCount = belief.percep.visibleBodies.len
      scratch.huntPreStrikeKillReady = killReady
    return ActionIntent(
      steerTo: Point(x: targetWX, y: targetWY),
      steerValid: true,
      pressA: false, pressB: false,
      cursor: CursorNone, chat: "",
      discipline: DisciplineKillStrike)

  # =======================================================================
  # Target memory — pursue last-known position
  # =======================================================================
  if scratch.huntTargetColor >= 0 and
     scratch.huntLastSightingTick > 0 and
     belief.tick - scratch.huntLastSightingTick <= HuntMemoryTicks:
    # Target was recently visible — steer toward last-known position.
    # Use DisciplineNormal (not kill-strike) since we can't kill what
    # we can't see.
    return ActionIntent(
      steerTo: Point(x: scratch.huntLastSeenX, y: scratch.huntLastSeenY),
      steerValid: true,
      pressA: false, pressB: false,
      cursor: CursorNone, chat: "",
      discipline: DisciplineNormal)

  # Memory expired — clear target.
  scratch.huntTargetColor = -1
  scratch.huntStrikeTick = -1

  # =======================================================================
  # Cover patrol — station-to-station rotation
  # =======================================================================
  let tasks = referenceData.map.tasks
  if tasks.len == 0:
    return noOpIntent()

  # Currently loitering at a station?
  if scratch.huntCoverLoiterUntilTick > 0 and
     belief.tick < scratch.huntCoverLoiterUntilTick:
    return noOpIntent()

  # Loiter finished — pick a new station.
  if scratch.huntCoverLoiterUntilTick > 0 and
     belief.tick >= scratch.huntCoverLoiterUntilTick:
    scratch.huntCoverTargetIndex = -1
    scratch.huntCoverLoiterUntilTick = 0

  # No cover target — pick one.
  if scratch.huntCoverTargetIndex < 0:
    scratch.huntCoverTargetIndex = pickCoverStation(
      selfX, selfY, scratch.huntCoverTargetIndex)

  if scratch.huntCoverTargetIndex < 0:
    return noOpIntent()

  # Am I at the cover station?
  if isAtStation(selfX, selfY, scratch.huntCoverTargetIndex):
    scratch.huntCoverLoiterUntilTick = belief.tick + HuntCoverLoiterTicks
    return noOpIntent()

  # Navigate to cover station.
  let ts = tasks[scratch.huntCoverTargetIndex]
  ActionIntent(
    steerTo: Point(x: ts.passableCX, y: ts.passableCY),
    steerValid: true,
    pressA: false, pressB: false,
    cursor: CursorNone, chat: "",
    discipline: DisciplineNormal)
