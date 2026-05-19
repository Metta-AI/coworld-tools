## Domain checks for step-by-step state diff logging.

import
  environment, items, state_diff, test_utils, types

proc checkCaptureSnapshotBasics() =
  ## Verify snapshot capture of top-level state.
  echo "Testing state diff snapshot basics"

  let env = makeEmptyEnv()
  env.currentStep = 42
  env.victoryWinner = -1

  let snap = captureSnapshot(env)
  doAssert snap.step == 42
  doAssert snap.victoryWinner == -1

proc checkCaptureSnapshotAgents() =
  ## Verify snapshot capture of agent counts and classes.
  echo "Testing state diff agent capture"

  let env = makeEmptyEnv()
  discard addAgentAt(env, 0, ivec2(10, 10))
  discard addAgentAt(env, 1, ivec2(12, 10))
  discard addAgentAt(env, 2, ivec2(14, 10))
  discard addAgentAt(env, MapAgentsPerTeam, ivec2(30, 30))

  var snap = captureSnapshot(env)
  doAssert snap.teams[0].aliveCount == 3
  doAssert snap.teams[0].villagerCount == 3
  doAssert snap.teams[1].aliveCount == 1
  doAssert snap.teams[1].villagerCount == 1

  let deadEnv = makeEmptyEnv()
  discard addAgentAt(deadEnv, 0, ivec2(10, 10))
  discard addAgentAt(deadEnv, 1, ivec2(12, 10))
  deadEnv.terminated[1] = 1.0
  snap = captureSnapshot(deadEnv)
  doAssert snap.teams[0].aliveCount == 1
  doAssert snap.teams[0].deadCount == 1

  let classEnv = makeEmptyEnv()
  discard addAgentAt(classEnv, 0, ivec2(10, 10), unitClass = UnitVillager)
  discard addAgentAt(classEnv, 1, ivec2(12, 10), unitClass = UnitArcher)
  discard addAgentAt(classEnv, 2, ivec2(14, 10), unitClass = UnitKnight)
  discard addAgentAt(
    classEnv,
    3,
    ivec2(16, 10),
    unitClass = UnitManAtArms
  )
  discard addAgentAt(classEnv, 4, ivec2(18, 10), unitClass = UnitMonk)

  snap = captureSnapshot(classEnv)
  doAssert snap.teams[0].villagerCount == 1
  doAssert snap.teams[0].archerCount == 1
  doAssert snap.teams[0].knightCount == 1
  doAssert snap.teams[0].manAtArmsCount == 1
  doAssert snap.teams[0].monkCount == 1

proc checkCaptureSnapshotResourcesAndBuildings() =
  ## Verify snapshot capture of resources, buildings, and projectiles.
  echo "Testing state diff resources and buildings"

  let env = makeEmptyEnv()
  setStockpile(env, 0, ResourceFood, 100)
  setStockpile(env, 0, ResourceWood, 200)
  setStockpile(env, 0, ResourceGold, 50)
  setStockpile(env, 0, ResourceStone, 30)
  setStockpile(env, 0, ResourceWater, 10)

  discard addBuilding(env, House, ivec2(5, 5), 0)
  discard addBuilding(env, House, ivec2(7, 5), 0)
  discard addBuilding(env, House, ivec2(9, 5), 0)
  discard addBuilding(env, GuardTower, ivec2(11, 5), 0)
  discard addBuilding(env, Wall, ivec2(13, 5), 0)
  discard addBuilding(env, Market, ivec2(15, 5), 0)
  discard addBuilding(env, Castle, ivec2(17, 5), 0)

  env.projectiles.add(Projectile(countdown: 5, lifetime: 10))
  env.projectiles.add(Projectile(countdown: 3, lifetime: 10))

  let snap = captureSnapshot(env)
  doAssert snap.teams[0].food == 100
  doAssert snap.teams[0].wood == 200
  doAssert snap.teams[0].gold == 50
  doAssert snap.teams[0].stone == 30
  doAssert snap.teams[0].water == 10
  doAssert snap.houseCount == 3
  doAssert snap.towerCount == 1
  doAssert snap.wallCount == 1
  doAssert snap.marketCount == 1
  doAssert snap.castleCount == 1
  doAssert snap.projectileCount == 2

  let emptyEnv = makeEmptyEnv()
  let emptySnap = captureSnapshot(emptyEnv)
  doAssert emptySnap.step == 0
  doAssert emptySnap.victoryWinner == -1
  doAssert emptySnap.thingCount == 0
  doAssert emptySnap.projectileCount == 0
  doAssert emptySnap.houseCount == 0
  for teamId in 0 ..< MapRoomObjectsTeams:
    doAssert emptySnap.teams[teamId].aliveCount == 0
    doAssert emptySnap.teams[teamId].food == 0

proc checkCompareAndLog() =
  ## Verify snapshot comparison across several state changes.
  echo "Testing state diff compareAndLog"

  let env = makeEmptyEnv()
  setStockpile(env, 0, ResourceFood, 100)
  let snap1 = captureSnapshot(env)

  setStockpile(env, 0, ResourceFood, 150)
  let snap2 = captureSnapshot(env)
  compareAndLog(snap1, snap2)
  doAssert snap1.teams[0].food == 100
  doAssert snap2.teams[0].food == 150

  let buildEnv = makeEmptyEnv()
  let buildSnap1 = captureSnapshot(buildEnv)
  discard addBuilding(buildEnv, House, ivec2(5, 5), 0)
  let buildSnap2 = captureSnapshot(buildEnv)
  compareAndLog(buildSnap1, buildSnap2)
  doAssert buildSnap1.houseCount == 0
  doAssert buildSnap2.houseCount == 1

  let sameEnv = makeEmptyEnv()
  setStockpile(sameEnv, 0, ResourceFood, 100)
  discard addBuilding(sameEnv, House, ivec2(5, 5), 0)
  let sameSnap1 = captureSnapshot(sameEnv)
  let sameSnap2 = captureSnapshot(sameEnv)
  compareAndLog(sameSnap1, sameSnap2)
  doAssert sameSnap1.houseCount == sameSnap2.houseCount
  doAssert sameSnap1.teams[0].food == sameSnap2.teams[0].food

  let victoryEnv = makeEmptyEnv()
  victoryEnv.victoryWinner = -1
  let victorySnap1 = captureSnapshot(victoryEnv)
  victoryEnv.victoryWinner = 0
  let victorySnap2 = captureSnapshot(victoryEnv)
  compareAndLog(victorySnap1, victorySnap2)
  doAssert victorySnap1.victoryWinner == -1
  doAssert victorySnap2.victoryWinner == 0

  let deathEnv = makeEmptyEnv()
  discard addAgentAt(deathEnv, 0, ivec2(10, 10))
  discard addAgentAt(deathEnv, 1, ivec2(12, 10))
  let deathSnap1 = captureSnapshot(deathEnv)
  deathEnv.terminated[1] = 1.0
  let deathSnap2 = captureSnapshot(deathEnv)
  compareAndLog(deathSnap1, deathSnap2)
  doAssert deathSnap1.teams[0].aliveCount == 2
  doAssert deathSnap2.teams[0].aliveCount == 1
  doAssert deathSnap2.teams[0].deadCount == 1

proc checkPrePostStep() =
  ## Verify pre-step and post-step integration.
  echo "Testing state diff pre/post step"

  let env = makeEmptyEnv()
  setStockpile(env, 0, ResourceFood, 100)

  capturePreStep(env)
  doAssert diffState.hasSnapshot

  setStockpile(env, 0, ResourceFood, 200)
  env.currentStep = 1
  comparePostStep(env)
  doAssert diffState.prevSnapshot.teams[0].food == 200

  initStateDiff()
  let emptyEnv = makeEmptyEnv()
  comparePostStep(emptyEnv)
  doAssert not diffState.hasSnapshot

  capturePreStep(emptyEnv)
  doAssert diffState.hasSnapshot
  initStateDiff()
  doAssert not diffState.hasSnapshot

  initStateDiff()
  diffState.hasSnapshot = true
  ensureStateDiffInit()
  doAssert diffState.hasSnapshot

proc checkMultiTeamTracking() =
  ## Verify snapshots and diffs track teams independently.
  echo "Testing state diff multi-team tracking"

  let env = makeEmptyEnv()
  setStockpile(env, 0, ResourceFood, 100)
  setStockpile(env, 0, ResourceWood, 200)
  if MapRoomObjectsTeams > 1:
    setStockpile(env, 1, ResourceFood, 50)
    setStockpile(env, 1, ResourceGold, 300)

  let snap = captureSnapshot(env)
  doAssert snap.teams[0].food == 100
  doAssert snap.teams[0].wood == 200
  if MapRoomObjectsTeams > 1:
    doAssert snap.teams[1].food == 50
    doAssert snap.teams[1].gold == 300

  let diffEnv = makeEmptyEnv()
  setStockpile(diffEnv, 0, ResourceFood, 100)
  if MapRoomObjectsTeams > 1:
    setStockpile(diffEnv, 1, ResourceFood, 100)
  let snap1 = captureSnapshot(diffEnv)
  setStockpile(diffEnv, 0, ResourceFood, 200)
  let snap2 = captureSnapshot(diffEnv)
  compareAndLog(snap1, snap2)
  doAssert snap2.teams[0].food == 200
  if MapRoomObjectsTeams > 1:
    doAssert snap2.teams[1].food == 100

checkCaptureSnapshotBasics()
checkCaptureSnapshotAgents()
checkCaptureSnapshotResourcesAndBuildings()
checkCompareAndLog()
checkPrePostStep()
checkMultiTeamTracking()

echo "State diff domain checks passed"
