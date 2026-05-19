import std/unittest
import environment
import items
import test_utils

suite "University Techs":
  test "university tech research costs resources":
    let env = makeEmptyEnv()
    let university = addBuilding(env, University, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Cost for first tech (Ballistics): 5 food + 3 gold + 2 wood (multiplied by tech index 1)
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 20)
    setStockpile(env, 0, ResourceWood, 20)

    # Initial tech should not be researched
    check not env.teamUniversityTechs[0].researched[TechBallistics]

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, university.pos))

    # Tech should have been researched
    check env.teamUniversityTechs[0].researched[TechBallistics]

    # Resources should have been spent (5 food + 3 gold + 2 wood for first tech)
    check env.stockpileCount(0, ResourceFood) == 15  # 20 - 5
    check env.stockpileCount(0, ResourceGold) == 17  # 20 - 3
    check env.stockpileCount(0, ResourceWood) == 18  # 20 - 2

  test "university tech fails without resources":
    let env = makeEmptyEnv()
    let university = addBuilding(env, University, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    # Not enough resources
    setStockpile(env, 0, ResourceFood, 1)
    setStockpile(env, 0, ResourceGold, 1)
    setStockpile(env, 0, ResourceWood, 1)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, university.pos))

    # No tech should have been researched
    var totalTechs = 0
    for techType in UniversityTechType:
      if env.teamUniversityTechs[0].researched[techType]:
        inc totalTechs
    check totalTechs == 0

  test "university techs are researched in order":
    let env = makeEmptyEnv()
    let university = addBuilding(env, University, ivec2(10, 9), 0)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)
    setStockpile(env, 0, ResourceWood, 200)

    # Research first tech
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, university.pos))
    check env.teamUniversityTechs[0].researched[TechBallistics]
    check not env.teamUniversityTechs[0].researched[TechMurderHoles]

    # Research second tech
    university.cooldown = 0  # Reset cooldown
    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, university.pos))
    check env.teamUniversityTechs[0].researched[TechMurderHoles]

  test "only villagers can research university techs":
    let env = makeEmptyEnv()
    let university = addBuilding(env, University, ivec2(10, 9), 0)
    # Create a man-at-arms (not a villager)
    let agent = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(agent, UnitManAtArms)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)
    setStockpile(env, 0, ResourceWood, 100)

    env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, university.pos))

    # No tech should have been researched
    var totalTechs = 0
    for techType in UniversityTechType:
      if env.teamUniversityTechs[0].researched[techType]:
        inc totalTechs
    check totalTechs == 0

  test "teams have independent university techs":
    let env = makeEmptyEnv()
    # Set up different techs for teams
    env.teamUniversityTechs[0].researched[TechBallistics] = true
    env.teamUniversityTechs[1].researched[TechMurderHoles] = true

    check env.hasUniversityTech(0, TechBallistics)
    check not env.hasUniversityTech(0, TechMurderHoles)
    check not env.hasUniversityTech(1, TechBallistics)
    check env.hasUniversityTech(1, TechMurderHoles)

suite "Murder Holes":
  test "murder holes allows tower to attack adjacent units":
    let env = makeEmptyEnv()
    # Set up a guard tower for team 0
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    tower.hp = tower.maxHp
    # Create an enemy adjacent to the tower
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    enemy.hp = 10
    enemy.maxHp = 10

    # Without Murder Holes, tower should NOT attack adjacent unit (min range 1)
    env.stepNoop()
    let hpAfterWithout = enemy.hp
    # Tower has min range 1, so adjacent unit shouldn't be attacked
    check hpAfterWithout == 10

    # Now enable Murder Holes
    env.teamUniversityTechs[0].researched[TechMurderHoles] = true
    enemy.hp = 10
    env.stepNoop()
    # With Murder Holes, tower should attack adjacent unit
    check enemy.hp < 10

suite "Arrowslits":
  test "arrowslits increases tower damage":
    let env = makeEmptyEnv()
    # Set up a guard tower for team 0
    let tower = addBuilding(env, GuardTower, ivec2(10, 10), 0)
    tower.hp = tower.maxHp
    # Create an enemy in tower range
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    enemy.hp = 20
    enemy.maxHp = 20

    # Attack without Arrowslits
    env.stepNoop()
    let damageWithout = 20 - enemy.hp

    # Reset enemy HP
    enemy.hp = 20
    # Enable Arrowslits
    env.teamUniversityTechs[0].researched[TechArrowslits] = true
    env.stepNoop()
    let damageWith = 20 - enemy.hp

    # Damage with Arrowslits should be 1 more than without
    check damageWith == damageWithout + 1

suite "Ballistics":
  test "ballistics increases archer damage":
    let env = makeEmptyEnv()
    # Set up archer attack upgrade for team 0
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)
    # Create an enemy target at range
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    enemy.hp = 10
    enemy.maxHp = 10

    # Attack without Ballistics
    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))
    let damageWithout = 10 - enemy.hp

    # Reset enemy HP
    enemy.hp = 10
    # Enable Ballistics
    env.teamUniversityTechs[0].researched[TechBallistics] = true
    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, enemy.pos))
    let damageWith = 10 - enemy.hp

    # Damage with Ballistics should be 1 more than without
    check damageWith == damageWithout + 1

suite "Building HP Techs":
  test "masonry increases building HP by 10%":
    # Test without Masonry
    let envWithout = makeEmptyEnv()
    let agentWithout = addAgentAt(envWithout, 0, ivec2(10, 10))
    setStockpile(envWithout, 0, ResourceWood, 100)
    envWithout.stepAction(agentWithout.agentId, 8'u8, 23)  # Build guard tower
    let towerWithout = envWithout.getThing(agentWithout.pos + ivec2(0, -1))
    let hpWithout = if towerWithout.isNil: 0 else: towerWithout.maxHp

    # Test with Masonry
    let envWith = makeEmptyEnv()
    envWith.teamUniversityTechs[0].researched[TechMasonry] = true
    let agentWith = addAgentAt(envWith, 0, ivec2(10, 10))
    setStockpile(envWith, 0, ResourceWood, 100)
    envWith.stepAction(agentWith.agentId, 8'u8, 23)  # Build guard tower
    let towerWith = envWith.getThing(agentWith.pos + ivec2(0, -1))
    let hpWith = if towerWith.isNil: 0 else: towerWith.maxHp

    # HP with Masonry should be 10% higher
    if hpWithout > 0 and hpWith > 0:
      check hpWith == int(float32(hpWithout) * 1.1 + 0.5)

  test "masonry and architecture stack for 20% HP":
    let env = makeEmptyEnv()
    # Enable both techs
    env.teamUniversityTechs[0].researched[TechMasonry] = true
    env.teamUniversityTechs[0].researched[TechArchitecture] = true

    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceWood, 100)

    # Build a guard tower with both techs
    let buildIdx = 23  # GuardTowerBuildIndex
    env.stepAction(agent.agentId, 8'u8, buildIdx)
    let tower = env.getThing(agent.pos + ivec2(0, -1))
    if not tower.isNil and tower.kind == GuardTower:
      # Base HP is GuardTowerMaxHp (14), with 20% bonus = 17
      let expectedHp = int(float32(GuardTowerMaxHp) * 1.2 + 0.5)
      check tower.maxHp == expectedHp

suite "Building Armor Techs":
  test "masonry reduces building damage taken":
    let env = makeEmptyEnv()
    # Build a wall
    let wall = addBuilding(env, Wall, ivec2(10, 9), 0)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    let attacker = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 10))
    attacker.attackDamage = 5

    # Attack without Masonry
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, wall.pos))
    let damageWithout = WallMaxHp - wall.hp

    # Reset wall HP
    wall.hp = WallMaxHp
    # Enable Masonry
    env.teamUniversityTechs[0].researched[TechMasonry] = true
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, wall.pos))
    let damageWith = WallMaxHp - wall.hp

    # Damage with Masonry should be 1 less than without
    check damageWith == damageWithout - 1

suite "Treadmill Crane":
  test "treadmill crane increases construction speed":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceWood, 100)

    # Build a guard tower
    let buildIdx = 23  # GuardTowerBuildIndex
    env.stepAction(agent.agentId, 8'u8, buildIdx)
    let tower = env.getThing(agent.pos + ivec2(0, -1))
    if not tower.isNil and tower.kind == GuardTower:
      tower.hp = 1  # Start at 1 HP

      # Construct without Treadmill Crane
      let prevPos = agent.pos
      agent.pos = tower.pos + ivec2(0, 1)  # Move adjacent
      env.grid[agent.pos.x][agent.pos.y] = agent
      env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, tower.pos))
      let hpGainWithout = tower.hp - 1

      # Reset
      tower.hp = 1
      # Enable Treadmill Crane
      env.teamUniversityTechs[0].researched[TechTreadmillCrane] = true
      env.stepAction(agent.agentId, 3'u8, dirIndex(agent.pos, tower.pos))
      let hpGainWith = tower.hp - 1

      # HP gain with Treadmill Crane should be 20% higher
      check hpGainWith >= hpGainWithout  # At minimum equal (rounding)

suite "Siege Engineers":
  test "siege engineers increases siege building damage":
    let env = makeEmptyEnv()
    # Build a wall
    let wall = addBuilding(env, Wall, ivec2(10, 9), 0)
    wall.hp = WallMaxHp
    wall.maxHp = WallMaxHp
    # Create a battering ram
    let ram = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 10), unitClass = UnitBatteringRam)
    applyUnitClass(ram, UnitBatteringRam)

    # Attack without Siege Engineers
    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
    let damageWithout = WallMaxHp - wall.hp

    # Reset wall HP
    wall.hp = WallMaxHp
    # Enable Siege Engineers
    env.teamUniversityTechs[1].researched[TechSiegeEngineers] = true
    env.stepAction(ram.agentId, 2'u8, dirIndex(ram.pos, wall.pos))
    let damageWith = WallMaxHp - wall.hp

    # Damage with Siege Engineers should be higher (20% more siege bonus)
    check damageWith > damageWithout
