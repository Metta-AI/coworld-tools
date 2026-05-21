## Focused checks for LLM mode params and mode summaries.
##
## Run:
##   nim c -r -d:release --threads:on --mm:orc \
##       among_them/guided_bot/test/mode_params_snapshot_test.nim

import std/[json, strformat]
import ../types
import ../belief
import ../mode_registry
import ../snapshot
import ../perception/data
import ../tuning
import ../modes/task_completing as taskMode
import ../modes/pretending as pretendingMode
import ../modes/hunting as huntingMode
import ../reflex

var failures = 0

proc expect(cond: bool, label: string) =
  if not cond:
    stderr.writeLine "FAIL: ", label
    inc failures

proc expectEq[T](got, want: T, label: string) =
  if got != want:
    stderr.writeLine &"FAIL: {label}: got {got}, want {want}"
    inc failures

proc gameplayBelief(role: BotRole): Belief =
  result = initBelief()
  result.tick = 100
  result.self.role = role
  result.self.alive = true
  result.self.isGhost = false
  result.self.phase = PhaseGameplay
  result.percep.localized = true
  result.percep.selfX = 40
  result.percep.selfY = 40
  result.percep.killReady = false
  result.ensureTaskSlotsInitialized()

proc completeExpectedCrewTasks(belief: var Belief) =
  for i in 0 ..< min(CrewPostTaskCompleteCount, belief.tasks.slots.len):
    belief.tasks.slots[i].state = TaskCompleted

proc testTaskCompletingUsesIndexTarget() =
  var belief = gameplayBelief(RoleCrewmate)
  let targetIdx = min(3, referenceData.map.tasks.high)
  let ts = referenceData.map.tasks[targetIdx]
  let params = ModeParams(
    mode: ModeTaskCompleting,
    tcTarget: TaskTarget(kind: TgtIndex, taskIndex: targetIdx, roomId: -1),
    tcAbandonOnNearbyBody: true)
  var scratch: ModeScratch
  taskMode.onEnter(belief, params, scratch)

  let intent = taskMode.decide(belief, params, scratch)

  expectEq(scratch.tcLockedTaskIndex, targetIdx,
           "task_completing locks LLM target index")
  expect(intent.steerValid, "task_completing target emits movement")
  expectEq(intent.steerTo.x, ts.passableCX, "task_completing target x")
  expectEq(intent.steerTo.y, ts.passableCY, "task_completing target y")

proc testTaskCompletingPostTaskShadowsCrewmate() =
  var belief = gameplayBelief(RoleCrewmate)
  belief.self.colorIndex = 0
  belief.completeExpectedCrewTasks()
  belief.percep.cameraX = 0
  belief.percep.cameraY = 0
  belief.percep.visibleCrewmates.add CrewmateMatch(
    x: 120, y: 80, colorIndex: 2, flipH: false)
  let params = ModeParams(
    mode: ModeTaskCompleting,
    tcTarget: TaskTarget(kind: TgtNearestMandatory, taskIndex: -1, roomId: -1),
    tcAbandonOnNearbyBody: true)
  var scratch: ModeScratch
  taskMode.onEnter(belief, params, scratch)

  let intent = taskMode.decide(belief, params, scratch)

  expect(intent.steerValid, "post-task crew behavior emits movement")
  expectEq(intent.steerTo.x, 122, "post-task crew shadows crewmate x")
  expectEq(intent.steerTo.y, 88, "post-task crew shadows crewmate y")
  expect(not intent.pressA, "post-task shadowing does not press emergency")
  expectEq(scratch.tcLockedTaskIndex, -1,
           "post-task crew behavior suppresses geometry fallback")

proc testTaskCompletingPostTaskCallsButtonWithEvidence() =
  var belief = gameplayBelief(RoleCrewmate)
  belief.self.colorIndex = 0
  belief.completeExpectedCrewTasks()
  let button = referenceData.map.button
  let buttonX = button.x + button.w div 2
  let buttonY = button.y + button.h div 2
  belief.percep.selfX = buttonX
  belief.percep.selfY = buttonY
  belief.memory.perPlayer[3].nearVentEvidenceScore = CrewButtonEvidenceThreshold
  let params = ModeParams(
    mode: ModeTaskCompleting,
    tcTarget: TaskTarget(kind: TgtNearestMandatory, taskIndex: -1, roomId: -1),
    tcAbandonOnNearbyBody: true)
  var scratch: ModeScratch
  taskMode.onEnter(belief, params, scratch)

  let intent = taskMode.decide(belief, params, scratch)

  expect(intent.steerValid, "post-task evidence button emits movement")
  expectEq(intent.steerTo.x, buttonX, "post-task evidence button x")
  expectEq(intent.steerTo.y, buttonY, "post-task evidence button y")
  expect(intent.pressA, "post-task evidence presses emergency in range")

proc testPretendingUsesIndexTarget() =
  var belief = gameplayBelief(RoleImposter)
  let targetIdx = min(4, referenceData.map.tasks.high)
  let ts = referenceData.map.tasks[targetIdx]
  let params = ModeParams(
    mode: ModePretending,
    preTarget: TaskTarget(kind: TgtIndex, taskIndex: targetIdx, roomId: -1),
    preLoiterTicks: 60,
    preMaySwapOnWitness: true)
  var scratch: ModeScratch
  pretendingMode.onEnter(belief, params, scratch)

  let intent = pretendingMode.decide(belief, params, scratch)

  expectEq(scratch.preFakeTargetIndex, targetIdx,
           "pretending locks LLM target index")
  expect(intent.steerValid, "pretending target emits movement")
  expectEq(intent.steerTo.x, ts.passableCX, "pretending target x")
  expectEq(intent.steerTo.y, ts.passableCY, "pretending target y")

proc testHuntingCoverModeIdleDoesNotPatrol() =
  var belief = gameplayBelief(RoleImposter)
  belief.percep.killReady = false
  let params = ModeParams(
    mode: ModeHunting,
    huntPreferredTarget: -1,
    huntMaxWitnesses: 0,
    huntOpportunistic: true,
    huntCoverMode: ModeIdle)
  var scratch: ModeScratch
  huntingMode.onEnter(belief, params, scratch)

  let intent = huntingMode.decide(belief, params, scratch)

  expect(not intent.steerValid, "idle cover mode should not pick cover patrol")
  expectEq(scratch.huntCoverTargetIndex, -1,
           "idle cover mode leaves cover target unset")

proc testTaskBodyAbandonParamGatesReportReflex() =
  var belief = gameplayBelief(RoleCrewmate)
  belief.directive = Directive(
    mode: ModeTaskCompleting,
    params: ModeParams(
      mode: ModeTaskCompleting,
      tcTarget: TaskTarget(kind: TgtNearestMandatory, taskIndex: -1, roomId: -1),
      tcAbandonOnNearbyBody: false),
    source: SourceLlm,
    issuedAtTick: belief.tick,
    ttlTicks: 360,
    reflexName: "",
    reasoning: "")
  belief.percep.visibleBodies.add BodyMatch(x: 64, y: 64, colorIndex: 2)
  var state = initReflexState()
  var scratch: ModeScratch
  taskMode.onEnter(belief, belief.directive.params, scratch)

  let result = evaluateReflexes(belief, state, scratch)

  expect(not result.fired,
         "tcAbandonOnNearbyBody=false suppresses body report reflex")

proc testSnapshotIncludesParamsAndModeSummary() =
  var belief = gameplayBelief(RoleCrewmate)
  belief.directive = Directive(
    mode: ModeTaskCompleting,
    params: ModeParams(
      mode: ModeTaskCompleting,
      tcTarget: TaskTarget(kind: TgtIndex, taskIndex: 2, roomId: -1),
      tcAbandonOnNearbyBody: true),
    source: SourceLlm,
    issuedAtTick: 80,
    ttlTicks: 360,
    reflexName: "",
    reasoning: "")
  var scratch: ModeScratch
  taskMode.onEnter(belief, belief.directive.params, scratch)
  let summary = summarizeForLlm(belief.directive.mode, belief,
                                belief.directive.params, scratch)
  let snap = parseJson(renderSnapshot(belief, summary))
  let current = snap["current_mode"]

  expectEq(current["params"]["target"]["kind"].getStr(), "index",
           "snapshot carries current mode target kind")
  expectEq(current["params"]["target"]["task_index"].getInt(), 2,
           "snapshot carries current mode target index")
  expectEq(current["summary"]["phase"].getStr(), "navigate",
           "snapshot carries mode summary")

proc beliefForMode(mode: ModeName): Belief =
  let role =
    if mode in [ModePretending, ModeHunting, ModeFleeing, ModeAlibiBuilding]:
      RoleImposter
    elif mode == ModeIdle:
      RoleUnknown
    else:
      RoleCrewmate
  result = gameplayBelief(role)
  if mode == ModeMeeting:
    result.self.phase = PhaseVoting
    result.percep.interstitial = true
    result.percep.votingPlayerCount = 8
    result.percep.votingCursor = 0

proc testAllModesHaveLlmSummary() =
  const modes = [
    ModeIdle, ModeTaskCompleting, ModeReporting, ModePretending,
    ModeHunting, ModeFleeing, ModeAlibiBuilding, ModeMeeting]

  for mode in modes:
    var belief = beliefForMode(mode)
    let params = defaultParamsFor(mode, belief)
    var scratch: ModeScratch
    onEnter(mode, belief, params, scratch)
    let summary = summarizeForLlm(mode, belief, params, scratch)
    expect(summary.kind == JObject, $mode & " summary is object")
    expect(summary.hasKey("status"), $mode & " summary has status")

proc main() =
  testTaskCompletingUsesIndexTarget()
  testTaskCompletingPostTaskShadowsCrewmate()
  testTaskCompletingPostTaskCallsButtonWithEvidence()
  testPretendingUsesIndexTarget()
  testHuntingCoverModeIdleDoesNotPatrol()
  testTaskBodyAbandonParamGatesReportReflex()
  testSnapshotIncludesParamsAndModeSummary()
  testAllModesHaveLlmSummary()

  if failures > 0:
    quit(1)
  echo &"OK (mode params + snapshot tests passed)"

when isMainModule:
  main()
