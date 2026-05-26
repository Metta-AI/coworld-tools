## Focused reflex-state checks.
##
## Run:
##   nim c -r -d:release --threads:on --mm:orc \
##       among_them/guided_bot/test/reflex_test.nim

import std/strformat
import ../types
import ../belief
import ../reflex
import ../tuning
import ../modes/hunting as huntingMode

var failures = 0

proc expect(cond: bool, label: string) =
  if not cond:
    stderr.writeLine "FAIL: ", label
    inc failures

proc huntingDirective(belief: Belief): Directive =
  let params = huntingMode.defaultParamsFor(belief)
  Directive(
    mode: ModeHunting,
    params: params,
    source: SourceDefault,
    issuedAtTick: belief.tick,
    ttlTicks: 0,
    reflexName: "",
    reasoning: "")

proc makeHuntingBelief(tick: int, bodies: seq[BodyMatch]): Belief =
  result = initBelief()
  result.tick = tick
  result.self.role = RoleImposter
  result.self.colorIndex = 4
  result.self.alive = true
  result.self.isGhost = false
  result.self.phase = PhaseGameplay
  result.percep.cameraX = 100
  result.percep.cameraY = 200
  result.percep.localized = true
  result.percep.selfX = 164
  result.percep.selfY = 264
  result.percep.killReady = true
  result.percep.visibleBodies = bodies
  result.directive = huntingDirective(result)

proc makeHuntingScratch(belief: Belief): ModeScratch =
  let params = belief.directive.params
  huntingMode.onEnter(belief, params, result)

proc bodyAt(x, y: int): BodyMatch =
  BodyMatch(x: x, y: y, colorIndex: 2)

proc testKnownBodySuppressesReentry() =
  var belief = makeHuntingBelief(1, @[bodyAt(40, 40)])
  var scratch = makeHuntingScratch(belief)
  var state = initReflexState()

  let first = evaluateReflexes(belief, state, scratch)
  expect(first.fired and first.reflexName == "body_newly_in_view_flee",
         "first unknown body should trigger flee reflex")

  belief.tick = 2
  belief.percep.visibleBodies = @[]
  discard evaluateReflexes(belief, state, scratch)

  belief.tick = ReflexCooldownTicks + 10
  belief.percep.visibleBodies = @[bodyAt(42, 41)]
  let reentry = evaluateReflexes(belief, state, scratch)
  expect(not reentry.fired,
         "known body re-entering view after cooldown should not retrigger flee")

  belief.tick = ReflexCooldownTicks + 11
  belief.percep.visibleBodies = @[]
  discard evaluateReflexes(belief, state, scratch)

  belief.tick = ReflexCooldownTicks * 2 + 20
  belief.percep.visibleBodies = @[bodyAt(130, 120)]
  let newBody = evaluateReflexes(belief, state, scratch)
  expect(newBody.fired and newBody.reflexName == "body_newly_in_view_flee",
         "far unknown body should still trigger flee reflex")

proc testPostKillBodyIsRememberedWithoutFleeing() =
  var belief = makeHuntingBelief(1, @[bodyAt(55, 44)])
  var scratch = makeHuntingScratch(belief)
  scratch.huntPhase = HpPostKill
  var state = initReflexState()

  let postKill = evaluateReflexes(belief, state, scratch)
  expect(not postKill.fired,
         "body seen during hunting post-kill handling should not fire flee")

  belief.tick = 2
  belief.percep.visibleBodies = @[]
  scratch.huntPhase = HpSeeking
  discard evaluateReflexes(belief, state, scratch)

  belief.tick = ReflexCooldownTicks + 10
  belief.percep.visibleBodies = @[bodyAt(57, 43)]
  let reentry = evaluateReflexes(belief, state, scratch)
  expect(not reentry.fired,
         "post-kill remembered body should not retrigger after re-entry")

proc testMeetingPhaseClearsKnownBodies() =
  var belief = makeHuntingBelief(1, @[bodyAt(40, 40)])
  var scratch = makeHuntingScratch(belief)
  var state = initReflexState()

  discard evaluateReflexes(belief, state, scratch)

  belief.tick = 2
  belief.self.phase = PhaseVoting
  belief.percep.visibleBodies = @[]
  discard evaluateReflexes(belief, state, scratch)

  belief.tick = ReflexCooldownTicks + 10
  belief.self.phase = PhaseGameplay
  belief.percep.visibleBodies = @[bodyAt(41, 39)]
  let afterMeeting = evaluateReflexes(belief, state, scratch)
  expect(afterMeeting.fired and
         afterMeeting.reflexName == "body_newly_in_view_flee",
         "meeting phase should clear known bodies for the next round")

proc main() =
  testKnownBodySuppressesReentry()
  testPostKillBodyIsRememberedWithoutFleeing()
  testMeetingPhaseClearsKnownBodies()

  if failures > 0:
    quit(1)
  echo &"OK (reflex tests passed)"

when isMainModule:
  main()
