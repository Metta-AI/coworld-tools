import std/[unittest]
import test_common

suite "Behavior: Agent Death Cleanup":
  test "killed agent position set to invalid":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check victim.pos == ivec2(-1, -1)

  test "killed agent HP set to zero":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 5

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check victim.hp == 0

  test "killed agent inventory cleared":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemWood, 5)
    setInv(victim, ItemGold, 3)
    setInv(victim, ItemStone, 2)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    # Victim inventory should be emptied (items transferred to corpse)
    check getInv(victim, ItemWood) == 0
    check getInv(victim, ItemGold) == 0
    check getInv(victim, ItemStone) == 0

  test "killed agent grid cell cleared":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check env.grid[victimPos.x][victimPos.y] == nil

  test "killed agent terminated flag set":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1

    check env.terminated[victim.agentId] == 0.0

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check env.terminated[victim.agentId] == 1.0

  test "enforceZeroHpDeaths kills drained agents":
    let env = makeEmptyEnv()
    let victim = addAgentAt(env, 0, ivec2(10, 10))
    victim.hp = 0
    # Agent is at 0 HP but not yet terminated
    check env.terminated[victim.agentId] == 0.0

    # A noop step triggers enforceZeroHpDeaths
    env.stepNoop()

    check env.terminated[victim.agentId] == 1.0
    check victim.pos == ivec2(-1, -1)

suite "Behavior: Corpse Creation Timing":
  test "corpse created at death position with inventory":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemWood, 4)
    setInv(victim, ItemGold, 2)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    let corpse = env.getBackgroundThing(victimPos)
    check corpse != nil
    check corpse.kind == Corpse
    check corpse.pos == victimPos
    check getInv(corpse, ItemWood) == 4
    check getInv(corpse, ItemGold) == 2

  test "skeleton created when victim has no inventory":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    # No inventory items

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    let remains = env.getBackgroundThing(victimPos)
    check remains != nil
    check remains.kind == Skeleton

  test "corpse created same step as death":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemWood, 1)

    let corpsesBefore = env.thingsByKind[Corpse].len

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check env.thingsByKind[Corpse].len == corpsesBefore + 1

  test "corpse appears in thingsByKind after death":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemGold, 1)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    var found = false
    for thing in env.thingsByKind[Corpse]:
      if thing.pos == victimPos:
        found = true
        break
    check found

suite "Behavior: Corpse Removal and Conversion":
  test "corpse removed after full loot via USE action":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemWood, 1)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    # Verify corpse exists
    let corpse = env.getBackgroundThing(victimPos)
    check corpse != nil
    check corpse.kind == Corpse

    # Harvest the single item using USE verb (3)
    env.stepAction(attacker.agentId, 3'u8, dirIndex(attacker.pos, victimPos))

    # Corpse should be gone, replaced by skeleton (non-meat loot)
    let remains = env.getBackgroundThing(victimPos)
    if remains != nil:
      check remains.kind == Skeleton

  test "corpse persists with remaining inventory after partial loot":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemWood, 3)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    # Verify corpse has 3 wood
    let corpseBefore = env.getBackgroundThing(victimPos)
    check corpseBefore != nil
    check getInv(corpseBefore, ItemWood) == 3

    # Harvest one item using USE verb (3)
    env.stepAction(attacker.agentId, 3'u8, dirIndex(attacker.pos, victimPos))

    # Corpse should still exist with remaining items
    let corpse = env.getBackgroundThing(victimPos)
    check corpse != nil
    check corpse.kind == Corpse
    check getInv(corpse, ItemWood) == 2

  test "corpse converted to skeleton after non-meat depletion":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemGold, 1)

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    # Harvest the gold using USE verb (3)
    env.stepAction(attacker.agentId, 3'u8, dirIndex(attacker.pos, victimPos))

    let remains = env.getBackgroundThing(victimPos)
    if remains != nil:
      check remains.kind == Skeleton

  test "multiple deaths create multiple corpses":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victim1Pos = ivec2(10, 9)
    let victim1 = addAgentAt(env, MapAgentsPerTeam, victim1Pos)
    victim1.hp = 1
    setInv(victim1, ItemWood, 1)
    let victim2Pos = ivec2(10, 11)
    let victim2 = addAgentAt(env, MapAgentsPerTeam + 1, victim2Pos)
    victim2.hp = 1
    setInv(victim2, ItemGold, 1)

    let corpsesBefore = env.thingsByKind[Corpse].len

    # Kill first victim (north)
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victim1Pos))
    check env.thingsByKind[Corpse].len == corpsesBefore + 1

    # Kill second victim (south)
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victim2Pos))
    check env.thingsByKind[Corpse].len == corpsesBefore + 2

suite "Behavior: Death Item Drops":
  test "lanterns drop on adjacent tiles on death":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    victim.inventoryLantern = 2

    let lanternsBefore = env.thingsByKind[Lantern].len

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check env.thingsByKind[Lantern].len == lanternsBefore + 2
    # Lanterns should not be at the death position (corpse/skeleton is there)
    for i in lanternsBefore ..< env.thingsByKind[Lantern].len:
      check env.thingsByKind[Lantern][i].pos != victimPos

  test "relics drop on adjacent tiles on death":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    victim.inventoryRelic = 1

    let relicsBefore = env.thingsByKind[Relic].len

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check env.thingsByKind[Relic].len == relicsBefore + 1
    # Relic should be on adjacent tile
    let relic = env.thingsByKind[Relic][relicsBefore]
    check relic.pos != victimPos

  test "lantern and relic cleared from dead agent inventory":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    victim.inventoryLantern = 1
    victim.inventoryRelic = 1

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check victim.inventoryLantern == 0
    check victim.inventoryRelic == 0

  test "death with both regular and special items drops all":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1
    setInv(victim, ItemWood, 3)
    victim.inventoryLantern = 1
    victim.inventoryRelic = 1

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    # Corpse should have the regular inventory
    let corpse = env.getBackgroundThing(victimPos)
    check corpse != nil
    check corpse.kind == Corpse
    # Lantern and relic should be on adjacent tiles
    check env.thingsByKind[Lantern].len >= 1
    check env.thingsByKind[Relic].len >= 1

suite "Behavior: Corpse and Skeleton Tracking":
  test "multiple corpses tracked in thingsByKind":
    let env = makeEmptyEnv()
    # Use separate attackers adjacent to each victim
    let victim1Pos = ivec2(10, 9)
    let victim2Pos = ivec2(15, 9)
    let victim3Pos = ivec2(20, 9)
    let attacker1 = addAgentAt(env, 0, ivec2(10, 10))
    attacker1.attackDamage = 100
    let attacker2 = addAgentAt(env, 1, ivec2(15, 10))
    attacker2.attackDamage = 100
    let attacker3 = addAgentAt(env, 2, ivec2(20, 10))
    attacker3.attackDamage = 100
    let victim1 = addAgentAt(env, MapAgentsPerTeam, victim1Pos)
    victim1.hp = 1
    setInv(victim1, ItemWood, 1)
    let victim2 = addAgentAt(env, MapAgentsPerTeam + 1, victim2Pos)
    victim2.hp = 1
    setInv(victim2, ItemGold, 1)
    let victim3 = addAgentAt(env, MapAgentsPerTeam + 2, victim3Pos)
    victim3.hp = 1
    setInv(victim3, ItemStone, 1)

    let corpsesBefore = env.thingsByKind[Corpse].len

    # Kill all three in one step
    env.stepAction(attacker1.agentId, 2'u8, dirIndex(attacker1.pos, victim1Pos))
    env.stepAction(attacker2.agentId, 2'u8, dirIndex(attacker2.pos, victim2Pos))
    env.stepAction(attacker3.agentId, 2'u8, dirIndex(attacker3.pos, victim3Pos))

    check env.thingsByKind[Corpse].len == corpsesBefore + 3

  test "skeleton tracked in thingsByKind after no-inventory death":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 100
    let victimPos = ivec2(10, 9)
    let victim = addAgentAt(env, MapAgentsPerTeam, victimPos)
    victim.hp = 1

    let skeletonsBefore = env.thingsByKind[Skeleton].len

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victimPos))

    check env.thingsByKind[Skeleton].len == skeletonsBefore + 1
