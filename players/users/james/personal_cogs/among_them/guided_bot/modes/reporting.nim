## Mode: `reporting`. A body is known; navigate to report range and
## press A. Crewmate only (imposters don't self-report in the default
## fallback — the LLM could issue this in phase 3).
##
## Target of the `task_completing -> reporting` reflex (DESIGN.md §5.8).
## The reflex provides the body's world position in `repBodyLocation`.
##
## Phase 6.2 rewrite: adds body-visibility check, approach timeout,
## in-range timeout, and give-up signalling. See REPORTING_DESIGN.md.
##
## Strategy:
##   - Navigate toward the body location using DisciplineReport.
##   - The action layer steers toward the target and presses A when in
##     report range (within ReportRange pixels).
##   - Give up if: body disappears for 36 frames, approach takes >10s,
##     or in-range A-press doesn't trigger a meeting within 3s.
##   - Success is detected by reflex 4 (voting_screen_appeared), which
##     fires automatically when the server starts a meeting.

import std/json
import ../types
import ../action
import ../tuning
import ../perception/geometry

const
  Name* = ModeReporting
  ## ReportRange must match the action layer's constant. Duplicated
  ## here for the in-range check; the action layer's copy is
  ## authoritative for the actual button press.
  ReportRangeLocal = 20

proc isLegalFor*(belief: Belief): bool =
  belief.self.role == RoleCrewmate and belief.self.alive and not belief.self.isGhost

proc defaultParamsFor*(belief: Belief): ModeParams =
  discard belief
  ModeParams(mode: ModeReporting,
             repBodyLocation: Point(x: 0, y: 0))

proc onEnter*(belief: Belief, params: ModeParams, scratch: var ModeScratch) =
  scratch = ModeScratch(mode: ModeReporting,
                        repEnterTick: belief.tick,
                        repBodyMissCount: 0,
                        repReachedRange: false,
                        repInRangeTicks: 0,
                        repGaveUp: false,
                        repGaveUpReason: "")
  discard params

proc onExit*(belief: Belief, scratch: var ModeScratch) =
  discard belief
  discard scratch

# ---------------------------------------------------------------------------
# Body-visibility check
# ---------------------------------------------------------------------------

proc bodyStillVisible(belief: Belief, targetX, targetY: int): bool =
  ## True if any visible body is within ReportBodyMatchRadius of the
  ## target world position. Handles camera jitter and sprite-anchor
  ## offsets.
  let camX = belief.percep.cameraX
  let camY = belief.percep.cameraY
  for body in belief.percep.visibleBodies:
    let bx = visibleCrewmateWorldX(camX, body.x)
    let by = visibleCrewmateWorldY(camY, body.y)
    let dist = heuristic(bx, by, targetX, targetY)
    if dist <= ReportBodyMatchRadius:
      return true
  false

# ---------------------------------------------------------------------------
# Decide
# ---------------------------------------------------------------------------

proc decide*(belief: Belief, params: ModeParams,
             scratch: var ModeScratch): ActionIntent =
  let localized = belief.percep.localized

  if not localized:
    return noOpIntent()

  # Already gave up — return no-op. bot.nim will switch to default.
  if scratch.repGaveUp:
    return noOpIntent()

  let selfX = belief.percep.selfX
  let selfY = belief.percep.selfY
  let targetX = params.repBodyLocation.x
  let targetY = params.repBodyLocation.y
  let dist = heuristic(selfX, selfY, targetX, targetY)
  let inRange = dist <= ReportRangeLocal

  # --- Body-visibility check ---
  if bodyStillVisible(belief, targetX, targetY):
    scratch.repBodyMissCount = 0
  else:
    scratch.repBodyMissCount += 1
    if scratch.repBodyMissCount >= ReportBodyMissFrames:
      scratch.repGaveUp = true
      scratch.repGaveUpReason = "body_gone"
      return noOpIntent()

  # --- Track range entry ---
  if inRange and not scratch.repReachedRange:
    scratch.repReachedRange = true

  # --- Approach timeout ---
  if not scratch.repReachedRange:
    let elapsed = belief.tick - scratch.repEnterTick
    if elapsed >= ReportApproachTimeoutTicks:
      scratch.repGaveUp = true
      scratch.repGaveUpReason = "approach_timeout"
      return noOpIntent()

  # --- In-range timeout ---
  if scratch.repReachedRange:
    if inRange:
      scratch.repInRangeTicks += 1
    # Don't reset on momentary out-of-range (camera jitter).
    if scratch.repInRangeTicks >= ReportInRangeTimeoutTicks:
      # We've been pressing A in range for 3s and no meeting started.
      scratch.repGaveUp = true
      scratch.repGaveUpReason = "in_range_timeout"
      return noOpIntent()

  # --- Normal behavior: steer toward body, press A in range ---
  ActionIntent(
    steerTo: params.repBodyLocation,
    steerValid: true,
    pressA: false,  # Action layer handles ButtonA via DisciplineReport.
    pressB: false,
    cursor: CursorNone,
    chat: "",
    discipline: DisciplineReport
  )

proc summarizeForLlm*(belief: Belief, params: ModeParams,
                      scratch: ModeScratch): JsonNode =
  result = newJObject()
  result["status"] = newJString("reporting_body")
  result["body_location"] = %*[params.repBodyLocation.x, params.repBodyLocation.y]
  result["ticks_in_mode"] = newJInt(max(0, belief.tick - scratch.repEnterTick))
  result["body_miss_count"] = newJInt(scratch.repBodyMissCount)
  result["reached_range"] = newJBool(scratch.repReachedRange)
  result["in_range_ticks"] = newJInt(scratch.repInRangeTicks)
  result["gave_up"] = newJBool(scratch.repGaveUp)
  if scratch.repGaveUpReason.len > 0:
    result["gave_up_reason"] = newJString(scratch.repGaveUpReason)
  if belief.percep.localized:
    result["distance_to_body"] = newJInt(
      heuristic(belief.percep.selfX, belief.percep.selfY,
                params.repBodyLocation.x, params.repBodyLocation.y))
