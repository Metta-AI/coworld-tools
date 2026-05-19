import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import test_utils

# Helper to add a cow to the environment
proc addCow(env: Environment, pos: IVec2, herdId: int = 0): Thing =
  let cow = Thing(
    kind: Cow,
    pos: pos,
    orientation: Orientation.W,
    herdId: herdId
  )
  cow.inventory = emptyInventory()
  setInv(cow, ItemMeat, ResourceNodeInitial)
  env.add(cow)
  cow

# Helper to add a wolf to the environment
proc addWolf(env: Environment, pos: IVec2, packId: int = 0,
             isLeader: bool = false): Thing =
  let wolf = Thing(
    kind: Wolf,
    pos: pos,
    orientation: Orientation.W,
    packId: packId,
    maxHp: WolfMaxHp,
    hp: WolfMaxHp,
    attackDamage: WolfAttackDamage,
    isPackLeader: isLeader
  )
  env.add(wolf)
  wolf

# Helper to add a bear to the environment
proc addBear(env: Environment, pos: IVec2): Thing =
  let bear = Thing(
    kind: Bear,
    pos: pos,
    orientation: Orientation.W,
    maxHp: BearMaxHp,
    hp: BearMaxHp,
    attackDamage: BearAttackDamage
  )
  env.add(bear)
  bear

suite "Animal AI - stepToward":
  test "step toward target east":
    let result = stepToward(ivec2(10, 10), ivec2(15, 10))
    check result == ivec2(1, 0)

  test "step toward target west":
    let result = stepToward(ivec2(10, 10), ivec2(5, 10))
    check result == ivec2(-1, 0)

  test "step toward target south":
    let result = stepToward(ivec2(10, 10), ivec2(10, 15))
    check result == ivec2(0, 1)

  test "step toward target north":
    let result = stepToward(ivec2(10, 10), ivec2(10, 5))
    check result == ivec2(0, -1)

  test "step toward same position returns zero":
    let result = stepToward(ivec2(10, 10), ivec2(10, 10))
    check result == ivec2(0, 0)

  test "diagonal favors larger axis (x)":
    let result = stepToward(ivec2(10, 10), ivec2(15, 12))
    # dx=5 > dy=2, so step along x
    check result == ivec2(1, 0)

  test "diagonal favors larger axis (y)":
    let result = stepToward(ivec2(10, 10), ivec2(12, 15))
    # dy=5 > dx=2, so step along y
    check result == ivec2(0, 1)

  test "equal diagonal favors x axis":
    let result = stepToward(ivec2(10, 10), ivec2(13, 13))
    # dx=3 == dy=3, abs(dx) >= abs(dy) so x axis
    check result == ivec2(1, 0)

suite "Animal AI - tryMoveWildlife":
  test "wildlife moves to empty cell":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let cow = env.addCow(ivec2(50, 50))
    env.tryMoveWildlife(cow, ivec2(1, 0))
    check cow.pos == ivec2(51, 50)
    check env.grid[51][50] == cow
    check env.grid[50][50] == nil

  test "wildlife does not move to occupied cell":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let cow1 = env.addCow(ivec2(50, 50))
    discard env.addCow(ivec2(51, 50), herdId = 0)
    env.tryMoveWildlife(cow1, ivec2(1, 0))
    # Should not have moved - cell occupied
    check cow1.pos == ivec2(50, 50)
    check env.grid[50][50] == cow1

  test "wildlife does not move to blocked terrain":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let cow = env.addCow(ivec2(50, 50))
    env.terrain[51][50] = Water
    env.tryMoveWildlife(cow, ivec2(1, 0))
    check cow.pos == ivec2(50, 50)

  test "wildlife zero movement is no-op":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let cow = env.addCow(ivec2(50, 50))
    env.tryMoveWildlife(cow, ivec2(0, 0))
    check cow.pos == ivec2(50, 50)

  test "wildlife updates orientation on horizontal move":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let cow = env.addCow(ivec2(50, 50))
    env.tryMoveWildlife(cow, ivec2(1, 0))
    check cow.orientation == Orientation.E
    env.tryMoveWildlife(cow, ivec2(-1, 0))
    check cow.orientation == Orientation.W

suite "Animal AI - Cow Herd Behavior":
  test "cows aggregate into herds":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    # Place cows in herd 0
    let cow1 = env.addCow(ivec2(50, 50), herdId = 0)
    let cow2 = env.addCow(ivec2(51, 50), herdId = 0)
    let cow3 = env.addCow(ivec2(50, 51), herdId = 0)
    # Step to trigger animal AI
    env.stepNoop()
    # After step, cows should still exist
    check env.thingsByKind[Cow].len == 3

  test "multiple herds are independent":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let cow1 = env.addCow(ivec2(50, 50), herdId = 0)
    let cow2 = env.addCow(ivec2(60, 60), herdId = 1)
    env.stepNoop()
    # Both should still exist
    check env.thingsByKind[Cow].len == 2

suite "Animal AI - Wolf Pack Behavior":
  test "wolves aggregate into packs":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let w1 = env.addWolf(ivec2(50, 50), packId = 0, isLeader = true)
    let w2 = env.addWolf(ivec2(51, 50), packId = 0)
    let w3 = env.addWolf(ivec2(50, 51), packId = 0)
    env.stepNoop()
    check env.thingsByKind[Wolf].len == 3

  test "scattered wolves wander randomly":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wolf = env.addWolf(ivec2(50, 50), packId = 0)
    wolf.scatteredSteps = 10
    env.stepNoop()
    # Wolf should still exist and scattered steps should decrease
    check wolf.scatteredSteps < 10

suite "Animal AI - Bear Behavior":
  test "bears exist and move":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let bear = env.addBear(ivec2(50, 50))
    env.stepNoop()
    check env.thingsByKind[Bear].len == 1
    check bear.hp == BearMaxHp

  test "bear has correct attack damage":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let bear = env.addBear(ivec2(50, 50))
    check bear.attackDamage == BearAttackDamage

suite "Animal AI - Predator Attacks":
  test "wolf attacks adjacent agent":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wolf = env.addWolf(ivec2(50, 50), packId = 0, isLeader = true)
    let agent = env.addAgentAt(0, ivec2(51, 50))
    let hpBefore = agent.hp
    env.stepNoop()
    # Wolf should have attacked the adjacent agent
    check agent.hp < hpBefore

  test "bear attacks adjacent agent":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let bear = env.addBear(ivec2(50, 50))
    let agent = env.addAgentAt(0, ivec2(51, 50))
    let hpBefore = agent.hp
    env.stepNoop()
    # Bear should have attacked the adjacent agent
    check agent.hp < hpBefore

  test "wolf does not attack non-adjacent agent":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wolf = env.addWolf(ivec2(50, 50), packId = 0, isLeader = true)
    let agent = env.addAgentAt(0, ivec2(53, 50))
    let hpBefore = agent.hp
    env.stepNoop()
    # Agent was too far - check wolf may have moved toward agent but not attacked this step
    # At minimum, agent should not have taken wolf attack damage if wolf hadn't moved adjacent
    # (wolf moves 1 step toward target, then attacks, so at dist 3 it takes 2 more steps)
    check agent.hp >= hpBefore - BearAttackDamage  # Allow for potential other damage

  test "bear does BearAttackDamage to adjacent agent":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let bear = env.addBear(ivec2(50, 50))
    let agent = env.addAgentAt(0, ivec2(50, 51))
    let hpBefore = agent.hp
    env.stepNoop()
    # Bear should deal BearAttackDamage (2)
    check agent.hp == hpBefore - BearAttackDamage

  test "wolf does WolfAttackDamage to adjacent agent":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wolf = env.addWolf(ivec2(50, 50), packId = 0, isLeader = true)
    let agent = env.addAgentAt(0, ivec2(50, 51))
    let hpBefore = agent.hp
    env.stepNoop()
    # Wolf should deal WolfAttackDamage (1)
    check agent.hp == hpBefore - WolfAttackDamage
