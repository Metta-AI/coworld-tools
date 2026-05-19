import std/unittest
import environment
import types
import items
import constants
import common_types
import test_utils

suite "Repair - Basic Repair":
  test "villager repairs damaged building":
    let env = makeEmptyEnv()
    # Place a House at (5,5) owned by team 0, fully constructed but damaged
    let house = env.addBuilding(House, ivec2(5, 5), 0)
    house.maxHp = 100
    house.hp = 50
    house.constructed = true

    # Place villager adjacent to house at (5,4) facing south (toward 5,5)
    let agent = env.addAgentAt(0, ivec2(5, 4), unitClass = UnitVillager)

    # Use action (verb=3) with direction south (argument=1 for S)
    env.stepAction(0, ActionUse, 1)  # S direction

    # Should have gained RepairHpPerAction (2) HP
    check house.hp == 52

  test "repair rate is faster than construction rate":
    let env = makeEmptyEnv()
    # Constructed building (repair)
    let repairBuilding = env.addBuilding(House, ivec2(5, 5), 0)
    repairBuilding.maxHp = 100
    repairBuilding.hp = 50
    repairBuilding.constructed = true

    # Under-construction building (not yet constructed)
    let buildBuilding = env.addBuilding(Barracks, ivec2(10, 5), 0)
    buildBuilding.maxHp = 100
    buildBuilding.hp = 50
    buildBuilding.constructed = false

    # Villager repairs the house
    let agent0 = env.addAgentAt(0, ivec2(5, 4), unitClass = UnitVillager)
    # Villager constructs the barracks
    let agent1 = env.addAgentAt(1, ivec2(10, 4), unitClass = UnitVillager)

    env.stepAction(0, ActionUse, 1)  # agent 0 repairs house (S direction)

    let repairGain = repairBuilding.hp - 50
    check repairGain == RepairHpPerAction  # 2

    # Now step for construction
    let env2 = makeEmptyEnv()
    let buildBuilding2 = env2.addBuilding(Barracks, ivec2(10, 5), 0)
    buildBuilding2.maxHp = 100
    buildBuilding2.hp = 50
    buildBuilding2.constructed = false
    let agent2 = env2.addAgentAt(0, ivec2(10, 4), unitClass = UnitVillager)
    env2.stepAction(0, ActionUse, 1)

    let constructGain = buildBuilding2.hp - 50
    check constructGain == ConstructionHpPerAction  # 1

    # Repair is faster
    check RepairHpPerAction > ConstructionHpPerAction

  test "repair does not exceed maxHp":
    let env = makeEmptyEnv()
    let house = env.addBuilding(House, ivec2(5, 5), 0)
    house.maxHp = 100
    house.hp = 99
    house.constructed = true

    let agent = env.addAgentAt(0, ivec2(5, 4), unitClass = UnitVillager)
    env.stepAction(0, ActionUse, 1)

    check house.hp == 100  # Capped at maxHp
    check house.constructed == true

suite "Repair - Multi-Builder Bonus":
  test "two villagers repair faster with diminishing returns":
    let env = makeEmptyEnv()
    let house = env.addBuilding(House, ivec2(5, 5), 0)
    house.maxHp = 200
    house.hp = 100
    house.constructed = true

    # Two villagers adjacent to the house
    let agent0 = env.addAgentAt(0, ivec2(5, 4), unitClass = UnitVillager)  # N of house
    let agent1 = env.addAgentAt(1, ivec2(5, 6), unitClass = UnitVillager)  # S of house

    # Both use toward the house
    # agent0 at (5,4) faces S (arg=1) toward (5,5)
    # agent1 at (5,6) faces N (arg=0) toward (5,5)
    var actions: array[MapAgents, uint16]
    for i in 0 ..< MapAgents:
      actions[i] = 0
    # Fill agents so step works
    while env.agents.len < MapAgents:
      let nextId = env.agents.len
      let filler = Thing(
        kind: Agent, pos: ivec2(-1, -1), agentId: nextId,
        orientation: N, inventory: emptyInventory(),
        hp: 0, maxHp: AgentMaxHp, attackDamage: 1,
        unitClass: UnitVillager, stance: StanceNoAttack,
        homeAltar: ivec2(-1, -1), rallyTarget: ivec2(-1, -1)
      )
      env.add(filler)
      env.terminated[nextId] = 1.0
    actions[0] = encodeAction(ActionUse, 1)  # S toward house
    actions[1] = encodeAction(ActionUse, 0)  # N toward house
    env.step(addr actions)
    env.ensureObservations()

    # Two builders: ConstructionBonusTable[2] = 1.5
    # Repair HP = round(RepairHpPerAction * 1.5) = round(2 * 1.5) = 3
    let hpGain = house.hp - 100
    check hpGain == 3

  test "three villagers get appropriate bonus":
    let env = makeEmptyEnv()
    let house = env.addBuilding(House, ivec2(5, 5), 0)
    house.maxHp = 200
    house.hp = 100
    house.constructed = true

    # Three villagers around the house
    discard env.addAgentAt(0, ivec2(5, 4), unitClass = UnitVillager)  # N
    discard env.addAgentAt(1, ivec2(5, 6), unitClass = UnitVillager)  # S
    discard env.addAgentAt(2, ivec2(4, 5), unitClass = UnitVillager)  # W

    while env.agents.len < MapAgents:
      let nextId = env.agents.len
      let filler = Thing(
        kind: Agent, pos: ivec2(-1, -1), agentId: nextId,
        orientation: N, inventory: emptyInventory(),
        hp: 0, maxHp: AgentMaxHp, attackDamage: 1,
        unitClass: UnitVillager, stance: StanceNoAttack,
        homeAltar: ivec2(-1, -1), rallyTarget: ivec2(-1, -1)
      )
      env.add(filler)
      env.terminated[nextId] = 1.0
    var actions: array[MapAgents, uint16]
    for i in 0 ..< MapAgents:
      actions[i] = 0
    actions[0] = encodeAction(ActionUse, 1)  # S toward house
    actions[1] = encodeAction(ActionUse, 0)  # N toward house
    actions[2] = encodeAction(ActionUse, 3)  # E toward house
    env.step(addr actions)
    env.ensureObservations()

    # Three builders: ConstructionBonusTable[3] = 1.83
    # Repair HP = round(2 * 1.83) = round(3.66) = 4
    let hpGain = house.hp - 100
    check hpGain == 4

suite "Repair - Construction Flag":
  test "building becomes constructed when first reaching maxHp":
    let env = makeEmptyEnv()
    let house = env.addBuilding(House, ivec2(5, 5), 0)
    house.maxHp = 10
    house.hp = 9
    house.constructed = false  # Still under construction

    let agent = env.addAgentAt(0, ivec2(5, 4), unitClass = UnitVillager)
    env.stepAction(0, ActionUse, 1)

    # hp should reach maxHp (9 + 1 = 10, construction uses ConstructionHpPerAction=1)
    check house.hp == 10
    check house.constructed == true

  test "only villagers can repair":
    let env = makeEmptyEnv()
    let house = env.addBuilding(House, ivec2(5, 5), 0)
    house.maxHp = 100
    house.hp = 50
    house.constructed = true

    # Place a non-villager (ManAtArms) adjacent
    let soldier = env.addAgentAt(0, ivec2(5, 4), unitClass = UnitManAtArms)

    let hpBefore = house.hp
    env.stepAction(0, ActionUse, 1)

    # Soldier cannot repair - HP unchanged
    check house.hp == hpBefore

  test "cannot repair enemy building":
    let env = makeEmptyEnv()
    # Building owned by team 1
    let house = env.addBuilding(House, ivec2(5, 5), 1)
    house.maxHp = 100
    house.hp = 50
    house.constructed = true

    # Villager on team 0
    let agent = env.addAgentAt(0, ivec2(5, 4), unitClass = UnitVillager)

    let hpBefore = house.hp
    env.stepAction(0, ActionUse, 1)

    # Cannot repair enemy building
    check house.hp == hpBefore
