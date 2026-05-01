## Mode: `idle`. Pre-localization and pre-role-detection behavior.
## Wanders toward the map centre to give the localizer gameplay-map
## pixels and to pass the cogames 10-step validation gate.
##
## Once the role is detected, `reconcileDirective` in `bot.nim`
## immediately transitions to task_completing (crew) or hunting
## (imposter), so this mode only runs for the first few frames.
## See DESIGN.md §5.4.

import ../types
import ../action
import ../tuning
import ../perception/data

const Name* = ModeIdle

proc isLegalFor*(belief: Belief): bool =
  ## Legal in any role, any phase except meeting/game over.
  discard belief
  true

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeIdle,
             idleLingerValid: false,
             idleNearGroup: true)

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeIdle, idleEnterTick: belief.tick)
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  discard params

  # During interstitials (voting screens, role reveals, game-over),
  # there's nothing to move toward — emit noop.
  if belief.percep.interstitial:
    return noOpIntent()

  # Wander toward the map centre. DisciplineWander emits raw direction
  # buttons without A* or localization, so the bot physically moves
  # even before the localizer locks. Once localized, steerTo aims at
  # the map centre; before that, cycle through cardinal directions.
  let elapsed = belief.tick - scratch.idleEnterTick
  let dirPhase = (elapsed div IdleWanderPeriod) mod 4

  if belief.percep.localized:
    # Steer toward the map centre.
    let goalX = MapWidth div 2
    let goalY = MapHeight div 2
    return ActionIntent(
      steerTo: Point(x: goalX, y: goalY),
      steerValid: true,
      pressA: false,
      pressB: false,
      cursor: CursorNone,
      chat: "",
      discipline: DisciplineWander
    )

  # Not localized — cycle through cardinal directions so the
  # localizer sees fresh map pixels. The direction phase is
  # encoded in steerTo.x for the action layer.
  ActionIntent(
    steerTo: Point(x: dirPhase, y: 0),
    steerValid: false,
    pressA: false,
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineWander
  )
