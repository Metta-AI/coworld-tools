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
## The kill strike uses DisciplineKillStrike: the action layer steers
## toward the target and presses A when in range (within KillStrikeRange
## pixels, now 20 to match the server's KillRange).

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
             hunPreferredTarget: -1,
             hunMaxWitnesses: 0,
             hunOpportunistic: true,
             hunCoverMode: ModePretending)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeHunting,
                        hunTargetColor: params.hunPreferredTarget,
                        hunLastSightingTick: 0,
                        hunEnterTick: belief.tick,
                        hunLastSeenX: 0,
                        hunLastSeenY: 0,
                        hunCoverTargetIndex: -1,
                        hunCoverLoiterUntilTick: 0,
                        hunStrikeTick: -1,
                        hunStrikeTargetX: 0,
                        hunStrikeTargetY: 0,
                        hunPreStrikeBodyCount: 0,
                        hunPreStrikeKillReady: false,
                        hunKillConfirmed: false)

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

  let witnessCount = belief.percep.visibleCrewmates.len

  # =======================================================================
  # Kill confirmation check (runs before new pursuit decisions)
  # =======================================================================
  if scratch.hunStrikeTick >= 0:
    let elapsed = belief.tick - scratch.hunStrikeTick
    if elapsed <= HuntKillConfirmTicks:
      let gotBody = bodyNearTarget(belief,
                                   scratch.hunStrikeTargetX,
                                   scratch.hunStrikeTargetY,
                                   scratch.hunPreStrikeBodyCount)
      let cooldownReset = scratch.hunPreStrikeKillReady and not killReady
      if gotBody and cooldownReset:
        # Kill confirmed. Drop to cover, wait out cooldown.
        scratch.hunKillConfirmed = true
        scratch.hunStrikeTick = -1
        scratch.hunTargetColor = -1
        # Fall through to cover behavior below.
      else:
        # Still waiting for confirmation — keep pressing A at target.
        return ActionIntent(
          steerTo: Point(x: scratch.hunStrikeTargetX,
                         y: scratch.hunStrikeTargetY),
          steerValid: true,
          pressA: false, pressB: false,
          cursor: CursorNone, chat: "",
          discipline: DisciplineKillStrike)
    else:
      # Confirm window expired — kill missed or not confirmed.
      scratch.hunStrikeTick = -1

  # =======================================================================
  # Look for a kill target
  # =======================================================================

  # Check preferred target first.
  if params.hunPreferredTarget >= 0 and killReady:
    for cm in belief.percep.visibleCrewmates:
      if cm.colorIndex == params.hunPreferredTarget:
        let otherWitnesses = witnessCount - 1
        if otherWitnesses <= params.hunMaxWitnesses:
          let targetWX = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
          let targetWY = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
          scratch.hunTargetColor = cm.colorIndex
          scratch.hunLastSightingTick = belief.tick
          scratch.hunLastSeenX = targetWX
          scratch.hunLastSeenY = targetWY
          # Record strike state for confirmation.
          if scratch.hunStrikeTick < 0:
            scratch.hunStrikeTick = belief.tick
            scratch.hunStrikeTargetX = targetWX
            scratch.hunStrikeTargetY = targetWY
            scratch.hunPreStrikeBodyCount = belief.percep.visibleBodies.len
            scratch.hunPreStrikeKillReady = killReady
          return ActionIntent(
            steerTo: Point(x: targetWX, y: targetWY),
            steerValid: true,
            pressA: false, pressB: false,
            cursor: CursorNone, chat: "",
            discipline: DisciplineKillStrike)

  # Opportunistic: if any lone crewmate and kill is ready.
  if params.hunOpportunistic and killReady and witnessCount == 1:
    let cm = belief.percep.visibleCrewmates[0]
    let targetWX = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
    let targetWY = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
    scratch.hunTargetColor = cm.colorIndex
    scratch.hunLastSightingTick = belief.tick
    scratch.hunLastSeenX = targetWX
    scratch.hunLastSeenY = targetWY
    # Record strike state for confirmation.
    if scratch.hunStrikeTick < 0:
      scratch.hunStrikeTick = belief.tick
      scratch.hunStrikeTargetX = targetWX
      scratch.hunStrikeTargetY = targetWY
      scratch.hunPreStrikeBodyCount = belief.percep.visibleBodies.len
      scratch.hunPreStrikeKillReady = killReady
    return ActionIntent(
      steerTo: Point(x: targetWX, y: targetWY),
      steerValid: true,
      pressA: false, pressB: false,
      cursor: CursorNone, chat: "",
      discipline: DisciplineKillStrike)

  # =======================================================================
  # Target memory — pursue last-known position
  # =======================================================================
  if scratch.hunTargetColor >= 0 and
     scratch.hunLastSightingTick > 0 and
     belief.tick - scratch.hunLastSightingTick <= HuntMemoryTicks:
    # Target was recently visible — steer toward last-known position.
    # Use DisciplineNormal (not kill-strike) since we can't kill what
    # we can't see.
    return ActionIntent(
      steerTo: Point(x: scratch.hunLastSeenX, y: scratch.hunLastSeenY),
      steerValid: true,
      pressA: false, pressB: false,
      cursor: CursorNone, chat: "",
      discipline: DisciplineNormal)

  # Memory expired — clear target.
  scratch.hunTargetColor = -1
  scratch.hunStrikeTick = -1

  # =======================================================================
  # Cover patrol — station-to-station rotation
  # =======================================================================
  let tasks = referenceData.map.tasks
  if tasks.len == 0:
    return noOpIntent()

  # Currently loitering at a station?
  if scratch.hunCoverLoiterUntilTick > 0 and
     belief.tick < scratch.hunCoverLoiterUntilTick:
    return noOpIntent()

  # Loiter finished — pick a new station.
  if scratch.hunCoverLoiterUntilTick > 0 and
     belief.tick >= scratch.hunCoverLoiterUntilTick:
    scratch.hunCoverTargetIndex = -1
    scratch.hunCoverLoiterUntilTick = 0

  # No cover target — pick one.
  if scratch.hunCoverTargetIndex < 0:
    scratch.hunCoverTargetIndex = pickCoverStation(
      selfX, selfY, scratch.hunCoverTargetIndex)

  if scratch.hunCoverTargetIndex < 0:
    return noOpIntent()

  # Am I at the cover station?
  if isAtStation(selfX, selfY, scratch.hunCoverTargetIndex):
    scratch.hunCoverLoiterUntilTick = belief.tick + HuntCoverLoiterTicks
    return noOpIntent()

  # Navigate to cover station.
  let ts = tasks[scratch.hunCoverTargetIndex]
  ActionIntent(
    steerTo: Point(x: ts.passableCX, y: ts.passableCY),
    steerValid: true,
    pressA: false, pressB: false,
    cursor: CursorNone, chat: "",
    discipline: DisciplineNormal)
