import std/unittest
import environment
import items
import test_utils
import constants

suite "Garrison Overflow Edge Cases":
  test "unit cannot garrison via USE action when TownCenter is at capacity":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    # Fill to capacity
    for i in 0 ..< TownCenterGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + (i mod 10).int32, 5 + (i div 10).int32))
      check env.garrisonUnitInBuilding(unit, tc) == true

    check tc.garrisonedUnits.len == TownCenterGarrisonCapacity

    # Try to enter via USE action - should fail silently
    let overflow = addAgentAt(env, TownCenterGarrisonCapacity, ivec2(10, 11))
    env.stepAction(overflow.agentId, 3'u8, dirIndex(overflow.pos, tc.pos))

    # Unit should still be outside, not garrisoned
    check tc.garrisonedUnits.len == TownCenterGarrisonCapacity
    check overflow.pos != ivec2(-1, -1)  # Not garrisoned

  test "unit cannot garrison via USE action when Castle is at capacity":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 10), 0)
    for i in 0 ..< CastleGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + (i mod 10).int32, 5 + (i div 10).int32),
                            unitClass = UnitManAtArms)
      check env.garrisonUnitInBuilding(unit, castle) == true

    check castle.garrisonedUnits.len == CastleGarrisonCapacity

    let overflow = addAgentAt(env, CastleGarrisonCapacity, ivec2(10, 11),
                              unitClass = UnitManAtArms)
    env.stepAction(overflow.agentId, 3'u8, dirIndex(overflow.pos, castle.pos))

    check castle.garrisonedUnits.len == CastleGarrisonCapacity
    check overflow.pos != ivec2(-1, -1)

  test "unit cannot garrison via USE action when GuardTower is at capacity":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    for i in 0 ..< GuardTowerGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      check env.garrisonUnitInBuilding(unit, tower) == true

    check tower.garrisonedUnits.len == GuardTowerGarrisonCapacity

    let overflow = addAgentAt(env, GuardTowerGarrisonCapacity, ivec2(10, 11))
    env.stepAction(overflow.agentId, 3'u8, dirIndex(overflow.pos, tower.pos))

    check tower.garrisonedUnits.len == GuardTowerGarrisonCapacity
    check overflow.pos != ivec2(-1, -1)

  test "unit cannot garrison via USE action when House is at capacity":
    let env = makeEmptyEnv()
    let house = addBuilding(env, House, ivec2(10, 10), 0)
    for i in 0 ..< HouseGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      check env.garrisonUnitInBuilding(unit, house) == true

    check house.garrisonedUnits.len == HouseGarrisonCapacity

    let overflow = addAgentAt(env, HouseGarrisonCapacity, ivec2(10, 11))
    env.stepAction(overflow.agentId, 3'u8, dirIndex(overflow.pos, house.pos))

    check house.garrisonedUnits.len == HouseGarrisonCapacity
    check overflow.pos != ivec2(-1, -1)

  test "multiple units try to enter full garrison simultaneously":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    # Fill to capacity
    for i in 0 ..< TownCenterGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + (i mod 10).int32, 5 + (i div 10).int32))
      discard env.garrisonUnitInBuilding(unit, tc)

    # Create multiple units trying to enter
    let baseIdx = TownCenterGarrisonCapacity
    let unit1 = addAgentAt(env, baseIdx, ivec2(10, 11))
    let unit2 = addAgentAt(env, baseIdx + 1, ivec2(11, 10))
    let unit3 = addAgentAt(env, baseIdx + 2, ivec2(9, 10))

    # All should fail
    check env.garrisonUnitInBuilding(unit1, tc) == false
    check env.garrisonUnitInBuilding(unit2, tc) == false
    check env.garrisonUnitInBuilding(unit3, tc) == false
    check tc.garrisonedUnits.len == TownCenterGarrisonCapacity

suite "Garrison/Ungarrison Rapid Cycling":
  test "rapid garrison and ungarrison cycles preserve unit count":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let triggerer = addAgentAt(env, 0, ivec2(9, 10))
    var units: seq[Thing] = @[]
    for i in 1 ..< 6:
      let unit = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      units.add(unit)

    for cycle in 0 ..< 5:
      # Garrison all units
      for unit in units:
        if unit.pos != ivec2(-1, -1):  # Not already garrisoned
          discard env.garrisonUnitInBuilding(unit, tc)

      check tc.garrisonedUnits.len == 5

      # Ungarrison via command
      env.stepAction(triggerer.agentId, 3'u8, 9)

      check tc.garrisonedUnits.len == 0

      # Verify all units are alive and on the grid
      for unit in units:
        check unit.hp > 0
        check isValidPos(unit.pos)

  test "rapid cycling does not duplicate units":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let triggerer = addAgentAt(env, 0, ivec2(9, 10))
    let unit = addAgentAt(env, 1, ivec2(10, 11))

    for _ in 0 ..< 10:
      discard env.garrisonUnitInBuilding(unit, tc)
      check tc.garrisonedUnits.len == 1
      env.stepAction(triggerer.agentId, 3'u8, 9)
      check tc.garrisonedUnits.len == 0

    # Unit should still exist exactly once
    check unit.hp > 0
    check isValidPos(unit.pos)

  test "garrison during ungarrison step":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let unit1 = addAgentAt(env, 0, ivec2(10, 11))
    let unit2 = addAgentAt(env, 1, ivec2(11, 10))

    # Garrison first unit
    discard env.garrisonUnitInBuilding(unit1, tc)
    check tc.garrisonedUnits.len == 1

    # Ungarrison
    let ejected = env.ungarrisonAllUnits(tc)
    check ejected.len == 1
    check tc.garrisonedUnits.len == 0

    # Immediately garrison second unit
    discard env.garrisonUnitInBuilding(unit2, tc)
    check tc.garrisonedUnits.len == 1
    check tc.garrisonedUnits[0] == unit2

  test "cycling with different unit types":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 10), 0)
    let triggerer = addAgentAt(env, 0, ivec2(9, 10))

    # Create mixed unit types
    let villager = addAgentAt(env, 1, ivec2(10, 11), unitClass = UnitVillager)
    let knight = addAgentAt(env, 2, ivec2(11, 10), unitClass = UnitManAtArms)
    let archer = addAgentAt(env, 3, ivec2(12, 10), unitClass = UnitArcher)

    for _ in 0 ..< 3:
      discard env.garrisonUnitInBuilding(villager, castle)
      discard env.garrisonUnitInBuilding(knight, castle)
      discard env.garrisonUnitInBuilding(archer, castle)
      check castle.garrisonedUnits.len == 3

      env.stepAction(triggerer.agentId, 3'u8, 9)
      check castle.garrisonedUnits.len == 0

    # All units should retain their class
    check villager.unitClass == UnitVillager
    check knight.unitClass == UnitManAtArms
    check archer.unitClass == UnitArcher

suite "Garrison Capacity Boundary Cases":
  test "exactly at capacity minus one allows one more":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    # Fill to capacity - 1
    for i in 0 ..< GuardTowerGarrisonCapacity - 1:
      let unit = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      check env.garrisonUnitInBuilding(unit, tower) == true

    check tower.garrisonedUnits.len == GuardTowerGarrisonCapacity - 1

    # One more should succeed
    let lastUnit = addAgentAt(env, GuardTowerGarrisonCapacity - 1, ivec2(15, 11))
    check env.garrisonUnitInBuilding(lastUnit, tower) == true
    check tower.garrisonedUnits.len == GuardTowerGarrisonCapacity

  test "ungarrison one then regarrison to capacity":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    var units: seq[Thing] = @[]
    for i in 0 ..< TownCenterGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + (i mod 10).int32, 5 + (i div 10).int32))
      discard env.garrisonUnitInBuilding(unit, tc)
      units.add(unit)

    check tc.garrisonedUnits.len == TownCenterGarrisonCapacity

    # Ungarrison all
    let ejected = env.ungarrisonAllUnits(tc)
    check ejected.len == TownCenterGarrisonCapacity
    check tc.garrisonedUnits.len == 0

    # Regarrison all - should all succeed
    for unit in units:
      check env.garrisonUnitInBuilding(unit, tc) == true
    check tc.garrisonedUnits.len == TownCenterGarrisonCapacity

  test "capacity check is per-building not global":
    let env = makeEmptyEnv()
    let tower1 = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let tower2 = addBuilding(env, GuardTower, ivec2(20, 10), 0)

    # Fill first tower
    for i in 0 ..< GuardTowerGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(10 + i.int32, 11))
      check env.garrisonUnitInBuilding(unit, tower1) == true

    check tower1.garrisonedUnits.len == GuardTowerGarrisonCapacity

    # Second tower should still accept units
    for i in 0 ..< GuardTowerGarrisonCapacity:
      let unit = addAgentAt(env, GuardTowerGarrisonCapacity + i, ivec2(20 + i.int32, 11))
      check env.garrisonUnitInBuilding(unit, tower2) == true

    check tower2.garrisonedUnits.len == GuardTowerGarrisonCapacity

suite "Garrison Exit When Surrounded":
  test "units stay garrisoned when no exit tiles available":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)

    # Garrison a unit
    let unit = addAgentAt(env, 0, ivec2(11, 11))
    discard env.garrisonUnitInBuilding(unit, tc)
    check tc.garrisonedUnits.len == 1

    # Surround the TC with walls (blocking all exit tiles)
    for dy in -2 .. 2:
      for dx in -2 .. 2:
        if dx == 0 and dy == 0:
          continue
        let pos = tc.pos + ivec2(dx.int32, dy.int32)
        if isValidPos(pos) and env.grid[pos.x][pos.y].isNil:
          discard addBuilding(env, Wall, pos, 0)

    # Try to ungarrison
    let ejected = env.ungarrisonAllUnits(tc)
    check ejected.len == 0  # No room to eject
    check tc.garrisonedUnits.len == 1  # Unit stays inside

  test "partial ungarrison when some tiles are blocked":
    let env = makeEmptyEnv()
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)

    # Garrison 5 units
    for i in 0 ..< GuardTowerGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + i.int32, 5))
      discard env.garrisonUnitInBuilding(unit, tower)

    check tower.garrisonedUnits.len == 5

    # Block most exit tiles, leaving only 2 free
    for dy in -2 .. 2:
      for dx in -2 .. 2:
        if dx == 0 and dy == 0:
          continue
        let pos = tower.pos + ivec2(dx.int32, dy.int32)
        if isValidPos(pos) and env.grid[pos.x][pos.y].isNil:
          # Leave positions (8,10) and (12,10) free
          if pos != ivec2(8, 10) and pos != ivec2(12, 10):
            discard addBuilding(env, Wall, pos, 0)

    # Ungarrison
    let ejected = env.ungarrisonAllUnits(tower)
    check ejected.len == 2  # Only 2 tiles available
    check tower.garrisonedUnits.len == 3  # 3 remain inside

suite "Garrison State Consistency":
  test "garrisoned unit HP does not affect capacity":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)

    # Garrison units with varying HP
    for i in 0 ..< TownCenterGarrisonCapacity:
      let unit = addAgentAt(env, i, ivec2(5 + (i mod 10).int32, 5 + (i div 10).int32))
      unit.hp = (i + 1)  # HP from 1 to 15
      check env.garrisonUnitInBuilding(unit, tc) == true

    check tc.garrisonedUnits.len == TownCenterGarrisonCapacity

  test "unit with zero HP can still garrison if on grid":
    # Note: isAgentAlive checks grid presence, not HP
    # A unit with hp=0 that's still on the grid is considered alive
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let unit = addAgentAt(env, 0, ivec2(10, 11))
    unit.hp = 0

    # Unit with 0 HP but still on grid CAN garrison
    check env.garrisonUnitInBuilding(unit, tc) == true
    check tc.garrisonedUnits.len == 1

  test "off-grid unit cannot garrison":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let unit = addAgentAt(env, 0, ivec2(10, 11))
    # Remove unit from grid (simulating death or already garrisoned)
    env.grid[unit.pos.x][unit.pos.y] = nil
    unit.pos = ivec2(-1, -1)

    check env.garrisonUnitInBuilding(unit, tc) == false
    check tc.garrisonedUnits.len == 0

  test "garrisoned units retain inventory through cycles":
    let env = makeEmptyEnv()
    let tc = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let triggerer = addAgentAt(env, 0, ivec2(9, 10))
    let carrier = addAgentAt(env, 1, ivec2(10, 11))
    setInv(carrier, ItemWood, 10)
    setInv(carrier, ItemGold, 5)
    setInv(carrier, ItemStone, 3)

    for _ in 0 ..< 5:
      discard env.garrisonUnitInBuilding(carrier, tc)
      check getInv(carrier, ItemWood) == 10
      check getInv(carrier, ItemGold) == 5
      check getInv(carrier, ItemStone) == 3

      env.stepAction(triggerer.agentId, 3'u8, 9)
      check getInv(carrier, ItemWood) == 10
      check getInv(carrier, ItemGold) == 5
      check getInv(carrier, ItemStone) == 3
