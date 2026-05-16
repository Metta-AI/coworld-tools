## Mode: `idle`. Pre-localization and pre-role-detection behavior.
## Wanders toward the map centre to give the localizer gameplay-map
## pixels and to keep Coworld validation/gameplay active from the first frame.
##
## Once the role is detected, `reconcileDirective` in `bot.nim`
## immediately transitions to task_completing (crew) or hunting
## (imposter), so this mode only runs for the first few frames.
## See DESIGN.md §5.4.

import std/json
import ../types
import ../action
import ../tuning
import ../perception/data
import ../perception/geometry

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
    var goalX = MapWidth div 2
    var goalY = MapHeight div 2
    if params.idleNearGroup and belief.percep.visibleCrewmates.len > 0:
      let cm = belief.percep.visibleCrewmates[0]
      goalX = visibleCrewmateWorldX(belief.percep.cameraX, cm.x)
      goalY = visibleCrewmateWorldY(belief.percep.cameraY, cm.y)
    elif params.idleLingerValid:
      goalX = params.idleLingerAt.x
      goalY = params.idleLingerAt.y
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

proc summarizeForLlm*(belief: Belief, params: ModeParams,
                      scratch: ModeScratch): JsonNode =
  result = newJObject()
  result["status"] = newJString("idle_or_pre_role_wander")
  result["ticks_in_mode"] = newJInt(max(0, belief.tick - scratch.idleEnterTick))
  result["localized"] = newJBool(belief.percep.localized)
  result["interstitial"] = newJBool(belief.percep.interstitial)
  result["linger_valid"] = newJBool(params.idleLingerValid)
  if params.idleLingerValid:
    result["linger_at"] = %*[params.idleLingerAt.x, params.idleLingerAt.y]
  result["near_group"] = newJBool(params.idleNearGroup)
