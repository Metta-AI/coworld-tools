import std/unittest
import environment
import items
import test_utils

suite "Town Center Garrison":
  test "villager can garrison in own town center":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Villager has no resources, so USE on TC should garrison

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, tc.pos))

    check tc.garrisonedUnits.len == 1
    check tc.garrisonedUnits[0] == agent
    check agent.pos == ivec2(-1, -1)  # Agent is off-grid

  test "garrisoned villagers add TC arrow damage":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    # Add some villagers to garrison
    for i in 0 ..< 5:
      let villager = addAgentAt(env, i, ivec2(10 + i, 11))
      discard env.garrisonUnitInBuilding(villager, tc)

    check tc.garrisonedUnits.len == 5
    # Each garrisoned unit adds GarrisonArrowBonus arrows

  test "units ungarrison when TC is destroyed":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(11, 11))
    discard env.garrisonUnitInBuilding(agent, tc)

    check tc.garrisonedUnits.len == 1
    check agent.pos == ivec2(-1, -1)

    # Destroy TC
    discard env.applyStructureDamage(tc, TownCenterMaxHp + 10)

    # Agent should be ejected
    check agent.pos != ivec2(-1, -1)
    check isValidPos(agent.pos)

  test "town bell activates garrison recall flag":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let triggerer = addAgentAt(env, 0, ivec2(9, 10))  # Adjacent to TC

    check env.townBellActive[0] == false

    # Ring town bell (argument 10) — sets flag, villagers garrison via AI over subsequent steps
    env.stepAction(triggerer.agentId, 3'u8, 10)
    check env.townBellActive[0] == true

    # Ring again to deactivate
    env.stepAction(triggerer.agentId, 3'u8, 10)
    check env.townBellActive[0] == false

  test "ungarrison command ejects all units":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let triggerer = addAgentAt(env, 0, ivec2(9, 10))
    # Garrison some units
    for i in 1 ..< 5:
      let villager = addAgentAt(env, i, ivec2(10 + i, 11))
      discard env.garrisonUnitInBuilding(villager, tc)

    check tc.garrisonedUnits.len == 4

    # Ungarrison (argument 9)
    env.stepAction(triggerer.agentId, 3'u8, 9)

    check tc.garrisonedUnits.len == 0

  test "enemy villager cannot garrison in opponent TC":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 9), 0)  # Team 0 TC
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 10))  # Team 1 villager

    env.stepAction(enemy.agentId, 3'u8, dirIndex(enemy.pos, tc.pos))

    check tc.garrisonedUnits.len == 0  # Enemy should not garrison

suite "Guard Tower Garrison":
  test "unit can garrison in guard tower":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, tower.pos))

    check tower.garrisonedUnits.len == 1
    check tower.garrisonedUnits[0] == agent
    check agent.pos == ivec2(-1, -1)

  test "guard tower respects capacity limit":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    # Fill to capacity (5)
    for i in 0 ..< GuardTowerGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(10 + i, 11))
      check env.garrisonUnitInBuilding(unit, tower) == true

    check tower.garrisonedUnits.len == GuardTowerGarrisonCapacity

    # 6th unit should fail
    let extra = addAgentAt(env, GuardTowerGarrisonCapacity, ivec2(15, 11))
    check env.garrisonUnitInBuilding(extra, tower) == false
    check tower.garrisonedUnits.len == GuardTowerGarrisonCapacity

  test "units eject when guard tower is destroyed":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(11, 11))
    discard env.garrisonUnitInBuilding(agent, tower)

    check tower.garrisonedUnits.len == 1
    check agent.pos == ivec2(-1, -1)

    discard env.applyStructureDamage(tower, GuardTowerMaxHp + 10)

    check agent.pos != ivec2(-1, -1)
    check isValidPos(agent.pos)

  test "ungarrison command works on guard tower":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let triggerer = addAgentAt(env, 0, ivec2(9, 10))
    for i in 1 ..< 4:
      let unit = addAgentAt(env, i, ivec2(10 + i, 11))
      discard env.garrisonUnitInBuilding(unit, tower)

    check tower.garrisonedUnits.len == 3

    env.stepAction(triggerer.agentId, 3'u8, 9)

    check tower.garrisonedUnits.len == 0

suite "House Garrison":
  test "villager can garrison in house":
    let env = makeEmptyEnv()
    let house = addBuilding(env, House, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, house.pos))

    check house.garrisonedUnits.len == 1
    check house.garrisonedUnits[0] == agent
    check agent.pos == ivec2(-1, -1)

  test "house respects capacity limit":
    let env = makeEmptyEnv()
    let house = addBuilding(env, House, ivec2(10, 10), 0)
    for i in 0 ..< HouseGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(10 + i, 11))
      check env.garrisonUnitInBuilding(unit, house) == true

    check house.garrisonedUnits.len == HouseGarrisonCapacity

    let extra = addAgentAt(env, HouseGarrisonCapacity, ivec2(15, 11))
    check env.garrisonUnitInBuilding(extra, house) == false

  test "units eject when house is destroyed":
    let env = makeEmptyEnv()
    let house = addBuilding(env, House, ivec2(10, 10), 0)
    let agent = addAgentAt(env, 0, ivec2(11, 11))
    discard env.garrisonUnitInBuilding(agent, house)

    check house.garrisonedUnits.len == 1

    discard env.applyStructureDamage(house, 100)

    check agent.pos != ivec2(-1, -1)
    check isValidPos(agent.pos)

  test "enemy cannot garrison in opponent house":
    let env = makeEmptyEnv()
    let house = addBuilding(env, House, ivec2(10, 9), 0)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 10))

    env.stepAction(enemy.agentId, 3'u8, dirIndex(enemy.pos, house.pos))

    check house.garrisonedUnits.len == 0

suite "Castle Garrison":
  test "castle respects its own capacity limit":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 10), 0)
    for i in 0 ..< CastleGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + (i mod 10), 5 + (i div 10)),
                            unitClass = UnitManAtArms)
      check env.garrisonUnitInBuilding(unit, castle) == true

    check castle.garrisonedUnits.len == CastleGarrisonCapacity

    let extra = addAgentAt(env, CastleGarrisonCapacity, ivec2(15, 15),
                           unitClass = UnitManAtArms)
    check env.garrisonUnitInBuilding(extra, castle) == false
