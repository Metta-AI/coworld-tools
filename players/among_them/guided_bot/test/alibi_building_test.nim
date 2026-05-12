## Focused alibi-building mode checks.
##
## Run:
##   nim c -r -d:release --threads:on --mm:orc \
##       among_them/guided_bot/test/alibi_building_test.nim

import std/strformat
import ../types
import ../belief
import ../perception/geometry
import ../modes/alibi_building as alibiMode

var failures = 0

proc expect(cond: bool, label: string) =
  if not cond:
    stderr.writeLine "FAIL: ", label
    inc failures

proc expectEq[T](got, want: T, label: string) =
  if got != want:
    stderr.writeLine &"FAIL: {label}: got {got}, want {want}"
    inc failures

proc params(color: int): ModeParams =
  ModeParams(mode: ModeAlibiBuilding,
             aliCompanionColor: color,
             aliRoomId: -1,
             aliMinDurationTicks: 120)

proc makeBelief(tick: int, selfX, selfY: int,
                visible: openArray[tuple[color, screenX, screenY: int]]): Belief =
  result = initBelief()
  result.tick = tick
  result.self.role = RoleImposter
  result.self.colorIndex = 4
  result.self.alive = true
  result.self.isGhost = false
  result.self.phase = PhaseGameplay
  result.percep.localized = true
  result.percep.selfX = selfX
  result.percep.selfY = selfY
  result.percep.cameraX = selfX - PlayerWorldOffX
  result.percep.cameraY = selfY - PlayerWorldOffY
  for ci in 0 ..< PlayerColorCount:
    result.memory.perPlayer[ci].alive = true
  for item in visible:
    result.percep.visibleCrewmates.add CrewmateMatch(
      x: item.screenX, y: item.screenY, colorIndex: item.color, flipH: false)
    let worldX = visibleCrewmateWorldX(result.percep.cameraX, item.screenX)
    let worldY = visibleCrewmateWorldY(result.percep.cameraY, item.screenY)
    result.memory.perPlayer[item.color].lastSeenTick = tick
    result.memory.perPlayer[item.color].lastSeenX = worldX
    result.memory.perPlayer[item.color].lastSeenY = worldY

proc makeScratch(belief: Belief, p: ModeParams): ModeScratch =
  alibiMode.onEnter(belief, p, result)

proc testFollowsDistantTarget() =
  var belief = makeBelief(10, 100, 100, [(2, 120, 64)])
  let targetX = visibleCrewmateWorldX(belief.percep.cameraX, 120)
  let targetY = visibleCrewmateWorldY(belief.percep.cameraY, 64)
  belief.percep.selfX = targetX - 100
  belief.percep.selfY = targetY
  let p = params(2)
  var scratch = makeScratch(belief, p)

  let intent = alibiMode.decide(belief, p, scratch)

  expect(intent.steerValid, "distant companion should produce movement")
  expectEq(intent.steerTo.x, targetX, "distant companion target x")
  expectEq(intent.steerTo.y, targetY, "distant companion target y")
  expectEq(scratch.aliTargetColor, 2, "tracks selected companion color")
  expectEq(scratch.aliLastSeenTick, 10, "records visible companion tick")

proc testRejectsKnownImposterCompanion() =
  var belief = makeBelief(20, 100, 100, [(2, 120, 64), (3, 64, 120)])
  belief.self.knownImposterColors = @[2]
  let p = params(2)
  var scratch = makeScratch(belief, p)

  discard alibiMode.decide(belief, p, scratch)

  expectEq(scratch.aliTargetColor, 3,
           "known imposter companion is replaced by visible crew target")

proc testLostSightInterruptsFakeTask() =
  var belief = makeBelief(30, 100, 100, [(2, 90, 64)])
  let targetX = visibleCrewmateWorldX(belief.percep.cameraX, 90)
  let targetY = visibleCrewmateWorldY(belief.percep.cameraY, 64)
  let p = params(2)
  var scratch = makeScratch(belief, p)
  discard alibiMode.decide(belief, p, scratch)

  belief.tick = 31
  belief.percep.visibleCrewmates.setLen(0)
  scratch.aliFakeHoldUntilTick = 100

  let intent = alibiMode.decide(belief, p, scratch)

  expect(not intent.pressA, "losing sight interrupts fake task hold")
  expect(intent.steerValid, "lost companion should be reacquired")
  expectEq(intent.steerTo.x, targetX, "reacquire last seen x")
  expectEq(intent.steerTo.y, targetY, "reacquire last seen y")

proc main() =
  testFollowsDistantTarget()
  testRejectsKnownImposterCompanion()
  testLostSightInterruptsFakeTask()

  if failures > 0:
    quit(1)
  echo &"OK (alibi_building tests passed)"

when isMainModule:
  main()
