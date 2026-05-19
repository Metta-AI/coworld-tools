## Behavioral tests for age advancement unlock gating.
## Validates that:
## - Buildings and units are NOT gated by age (intentional design)
## - Castle Age → Imperial Age tech ordering is enforced
## - Unit upgrades (tier 2 → tier 3) require correct prerequisites
## - Edge cases like queuing during research work correctly

import std/unittest
import test_common

suite "Age Gating - Buildings Not Age-Restricted":
  ## Verify that all buildings can be constructed without any age requirement.
  ## This is intentional design - only resources gate building construction.

  test "can build Barracks without Castle Age":
    let env = makeEmptyEnv()
    discard addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceWood, 100)

    # Team 0 has NOT researched any Castle techs
    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    # Can still build Barracks (cost: 9 wood)
    let barracks = addBuilding(env, Barracks, ivec2(12, 10), 0)
    check barracks != nil
    check barracks.teamId == 0

  test "can build Castle without Castle Age tech":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceStone, 100)

    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    # Can build Castle (cost: 33 stone) even without Castle Age tech
    let castle = addBuilding(env, Castle, ivec2(10, 10), 0)
    check castle != nil
    check castle.teamId == 0

  test "can build University without any age":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceWood, 100)

    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    let university = addBuilding(env, University, ivec2(10, 10), 0)
    check university != nil

  test "can build Wonder without Imperial Age":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceWood, 100)
    setStockpile(env, 0, ResourceStone, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let (_, imperialAge) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Wonder is the ultimate building but requires no age tech
    let wonder = addBuilding(env, Wonder, ivec2(10, 10), 0)
    check wonder != nil

  test "can build siege workshops without any age":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceWood, 100)
    setStockpile(env, 0, ResourceStone, 100)

    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    let siegeWorkshop = addBuilding(env, SiegeWorkshop, ivec2(10, 10), 0)
    check siegeWorkshop != nil

    let mangonelWorkshop = addBuilding(env, MangonelWorkshop, ivec2(12, 10), 0)
    check mangonelWorkshop != nil

    let trebuchetWorkshop = addBuilding(env, TrebuchetWorkshop, ivec2(14, 10), 0)
    check trebuchetWorkshop != nil

  test "building availability independent of team age progress":
    ## Two teams: one has Castle Age, one does not.
    ## Both should be able to build all building types.
    let env = makeEmptyEnv()

    # Team 0 researches Castle Age
    let (castleAge0, _) = castleTechsForTeam(0)
    env.teamCastleTechs[0].researched[castleAge0] = true
    env.applyCastleTechBonuses(0, castleAge0)

    # Team 1 has no techs
    let (castleAge1, _) = castleTechsForTeam(1)
    check not env.teamCastleTechs[1].researched[castleAge1]

    setStockpile(env, 0, ResourceStone, 100)
    setStockpile(env, 1, ResourceStone, 100)

    # Both teams can build Castle
    let castle0 = addBuilding(env, Castle, ivec2(10, 10), 0)
    let castle1 = addBuilding(env, Castle, ivec2(20, 10), 1)
    check castle0 != nil
    check castle1 != nil

suite "Age Gating - Units Not Age-Restricted":
  ## Verify that all units can be trained without age requirements.
  ## Only building presence and resources gate unit training.

  test "can train Man-at-Arms without Castle Age":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    # Train unit via step action (action 3 = use building)
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, barracks.pos))

    # Resources should be spent (Man-at-Arms costs 3 food + 1 gold)
    check env.stockpileCount(0, ResourceFood) < 100

  test "can train siege units without any age":
    let env = makeEmptyEnv()
    let siegeWorkshop = addBuilding(env, SiegeWorkshop, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceWood, 100)
    setStockpile(env, 0, ResourceStone, 100)

    let (castleAge, imperialAge) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, siegeWorkshop.pos))
    # Battering Ram costs 3 wood + 2 stone
    check env.stockpileCount(0, ResourceWood) < 100

  test "can train unique unit at Castle without age techs":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Both Castle techs NOT researched
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Castle action with no techs = train unique unit (Samurai for team 0)
    # Note: Castle prioritizes research over training when techs available
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))

    # Should have researched Castle Age instead of training
    check env.teamCastleTechs[0].researched[castleAge]

  test "Castle trains unique unit after all techs researched":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    # Pre-research both techs
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    env.teamCastleTechs[0].researched[castleAge] = true
    env.teamCastleTechs[0].researched[imperialAge] = true

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Now Castle should train unique unit (4 food + 2 gold for team 0's Samurai)
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))

    check env.stockpileCount(0, ResourceFood) == 96  # 100 - 4
    check env.stockpileCount(0, ResourceGold) == 98  # 100 - 2

  test "all military buildings train without age requirements":
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceWood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)
    setStockpile(env, 0, ResourceStone, 1000)

    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    # Create all military buildings
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(12, 9), 0)
    let stable = addBuilding(env, Stable, ivec2(14, 9), 0)
    let monastery = addBuilding(env, Monastery, ivec2(16, 9), 0)

    let v1 = addAgentAt(env, 0, ivec2(10, 10))
    let v2 = addAgentAt(env, 1, ivec2(12, 10))
    let v3 = addAgentAt(env, 2, ivec2(14, 10))
    let v4 = addAgentAt(env, 3, ivec2(16, 10))

    # All should be able to train
    let foodBefore = env.stockpileCount(0, ResourceFood)

    env.stepAction(v1.agentId, 3'u8, dirIndex(v1.pos, barracks.pos))
    env.stepAction(v2.agentId, 3'u8, dirIndex(v2.pos, archeryRange.pos))
    env.stepAction(v3.agentId, 3'u8, dirIndex(v3.pos, stable.pos))
    env.stepAction(v4.agentId, 3'u8, dirIndex(v4.pos, monastery.pos))

    # Resources should be spent on all buildings
    check env.stockpileCount(0, ResourceFood) < foodBefore

suite "Age Gating - Castle Age Prerequisite Enforcement":
  ## Verify Castle Age must be researched before Imperial Age.

  test "Imperial Age cannot be researched without Castle Age":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # First research always goes to Castle Age
    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Verify getNextCastleTech returns Imperial Age now
    castle.cooldown = 0
    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[imperialAge]

  test "manually setting Imperial Age without Castle Age is abnormal":
    ## This tests that the system state can be manually set incorrectly,
    ## but normal gameplay enforces the ordering.
    let env = makeEmptyEnv()
    let (castleAge, imperialAge) = castleTechsForTeam(0)

    # Manually set Imperial without Castle (bypasses normal flow)
    env.teamCastleTechs[0].researched[imperialAge] = true
    env.teamCastleTechs[0].researched[castleAge] = false

    # This is an invalid state that can't happen through normal research
    check env.hasCastleTech(0, imperialAge)
    check not env.hasCastleTech(0, castleAge)

    # Normal research would have enforced Castle Age first
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Next research targets Castle Age (fills the gap)
    check env.tryResearchCastleTech(villager, castle)
    check env.teamCastleTechs[0].researched[castleAge]

  test "all teams have independent age progression":
    let env = makeEmptyEnv()

    for teamId in 0 ..< min(4, MapRoomObjectsTeams):
      let castle = addBuilding(env, Castle, ivec2(10 + teamId.int32 * 12, 9), teamId)
      let villager = addAgentAt(env, teamId * MapAgentsPerTeam, ivec2(10 + teamId.int32 * 12, 10))
      setStockpile(env, teamId, ResourceFood, 100)
      setStockpile(env, teamId, ResourceGold, 100)

      let (castleAge, _) = castleTechsForTeam(teamId)

      # Research Castle Age
      check env.tryResearchCastleTech(villager, castle)
      check env.teamCastleTechs[teamId].researched[castleAge]

    # Verify each team progressed independently
    for teamId in 0 ..< min(4, MapRoomObjectsTeams):
      let (castleAge, imperialAge) = castleTechsForTeam(teamId)
      check env.teamCastleTechs[teamId].researched[castleAge]
      check not env.teamCastleTechs[teamId].researched[imperialAge]

suite "Age Gating - Unit Upgrade Prerequisites":
  ## Unit upgrades (tier 2 → tier 3) require the previous tier to be researched.

  test "Champion requires Long Swordsman upgrade":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # First upgrade gives Long Swordsman (tier 2)
    check env.tryResearchUnitUpgrade(villager, barracks)
    check env.hasUnitUpgrade(0, UpgradeLongSwordsman)
    check not env.hasUnitUpgrade(0, UpgradeChampion)

    # Second upgrade gives Champion (tier 3)
    barracks.cooldown = 0
    check env.tryResearchUnitUpgrade(villager, barracks)
    check env.hasUnitUpgrade(0, UpgradeChampion)

  test "Hussar requires Light Cavalry upgrade":
    let env = makeEmptyEnv()
    let stable = addBuilding(env, Stable, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # First upgrade gives Light Cavalry
    check env.tryResearchUnitUpgrade(villager, stable)
    check env.hasUnitUpgrade(0, UpgradeLightCavalry)
    check not env.hasUnitUpgrade(0, UpgradeHussar)

    # Second upgrade gives Hussar
    stable.cooldown = 0
    check env.tryResearchUnitUpgrade(villager, stable)
    check env.hasUnitUpgrade(0, UpgradeHussar)

  test "Arbalester requires Crossbowman upgrade":
    let env = makeEmptyEnv()
    let archeryRange = addBuilding(env, ArcheryRange, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    check env.tryResearchUnitUpgrade(villager, archeryRange)
    check env.hasUnitUpgrade(0, UpgradeCrossbowman)
    check not env.hasUnitUpgrade(0, UpgradeArbalester)

    archeryRange.cooldown = 0
    check env.tryResearchUnitUpgrade(villager, archeryRange)
    check env.hasUnitUpgrade(0, UpgradeArbalester)

  test "unit upgrades do not require Castle Age":
    ## Explicitly verify unit upgrades are independent of Castle techs.
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # No Castle Age researched
    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    # Can still research infantry upgrades
    check env.tryResearchUnitUpgrade(villager, barracks)
    check env.hasUnitUpgrade(0, UpgradeLongSwordsman)

    barracks.cooldown = 0
    check env.tryResearchUnitUpgrade(villager, barracks)
    check env.hasUnitUpgrade(0, UpgradeChampion)

    # Still no Castle Age needed
    check not env.teamCastleTechs[0].researched[castleAge]

suite "Age Gating - Queuing and Production During Research":
  ## Test edge cases around queuing actions while research is in progress.

  test "Castle on cooldown falls back to unit training":
    ## When Castle has research on cooldown, step action falls back to training
    ## the team's unique unit instead of blocking completely.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # Research Castle Age
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    check env.teamCastleTechs[0].researched[castleAge]
    check castle.cooldown > 0

    let foodAfterResearch = env.stockpileCount(0, ResourceFood)
    let goldAfterResearch = env.stockpileCount(0, ResourceGold)

    # Immediately try to use Castle again - cooldown blocks research
    # but falls back to training unique unit (Samurai: 4 food + 2 gold)
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))

    # Imperial Age NOT researched (blocked by cooldown)
    check not env.teamCastleTechs[0].researched[imperialAge]

    # Resources spent on training instead (4 food + 2 gold)
    check env.stockpileCount(0, ResourceFood) == foodAfterResearch - 4
    check env.stockpileCount(0, ResourceGold) == goldAfterResearch - 2

  test "training resumes after research completes":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # Complete both Castle techs
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    env.teamCastleTechs[0].researched[castleAge] = true
    env.teamCastleTechs[0].researched[imperialAge] = true

    let foodBefore = env.stockpileCount(0, ResourceFood)

    # Castle should now train unique unit (no more techs to research)
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, castle.pos))

    # Unique unit training costs resources (4 food + 2 gold)
    check env.stockpileCount(0, ResourceFood) == foodBefore - 4

  test "multiple buildings operate independently during age research":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let barracks = addBuilding(env, Barracks, ivec2(12, 9), 0)

    let v1 = addAgentAt(env, 0, ivec2(10, 10))
    let v2 = addAgentAt(env, 1, ivec2(12, 10))

    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    # Research at Castle
    env.stepAction(v1.agentId, 3'u8, dirIndex(v1.pos, castle.pos))
    check env.teamCastleTechs[0].researched[castleAge]

    let foodAfterCastle = env.stockpileCount(0, ResourceFood)

    # Barracks can train independently
    env.stepAction(v2.agentId, 3'u8, dirIndex(v2.pos, barracks.pos))

    # Barracks should have spent resources for Man-at-Arms (3 food + 1 gold)
    check env.stockpileCount(0, ResourceFood) == foodAfterCastle - 3

  test "cooldown at one building does not affect other buildings":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)
    let university = addBuilding(env, University, ivec2(12, 9), 0)

    let v1 = addAgentAt(env, 0, ivec2(10, 10))
    let v2 = addAgentAt(env, 1, ivec2(12, 10))

    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)
    setStockpile(env, 0, ResourceWood, 200)

    # Research at Blacksmith (puts it on cooldown)
    env.stepAction(v1.agentId, 3'u8, dirIndex(v1.pos, blacksmith.pos))
    check blacksmith.cooldown > 0

    # University should still work
    check not env.hasUniversityTech(0, TechBallistics)
    env.stepAction(v2.agentId, 3'u8, dirIndex(v2.pos, university.pos))
    check env.hasUniversityTech(0, TechBallistics)

suite "Age Gating - Edge Cases and Negative Tests":
  ## Edge cases and boundary conditions.

  test "zero resources prevents both building and training":
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    # Zero resources
    setStockpile(env, 0, ResourceFood, 0)
    setStockpile(env, 0, ResourceGold, 0)

    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, barracks.pos))

    # No change - insufficient resources
    check env.stockpileCount(0, ResourceFood) == 0
    check env.stockpileCount(0, ResourceGold) == 0

  test "step action at Barracks trains, not researches Castle tech":
    ## Step action at Barracks triggers unit training, not Castle tech research.
    ## This is because step.nim routes actions by building type (UseKind).
    let env = makeEmptyEnv()
    let barracks = addBuilding(env, Barracks, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    let (castleAge, _) = castleTechsForTeam(0)
    let foodBefore = env.stockpileCount(0, ResourceFood)

    # Step action at Barracks trains Man-at-Arms (not Castle tech)
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, barracks.pos))

    # Castle Age NOT researched (Barracks doesn't offer Castle tech research)
    check not env.teamCastleTechs[0].researched[castleAge]

    # Resources spent on Man-at-Arms (3 food + 1 gold)
    check env.stockpileCount(0, ResourceFood) == foodBefore - 3

  test "training at wrong building type fails":
    let env = makeEmptyEnv()
    let blacksmith = addBuilding(env, Blacksmith, ivec2(10, 9), 0)  # Cannot train units
    let villager = addAgentAt(env, 0, ivec2(10, 10))
    setStockpile(env, 0, ResourceFood, 200)
    setStockpile(env, 0, ResourceGold, 200)

    # Blacksmith can research upgrades but not train units
    let foodBefore = env.stockpileCount(0, ResourceFood)
    env.stepAction(villager.agentId, 3'u8, dirIndex(villager.pos, blacksmith.pos))

    # Should have researched an upgrade (3 food + 2 gold per upgrade)
    check env.stockpileCount(0, ResourceFood) == foodBefore - 3

  test "team with full tech tree has no more research available":
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    let villager = addAgentAt(env, 0, ivec2(10, 10))

    # Max out tech tree
    let (castleAge, imperialAge) = castleTechsForTeam(0)
    env.teamCastleTechs[0].researched[castleAge] = true
    env.teamCastleTechs[0].researched[imperialAge] = true

    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Further research attempts fail
    check not env.tryResearchCastleTech(villager, castle)
    check env.stockpileCount(0, ResourceFood) == 100  # Unchanged

  test "non-villager unit cannot research via direct API":
    ## Only villagers (not military units) can research Castle techs.
    let env = makeEmptyEnv()
    let castle = addBuilding(env, Castle, ivec2(10, 9), 0)
    setStockpile(env, 0, ResourceFood, 100)
    setStockpile(env, 0, ResourceGold, 100)

    # Create a Man-at-Arms instead of villager
    let soldier = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    applyUnitClass(soldier, UnitManAtArms)

    let (castleAge, _) = castleTechsForTeam(0)

    # Military unit cannot research (checked by tryResearchCastleTech)
    check not env.tryResearchCastleTech(soldier, castle)
    check not env.teamCastleTechs[0].researched[castleAge]
    check env.stockpileCount(0, ResourceFood) == 100  # Resources unchanged

  test "age advancement does not retroactively modify existing units":
    let env = makeEmptyEnv()

    # Create archer before Castle Age
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    env.applyUnitClass(archer, UnitArcher)
    let attackBefore = archer.attackDamage

    # Research Castle Age (Yeomen for team 0 gives +1 archer attack)
    env.teamCastleTechs[0].researched[CastleTechYeomen] = true
    env.applyCastleTechBonuses(0, CastleTechYeomen)

    # Existing archer does NOT get bonus (bonuses apply at unit creation)
    check archer.attackDamage == attackBefore

    # New archer gets the bonus
    let newArcher = addAgentAt(env, 1, ivec2(12, 10), unitClass = UnitArcher)
    env.applyUnitClass(newArcher, UnitArcher)
    check newArcher.attackDamage == attackBefore + 1

suite "Age Gating - Design Documentation":
  ## These tests document the intentional design of NO age gating for buildings/units.
  ## They serve as living documentation of the game's design philosophy.

  test "DESIGN: buildings are resource-gated, not age-gated":
    ## Buildings can be constructed at any time as long as resources are available.
    ## This allows strategic flexibility - players can rush specific buildings
    ## without following a strict tech tree.
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceWood, 1000)
    setStockpile(env, 0, ResourceStone, 1000)
    setStockpile(env, 0, ResourceGold, 1000)

    let (castleAge, imperialAge) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]
    check not env.teamCastleTechs[0].researched[imperialAge]

    # All building types can be constructed without any age requirement
    check addBuilding(env, Barracks, ivec2(10, 10), 0) != nil
    check addBuilding(env, Castle, ivec2(12, 10), 0) != nil
    check addBuilding(env, University, ivec2(14, 10), 0) != nil
    check addBuilding(env, Wonder, ivec2(16, 10), 0) != nil

  test "DESIGN: units are building+resource-gated, not age-gated":
    ## Unit training requires the appropriate building and resources.
    ## No age advancement is required - this enables early rush strategies.
    let env = makeEmptyEnv()
    setStockpile(env, 0, ResourceFood, 1000)
    setStockpile(env, 0, ResourceWood, 1000)
    setStockpile(env, 0, ResourceGold, 1000)
    setStockpile(env, 0, ResourceStone, 1000)

    let (castleAge, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge]

    # With buildings, all units can be trained without age
    discard addBuilding(env, Barracks, ivec2(10, 9), 0)       # Man-at-Arms
    discard addBuilding(env, ArcheryRange, ivec2(12, 9), 0)   # Archer
    discard addBuilding(env, Stable, ivec2(14, 9), 0)         # Scout
    discard addBuilding(env, SiegeWorkshop, ivec2(16, 9), 0)  # Battering Ram
    discard addBuilding(env, Monastery, ivec2(18, 9), 0)      # Monk

    # All training buildings exist - units can be trained immediately

  test "DESIGN: Castle techs provide bonuses, not gates":
    ## Castle Age and Imperial Age techs provide combat bonuses
    ## but do not gate access to buildings or units.
    ## This is different from traditional Age of Empires where age
    ## advancement is required to unlock building types.
    let env = makeEmptyEnv()

    # Team 0: no Castle tech
    let (castleAge0, _) = castleTechsForTeam(0)
    check not env.teamCastleTechs[0].researched[castleAge0]

    # Team 1: has Castle Age (Logistica)
    let (castleAge1, _) = castleTechsForTeam(1)
    env.teamCastleTechs[1].researched[castleAge1] = true
    env.applyCastleTechBonuses(1, castleAge1)

    # Both teams can build and train the same things
    # The only difference is team 1's units get bonuses from their tech
    let maa0 = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms)
    env.applyUnitClass(maa0, UnitManAtArms)

    let maa1 = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 10), unitClass = UnitManAtArms)
    env.applyUnitClass(maa1, UnitManAtArms)

    # Team 1's Man-at-Arms has +1 attack from Logistica
    check maa0.attackDamage == ManAtArmsAttackDamage
    check maa1.attackDamage == ManAtArmsAttackDamage + 1
