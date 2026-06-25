import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import spatial_index
import test_utils

suite "Building Combat - Tower Attack Basics":
  test "guard tower attacks enemy in range":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    # Place enemy agent within GuardTowerRange (4)
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(52, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    # Tower should have dealt damage
    check enemy.hp < hpBefore
    check enemy.hp == hpBefore - GuardTowerAttackDamage

  test "guard tower does not attack friendly units":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    # Place friendly agent within range
    let friendly = env.addAgentAt(0, ivec2(52, 50))
    # Also need an enemy team to avoid conquest victory
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(100, 100))
    let hpBefore = friendly.hp
    env.stepNoop()
    # Friendly should not be damaged
    check friendly.hp == hpBefore

  test "guard tower does not attack out of range":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    # Place enemy outside GuardTowerRange (4), at distance 5
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(55, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    check enemy.hp == hpBefore

  test "castle attacks enemy in range with higher damage":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let castle = env.addBuilding(Castle, ivec2(50, 50), 0)
    # Place enemy within CastleRange (6)
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(54, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    check enemy.hp < hpBefore
    check enemy.hp == hpBefore - CastleAttackDamage

  test "town center attacks enemy in range":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tc = env.addBuilding(TownCenter, ivec2(50, 50), 0)
    # Place enemy within TownCenterRange (6)
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(54, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    check enemy.hp < hpBefore
    check enemy.hp == hpBefore - TownCenterAttackDamage

suite "Building Combat - Dead Zone (Murder Holes)":
  test "tower cannot attack adjacent enemy without Murder Holes":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    # Place enemy at distance 1 (adjacent)
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(51, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    # Without Murder Holes, minRange=2 so adjacent (dist=1) is dead zone
    check enemy.hp == hpBefore

  test "tower attacks adjacent enemy with Murder Holes":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    # Research Murder Holes
    env.teamUniversityTechs[0].researched[TechMurderHoles] = true
    # Place enemy at distance 1 (adjacent)
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(51, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    # With Murder Holes, minRange=1 so adjacent should be hit
    check enemy.hp < hpBefore

  test "tower still attacks at range 2 without Murder Holes":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    # Place enemy at distance 2 (just outside dead zone)
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(52, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    check enemy.hp < hpBefore

suite "Building Combat - University Tech Bonuses":
  test "Arrowslits adds +1 damage to guard tower":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    env.teamUniversityTechs[0].researched[TechArrowslits] = true
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(52, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    # Arrowslits: base damage + 1
    check enemy.hp == hpBefore - (GuardTowerAttackDamage + 1)

  test "Arrowslits does not affect castle":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let castle = env.addBuilding(Castle, ivec2(50, 50), 0)
    env.teamUniversityTechs[0].researched[TechArrowslits] = true
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(52, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    # Arrowslits only affects GuardTower, not Castle
    check enemy.hp == hpBefore - CastleAttackDamage

  test "Heated Shot adds +2 damage vs water units":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    env.teamUniversityTechs[0].researched[TechHeatedShot] = true
    env.teamUniversityTechs[0].researched[TechMurderHoles] = true  # Ensure we can attack close
    # Place a water unit (boat) within range
    let boat = env.addAgentAt(MapAgentsPerTeam, ivec2(52, 50), unitClass = UnitBoat)
    let hpBefore = boat.hp
    env.stepNoop()
    # Heated Shot: base damage + 2 vs water units
    check boat.hp == hpBefore - (GuardTowerAttackDamage + 2)

  test "Heated Shot does not add damage vs land units":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    env.teamUniversityTechs[0].researched[TechHeatedShot] = true
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(52, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    # Heated Shot only affects water units
    check enemy.hp == hpBefore - GuardTowerAttackDamage

suite "Building Combat - Garrison Arrow Bonus":
  test "garrisoned units add extra arrows":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    # Create a friendly agent and garrison it
    let friendly = env.addAgentAt(0, ivec2(49, 50))
    discard env.garrisonUnitInBuilding(friendly, tower)
    check tower.garrisonedUnits.len == 1
    # Place enemy in range
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(52, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    # Tower base attack + 1 garrison arrow (GarrisonArrowBonus=1 per garrisoned unit)
    # Base attack hits for GuardTowerAttackDamage, garrison arrow hits for GuardTowerAttackDamage
    let expectedDamage = GuardTowerAttackDamage * 2  # base + 1 garrison arrow, each dealing base damage
    check enemy.hp == hpBefore - expectedDamage

  test "TC garrison adds extra arrows":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tc = env.addBuilding(TownCenter, ivec2(50, 50), 0)
    # Create and garrison a friendly agent
    let friendly = env.addAgentAt(0, ivec2(49, 50))
    discard env.garrisonUnitInBuilding(friendly, tc)
    check tc.garrisonedUnits.len == 1
    # Place enemy in range
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(54, 50))
    let hpBefore = enemy.hp
    env.stepNoop()
    # TC: base arrow + garrison arrows (1 + garrisonCount * GarrisonArrowBonus)
    # = 2 arrows total, each dealing TownCenterAttackDamage
    let expectedDamage = TownCenterAttackDamage * 2
    check enemy.hp == hpBefore - expectedDamage

suite "Building Combat - Garrison Mechanics":
  test "garrison capacity limits":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    check garrisonCapacity(GuardTower) == GuardTowerGarrisonCapacity
    check garrisonCapacity(Castle) == CastleGarrisonCapacity
    check garrisonCapacity(TownCenter) == TownCenterGarrisonCapacity
    check garrisonCapacity(House) == HouseGarrisonCapacity
    check garrisonCapacity(Barracks) == 0  # Non-garrisonable building

  test "cannot garrison enemy unit":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    let enemy = env.addAgentAt(MapAgentsPerTeam, ivec2(49, 50))
    let result = env.garrisonUnitInBuilding(enemy, tower)
    check result == false
    check tower.garrisonedUnits.len == 0

  test "cannot garrison in non-garrisonable building":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let barracks = env.addBuilding(Barracks, ivec2(50, 50), 0)
    let friendly = env.addAgentAt(0, ivec2(49, 50))
    let result = env.garrisonUnitInBuilding(friendly, barracks)
    check result == false

  test "garrison removes unit from grid":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    let friendly = env.addAgentAt(0, ivec2(49, 50))
    check env.grid[49][50] == friendly
    discard env.garrisonUnitInBuilding(friendly, tower)
    # Unit should be removed from grid
    check env.grid[49][50] == nil
    check friendly.pos == ivec2(-1, -1)
    check friendly.isGarrisoned == true

  test "ungarrison places units around building":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    let friendly = env.addAgentAt(0, ivec2(49, 50))
    discard env.garrisonUnitInBuilding(friendly, tower)
    check tower.garrisonedUnits.len == 1
    let ungarrisoned = env.ungarrisonAllUnits(tower)
    check ungarrisoned.len == 1
    check tower.garrisonedUnits.len == 0
    check ungarrisoned[0].isGarrisoned == false
    check ungarrisoned[0].pos != ivec2(-1, -1)  # Placed somewhere valid

  test "garrison capacity is enforced":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    # Garrison up to capacity
    var garrisoned = 0
    for i in 0 ..< GuardTowerGarrisonCapacity + 2:
      let agent = env.addAgentAt(i, ivec2(48, (48 + i).int32))
      if env.garrisonUnitInBuilding(agent, tower):
        inc garrisoned
    check garrisoned == GuardTowerGarrisonCapacity
    check tower.garrisonedUnits.len == GuardTowerGarrisonCapacity
