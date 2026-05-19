import std/[unittest]
import environment
import agent_control
import common
import types
import items
import terrain
import test_utils

suite "Structure Damage - Basic":
  test "structure takes damage":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 0)
    let hpBefore = wall.hp
    check hpBefore > 0
    discard env.applyStructureDamage(wall, 5)
    check wall.hp == hpBefore - 5

  test "structure damage cannot go below 0":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 0)
    discard env.applyStructureDamage(wall, wall.hp + 100)
    check wall.hp == 0

  test "minimum damage is 1":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 0)
    let hpBefore = wall.hp
    discard env.applyStructureDamage(wall, 0)
    # min(1, amount) ensures at least 1 damage
    check wall.hp == hpBefore - 1

  test "structure destruction returns true":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 0)
    let destroyed = env.applyStructureDamage(wall, wall.hp + 1)
    check destroyed == true
    check wall.hp == 0

  test "structure survival returns false":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 0)
    let destroyed = env.applyStructureDamage(wall, 1)
    check destroyed == false
    check wall.hp > 0

suite "Structure Damage - Siege Multiplier":
  test "siege units deal multiplied damage to structures":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 1)
    let ram = env.addAgentAt(0, ivec2(49, 50), unitClass = UnitBatteringRam)
    let hpBefore = wall.hp
    discard env.applyStructureDamage(wall, 2, ram)
    # Siege damage: 2 * SiegeStructureMultiplier (3) = 6
    check wall.hp == hpBefore - (2 * SiegeStructureMultiplier)

  test "non-siege units deal normal damage":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 1)
    let soldier = env.addAgentAt(0, ivec2(49, 50), unitClass = UnitManAtArms)
    let hpBefore = wall.hp
    discard env.applyStructureDamage(wall, 2, soldier)
    check wall.hp == hpBefore - 2

suite "Structure Damage - University Tech Armor":
  test "Masonry reduces structure damage by 1":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 0)
    env.teamUniversityTechs[0].researched[TechMasonry] = true
    let hpBefore = wall.hp
    discard env.applyStructureDamage(wall, 5)
    # Masonry: -1 armor, so 5 - 1 = 4 damage
    check wall.hp == hpBefore - 4

  test "Architecture stacks with Masonry for -2 armor":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 0)
    env.teamUniversityTechs[0].researched[TechMasonry] = true
    env.teamUniversityTechs[0].researched[TechArchitecture] = true
    let hpBefore = wall.hp
    discard env.applyStructureDamage(wall, 5)
    # Masonry + Architecture: -2 armor, so 5 - 2 = 3 damage
    check wall.hp == hpBefore - 3

  test "armor cannot reduce damage below 1":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 0)
    env.teamUniversityTechs[0].researched[TechMasonry] = true
    env.teamUniversityTechs[0].researched[TechArchitecture] = true
    let hpBefore = wall.hp
    # 2 damage - 2 armor = 0, but min is 1
    discard env.applyStructureDamage(wall, 2)
    check wall.hp == hpBefore - 1

suite "Structure Damage - Siege Engineers":
  test "Siege Engineers adds 20% to siege damage":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let castle = env.addBuilding(Castle, ivec2(50, 50), 1)
    let ram = env.addAgentAt(0, ivec2(49, 50), unitClass = UnitBatteringRam)
    env.teamUniversityTechs[0].researched[TechSiegeEngineers] = true
    let hpBefore = castle.hp
    discard env.applyStructureDamage(castle, 2, ram)
    # Siege: 2 * 3 = 6, then +20% = (6*6+2)/5 = 7 (with rounding)
    let siegeDmg = 2 * SiegeStructureMultiplier
    let engineersDmg = (siegeDmg * 6 + 2) div 5  # +20% with rounding
    check castle.hp == hpBefore - engineersDmg

  test "Siege Engineers does not affect non-siege units":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let wall = env.addBuilding(Wall, ivec2(50, 50), 1)
    let soldier = env.addAgentAt(0, ivec2(49, 50), unitClass = UnitManAtArms)
    env.teamUniversityTechs[0].researched[TechSiegeEngineers] = true
    let hpBefore = wall.hp
    discard env.applyStructureDamage(wall, 5, soldier)
    # Non-siege: no multiplier, no Siege Engineers bonus
    check wall.hp == hpBefore - 5

suite "Structure Damage - Garrison Eject on Destruction":
  test "garrisoned units are ejected when building destroyed":
    var env = makeEmptyEnv()
    env.config.victoryCondition = VictoryNone
    let tower = env.addBuilding(GuardTower, ivec2(50, 50), 0)
    let friendly = env.addAgentAt(0, ivec2(49, 50))
    discard env.garrisonUnitInBuilding(friendly, tower)
    check friendly.isGarrisoned == true
    check friendly.pos == ivec2(-1, -1)
    # Destroy the tower
    discard env.applyStructureDamage(tower, tower.hp + 1)
    check tower.hp == 0
    # Garrisoned unit should be ejected
    check friendly.isGarrisoned == false
    # Unit should either be placed on grid or terminated (if no space)
    check (friendly.pos != ivec2(-1, -1) or env.terminated[0] == 1.0)
