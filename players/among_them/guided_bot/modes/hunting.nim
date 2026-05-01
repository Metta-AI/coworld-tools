## Mode: `hunting`. Imposter closing on a kill. Also the imposter
## default directive (DESIGN.md §9.1) with `opportunistic: true` and no
## specific target.
##
## Strategy:
##   - If a preferred target is set and visible, steer toward them.
##   - If opportunistic and a lone crewmate is visible with kill ready
##     and few enough witnesses, close and strike.
##   - Otherwise, delegate to cover mode behavior (wander like pretending).
##
## The kill strike uses DisciplineKillStrike: the action layer steers
## toward the target and presses A when in range (within KillStrikeRange
## pixels). The kill button must be ready (belief.percep.killReady).

import ../types
import ../action
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
                        hunEnterTick: belief.tick)

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let localized = belief.percep.localized
  let killReady = belief.percep.killReady

  if not localized:
    return noOpIntent()

  # Count visible non-imposter witnesses (crewmates we can see).
  let witnessCount = belief.percep.visibleCrewmates.len

  # --- Look for a kill target ---

  # Check preferred target first.
  if params.hunPreferredTarget >= 0 and killReady:
    for cm in belief.percep.visibleCrewmates:
      if cm.colorIndex == params.hunPreferredTarget:
        # Target found — check witnesses.
        let otherWitnesses = witnessCount - 1  # Exclude the target.
        if otherWitnesses <= params.hunMaxWitnesses:
          let targetWX = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
          let targetWY = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
          scratch.hunTargetColor = cm.colorIndex
          scratch.hunLastSightingTick = belief.tick
          return ActionIntent(
            steerTo: Point(x: targetWX, y: targetWY),
            steerValid: true,
            pressA: false,  # Action layer handles ButtonA via discipline.
            pressB: false,
            cursor: CursorNone,
            chat: "",
            discipline: DisciplineKillStrike
          )

  # Opportunistic: if any lone crewmate and kill is ready.
  if params.hunOpportunistic and killReady and witnessCount == 1:
    let cm = belief.percep.visibleCrewmates[0]
    let targetWX = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
    let targetWY = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
    scratch.hunTargetColor = cm.colorIndex
    scratch.hunLastSightingTick = belief.tick
    return ActionIntent(
      steerTo: Point(x: targetWX, y: targetWY),
      steerValid: true,
      pressA: false,
      pressB: false,
      cursor: CursorNone,
      chat: "",
      discipline: DisciplineKillStrike
    )

  # --- No kill opportunity — cover behavior ---
  # Wander toward a task station to look like a crewmate.
  let tasks = referenceData.map.tasks
  if tasks.len > 0:
    # Pick a task to walk toward (simple: nearest one).
    var bestDist = high(int)
    var bestIdx = 0
    for i, ts in tasks:
      let cx = ts.x + ts.w div 2
      let cy = ts.y + ts.h div 2
      let d = heuristic(selfX, selfY, cx, cy)
      if d < bestDist:
        bestDist = d
        bestIdx = i
    let ts = tasks[bestIdx]
    return ActionIntent(
      steerTo: Point(x: ts.x + ts.w div 2, y: ts.y + ts.h div 2),
      steerValid: true,
      pressA: false,
      pressB: false,
      cursor: CursorNone,
      chat: "",
      discipline: DisciplineNormal
    )

  noOpIntent()
