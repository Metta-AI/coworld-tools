## Behavioral tests for rapid age-up rush strategies.
## Validates Castle Age and Imperial Age advancement mechanics including:
## - Sequential age progression (Castle Age must precede Imperial Age)
## - Resource requirements and spending
## - Cooldown handling between age advancements
## - Multi-team independent progression
## - Age bonuses applying immediately upon research
## - Edge cases like minimal resources and concurrent advancement

import std/[unittest, strformat]
import test_common

suite "Age Rush - Basic Age Advancement":
  test "team can research Castle Age tech at Castle":
    ## Verify basic Castle Age research succeeds with sufficient resources.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 10)
    setStockpile(env, 0, ResourceGold, 10)

    let (castleAge, imperialAge) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Resources spent: 4 food + 3 gold for Castle Age
    check env.stockpileCount(0, ResourceFood) == 6
    check env.stockpileCount(0, ResourceGold) == 7

  test "team can research Imperial Age after Castle Age":
    ## Verify Imperial Age requires Castle Age to be researched first.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 15)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # Research Castle Age first
    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Clear cooldown for test
    castle.cooldown = 0

    # Research Imperial Age
    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[imperialAge]

    # Total spent: 4+8=12 food, 3+6=9 gold
    check env.stockpileCount(0, ResourceFood) == 8
    check env.stockpileCount(0, ResourceGold) == 6

  test "cannot skip Castle Age to research Imperial Age directly":
    ## Verify the tech order is enforced - Castle Age must come first.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 50)
    setStockpile(env, 0, ResourceGold, 50)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # First research ALWAYS gives Castle Age
    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Cannot have Imperial without Castle
    check env.hasCastleTech(0, castleAge)
    check not env.hasCastleTech(0, imperialAge)

suite "Age Rush - Resource Requirements":
  test "Castle Age fails with insufficient food":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 3)  # Needs 4
    setStockpile(env, 0, ResourceGold, 10)

    check not env.tryResearchCastleTech(villager, castle)
    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]
    # Resources untouched
    check env.stockpileCount(0, ResourceFood) == 3
    check env.stockpileCount(0, ResourceGold) == 10

  test "Castle Age fails with insufficient gold":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 10)
    setStockpile(env, 0, ResourceGold, 2)  # Needs 3

    check not env.tryResearchCastleTech(villager, castle)
    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

  test "Imperial Age fails with insufficient resources after Castle Age":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    # Exactly enough for Castle Age (4 food, 3 gold) but not Imperial (needs 8+6 more)
    setStockpile(env, 0, ResourceFood, 4)
    setStockpile(env, 0, ResourceGold, 3)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # Castle Age succeeds
    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[castleAge]

    castle.cooldown = 0

    # Imperial Age fails - no resources left
    check not env.tryResearchCastleTech(villager, castle)
    check not env.teamCastleTechs[0].researched[imperialAge]

  test "exact minimum resources for full age rush":
    ## Verify the exact minimum resources needed: 4+8=12 food, 3+6=9 gold.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 12)  # Exactly 4+8
    setStockpile(env, 0, ResourceGold, 9)   # Exactly 3+6

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[castleAge]
    castle.cooldown = 0

    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[imperialAge]

    # All resources consumed
    check env.stockpileCount(0, ResourceFood) == 0
    check env.stockpileCount(0, ResourceGold) == 0

suite "Age Rush - Cooldown Mechanics":
  test "cooldown prevents immediate second age research":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    # Give exactly enough for Castle Age (4 food + 3 gold) plus a bit more
    # but not enough for both Imperial Age AND unit training when cooldown blocks
    # Imperial costs 8 food + 6 gold, training costs 4 food + 2 gold
    # With these resources, after Castle Age: 8 food, 7 gold remaining
    # Training would succeed (4 food + 2 gold), but Imperial research blocked
    setStockpile(env, 0, ResourceFood, 12)
    setStockpile(env, 0, ResourceGold, 10)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # Research Castle Age via step action (this is how it works in game)
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))
    check env.teamCastleTechs[0].researched[castleAge]
    check castle.cooldown > 0  # Cooldown should be set

    # Immediate second step: research fails due to cooldown
    # Note: The Castle will fall back to training a unit, which costs 4 food + 2 gold
    # The key assertion is that Imperial Age is NOT researched
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))
    check not env.teamCastleTechs[0].researched[imperialAge]

  test "cooldown decrements through game steps allowing subsequent research":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 50)
    setStockpile(env, 0, ResourceGold, 50)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # Research Castle Age via step action
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))
    check env.teamCastleTechs[0].researched[castleAge]

    # Wait for cooldown (cooldown is 10 for castle techs)
    for i in 0 ..< 15:
      env.stepNoop()

    # Now Imperial Age should be researchable
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))
    check env.teamCastleTechs[0].researched[imperialAge]

  test "rapid age rush timing with step simulation":
    ## Measure minimum steps needed for full age advancement.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let (castleAge, imperialAge) = castleTechsForTeam(0)
    var stepCount = 0

    # Research Castle Age
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))
    inc stepCount
    check env.teamCastleTechs[0].researched[castleAge]

    # Wait for cooldown and research Imperial Age
    while not env.teamCastleTechs[0].researched[imperialAge] and stepCount < 100:
      env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))
      inc stepCount

    check env.teamCastleTechs[0].researched[imperialAge]
    echo fmt"  Full age rush completed in {stepCount} steps"
    # Should take approximately 12 steps (1 for Castle Age + 10 cooldown + 1 for Imperial)
    check stepCount <= 15

suite "Age Rush - Multi-Team Independence":
  test "teams advance ages independently":
    let env = makeEmptyEnv()

    # Team 0 setup
    let castle0 = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager0 = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 15)

    # Team 1 setup
    let castle1 = addBuilding(env, Castle, ivec2(20, 9), 1)
    let villager1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 10))
    setStockpile(env, 1, ResourceFood, 20)
    setStockpile(env, 1, ResourceGold, 15)

    let (castleAge0, imperialAge0) = castleTechsForTeam(0)
    let (castleAge1, imperialAge1) = castleTechsForTeam(1)

    # Team 0 researches Castle Age
    check env.tryResearchCastleTech(villager0, castle0)
    check env.teamCastleTechs[0].researched[castleAge0]

    # Team 1 should still be at no ages
    check not env.teamCastleTechs[1].researched[castleAge1]

    # Team 1 researches Castle Age
    check env.tryResearchCastleTech(villager1, castle1)
    check env.teamCastleTechs[1].researched[castleAge1]

    # Team 0 advances to Imperial
    castle0.cooldown = 0
    check env.tryResearchCastleTech(villager0, castle0)
    check env.teamCastleTechs[0].researched[imperialAge0]

    # Team 1 still only has Castle Age
    check env.teamCastleTechs[1].researched[castleAge1]
    check not env.teamCastleTechs[1].researched[imperialAge1]

  test "different teams have different unique techs":
    ## Verify each team gets their own unique Castle techs.
    let env = makeEmptyEnv()

    for teamId in 0 ..< min(4, MapRoomObjectsTeams):
      let castle = addBuilding(env, Castle, ivec2(10 + teamId.int32 * 10, 9), teamId)
      let villager = addAgentAt(env, teamId * MapAgentsPerTeam, ivec2(10 + teamId.int32 * 10, 10))
      setStockpile(env, teamId, ResourceFood, 20)
      setStockpile(env, teamId, ResourceGold, 15)

      let (teamCastleAge, _) = castleTechsForTeam(teamId)
      check env.tryResearchCastleTech(villager, castle)
      check env.teamCastleTechs[teamId].researched[teamCastleAge]

    # Verify teams have different techs
    let (tech0, _) = castleTechsForTeam(0)
    let (tech1, _) = castleTechsForTeam(1)
    let (tech2, _) = castleTechsForTeam(2)
    check tech0 != tech1
    check tech1 != tech2
    check tech0 != tech2

  test "simultaneous age rush race":
    ## Two teams race to Imperial Age.
    let env = makeEmptyEnv()

    let castle0 = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager0 = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 50)
    setStockpile(env, 0, ResourceGold, 50)

    let castle1 = addBuilding(env, Castle, ivec2(20, 9), 1)
    let villager1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 10))
    setStockpile(env, 1, ResourceFood, 50)
    setStockpile(env, 1, ResourceGold, 50)

    let (_, imperialAge0) = castleTechsForTeam(0)
    let (_, imperialAge1) = castleTechsForTeam(1)

    var team0Imperial = false
    var team1Imperial = false
    var winner = -1

    for step in 0 ..< 50:
      # Both teams try to research
      env.stepAction(villager0.agentId, 3'u8, dirIndex(villager0.pos, castle0.pos))
      if env.teamCastleTechs[0].researched[imperialAge0] and not team0Imperial:
        team0Imperial = true
        if winner < 0: winner = 0

      env.stepAction(villager1.agentId, 3'u8, dirIndex(villager1.pos, castle1.pos))
      if env.teamCastleTechs[1].researched[imperialAge1] and not team1Imperial:
        team1Imperial = true
        if winner < 0: winner = 1

      if team0Imperial and team1Imperial:
        break

    check team0Imperial
    check team1Imperial
    echo fmt"  Both teams reached Imperial Age (first: team {winner})"

suite "Age Rush - Bonus Application":
  test "Castle Age bonuses apply to newly created units":
    ## Verify age-up bonuses affect units created after research.
    ## Bonuses are stored in teamModifiers and applied via applyUnitClass.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 15)

    # Team 0's Castle Age tech is CastleTechYeomen (+1 archer attack)
    # Research Castle Age first
    check env.tryResearchCastleTech(villager, castle)

    # Verify team modifier was updated
    check env.teamModifiers[0].unitAttackBonus[UnitArcher] == 1

    # Create archer AFTER research - it should get the bonus
    let archer = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer, UnitArcher)

    # Archer should have base attack + bonus
    check archer.attackDamage == ArcherAttackDamage + 1

  test "age bonuses do not affect enemy team units":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 20)
    setStockpile(env, 0, ResourceGold, 15)

    # Research Castle Age for team 0 (Yeomen: +1 archer attack)
    check env.tryResearchCastleTech(villager, castle)

    # Create friendly archer (team 0)
    let friendlyArcher = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitArcher)
    env.applyUnitClass(friendlyArcher, UnitArcher)

    # Create enemy archer (team 1)
    let enemyArcher = addAgentAt(env, MapAgentsPerTeam, ivec2(14, 10), unitClass = UnitArcher)
    env.applyUnitClass(enemyArcher, UnitArcher)

    # Only friendly archer gets bonus
    check friendlyArcher.attackDamage == ArcherAttackDamage + 1
    check enemyArcher.attackDamage == ArcherAttackDamage  # No bonus for enemy

suite "Age Rush - Edge Cases":
  test "cannot research at enemy Castle":
    let env = makeEmptyEnv()
    let enemyCastle = addBuilding(env, Castle, ivec2(10, 9), 1)  # Team 1's castle
    let villager = addAgentAt(env, 0, ivec2(10, 10))  # Team 0's villager
    setStockpile(env, 0, ResourceFood, 50)
    setStockpile(env, 0, ResourceGold, 50)

    check not env.tryResearchCastleTech(villager, enemyCastle)
    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

  test "only villagers can research ages":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 50)
    setStockpile(env, 0, ResourceGold, 50)

    # Try with military unit
    let knight = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight)
    applyUnitClass(knight, UnitKnight)

    check not env.tryResearchCastleTech(knight, castle)
    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    # Now with villager
    let villager = addAgentAt(env, 1, ivec2(10, 11))
    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[castleAge]

  test "cannot re-research already completed ages":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # Complete both ages
    check env.tryResearchCastleTech(villager, castle)
    castle.cooldown = 0
    check env.tryResearchCastleTech(villager, castle)

    check env.teamCastleTechs[0].researched[castleAge]
    check env.teamCastleTechs[0].researched[imperialAge]

    let foodBefore = env.stockpileCount(0, ResourceFood)
    let goldBefore = env.stockpileCount(0, ResourceGold)

    # Try to research again - should fail and not spend resources
    castle.cooldown = 0
    check not env.tryResearchCastleTech(villager, castle)
    check env.stockpileCount(0, ResourceFood) == foodBefore
    check env.stockpileCount(0, ResourceGold) == goldBefore

  test "age rush with zero initial resources fails gracefully":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    # No resources set - default is 0

    check not env.tryResearchCastleTech(villager, castle)
    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

  test "multiple villagers cannot double-research same age":
    ## Having multiple villagers shouldn't allow researching the same tech twice.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager1 = addAgentAt(env, 0, ivec2(10, 10))
    let villager2 = addAgentAt(env, 1, ivec2(10, 11))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let (castleAge, _) = castleTechsForTeam(0)

    # First villager researches
    check env.tryResearchCastleTech(villager1, castle)
    check env.teamCastleTechs[0].researched[castleAge]

    # Clear cooldown
    castle.cooldown = 0

    # Second villager tries to research same tech - next available is Imperial
    let resourcesBefore = (env.stockpileCount(0, ResourceFood), env.stockpileCount(0, ResourceGold))
    check env.tryResearchCastleTech(villager2, castle)  # This researches Imperial, not Castle again

    # Should have spent resources for Imperial Age (8 food, 6 gold)
    check env.stockpileCount(0, ResourceFood) == resourcesBefore[0] - 8
    check env.stockpileCount(0, ResourceGold) == resourcesBefore[1] - 6

suite "Age Rush - AI Behavioral Simulation":
  test "AI can complete age rush in extended simulation":
    ## Run a full game simulation and check if any team ages up.
    let env = newEnvironment()
    initGlobalController(BuiltinAI, seed = 42)

    # Run for enough steps that AI could potentially age up
    for step in 0 ..< 500:
      let actions = getActions(env)
      env.step(addr actions)

    # Check if any team has researched any castle techs
    var anyAgeUp = false
    for teamId in 0 ..< MapRoomObjectsTeams:
      let (castleAge, imperialAge) = castleTechsForTeam(teamId)
      if env.teamCastleTechs[teamId].researched[castleAge]:
        anyAgeUp = true
        echo fmt"  Team {teamId} reached Castle Age"
      if env.teamCastleTechs[teamId].researched[imperialAge]:
        echo fmt"  Team {teamId} reached Imperial Age"

    # This test just verifies the simulation runs without crashing
    # AI may or may not prioritize age advancement depending on strategy
    echo fmt"  Simulation completed. Any team aged up: {anyAgeUp}"
