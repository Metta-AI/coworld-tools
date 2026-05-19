import std/[unittest, strformat]
import test_common

suite "Behavior: Team Bitmask Operations":
  test "team masks are correct for all teams":
    check TeamMasks[0] == 0b00000001'u8
    check TeamMasks[1] == 0b00000010'u8
    check TeamMasks[2] == 0b00000100'u8
    check TeamMasks[3] == 0b00001000'u8
    check TeamMasks[4] == 0b00010000'u8
    check TeamMasks[5] == 0b00100000'u8
    check TeamMasks[6] == 0b01000000'u8
    check TeamMasks[7] == 0b10000000'u8
    check TeamMasks[8] == 0b00000000'u8  # Goblins/invalid

  test "getTeamMask returns correct mask for valid teams":
    for teamId in 0 ..< MapRoomObjectsTeams:
      let mask = getTeamMask(teamId)
      check mask == (1'u8 shl teamId)
      echo fmt"  Team {teamId}: mask = 0b{mask:08b}"

  test "getTeamMask returns NoTeamMask for invalid teams":
    check getTeamMask(-1) == NoTeamMask
    check getTeamMask(MapRoomObjectsTeams) == NoTeamMask
    check getTeamMask(100) == NoTeamMask

  test "sameTeamMask works correctly for agents":
    let env = makeEmptyEnv()
    let a0 = addAgentAt(env, 0, ivec2(10, 10))
    let a1 = addAgentAt(env, 1, ivec2(10, 11))
    let a2 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 12))
    # Same team
    check sameTeamMask(a0, a1) == true
    check getTeamMask(a0) == getTeamMask(a1)
    # Different teams
    check sameTeamMask(a0, a2) == false
    check (getTeamMask(a0) and getTeamMask(a2)) == 0'u8
    echo fmt"  a0 mask={getTeamMask(a0):08b}, a1 mask={getTeamMask(a1):08b}, a2 mask={getTeamMask(a2):08b}"

  test "isEnemyMask works correctly for agents":
    let env = makeEmptyEnv()
    let a0 = addAgentAt(env, 0, ivec2(10, 10))
    let a1 = addAgentAt(env, 1, ivec2(10, 11))
    let a2 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 12))
    # Same team - not enemies
    check isEnemyMask(a0, a1) == false
    # Different teams - are enemies
    check isEnemyMask(a0, a2) == true
    check isEnemyMask(a1, a2) == true

  test "teamsShareMask with alliance masks":
    # Simulate alliance between teams 0, 1, 2
    let allianceMask: TeamMask = TeamMasks[0] or TeamMasks[1] or TeamMasks[2]
    check isTeamInMask(0, allianceMask) == true
    check isTeamInMask(1, allianceMask) == true
    check isTeamInMask(2, allianceMask) == true
    check isTeamInMask(3, allianceMask) == false
    check isTeamInMask(7, allianceMask) == false
    echo fmt"  Alliance mask 0|1|2: 0b{allianceMask:08b}"

suite "Behavior: Team Identity and Membership":
  test "agents on same team share team ID":
    let env = makeEmptyEnv()
    let a0 = addAgentAt(env, 0, ivec2(10, 10))
    let a1 = addAgentAt(env, 1, ivec2(10, 11))
    check getTeamId(a0) == 0
    check getTeamId(a1) == 0
    echo fmt"  Agent 0 team={getTeamId(a0)}, Agent 1 team={getTeamId(a1)}"

  test "agents on different teams have different team IDs":
    let env = makeEmptyEnv()
    let a0 = addAgentAt(env, 0, ivec2(10, 10))
    let a1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    check getTeamId(a0) == 0
    check getTeamId(a1) == 1
    echo fmt"  Agent 0 team={getTeamId(a0)}, Agent 1 team={getTeamId(a1)}"

  test "teamIdOverride changes effective team":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    check getTeamId(agent) == 0
    agent.teamIdOverride = 3
    check getTeamId(agent) == 3
    echo fmt"  Default team=0, override team={getTeamId(agent)}"

  test "clearing teamIdOverride restores default team":
    let env = makeEmptyEnv()
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.teamIdOverride = 5
    check getTeamId(agent) == 5
    agent.teamIdOverride = -1
    check getTeamId(agent) == 0
    echo fmt"  After clearing override: team={getTeamId(agent)}"

suite "Behavior: Combat Respects Team Affiliation":
  test "same-team attack is rejected":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10))
    attacker.attackDamage = 5
    let ally = addAgentAt(env, 1, ivec2(10, 9))
    let startHp = ally.hp

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, ally.pos))

    check ally.hp == startHp
    echo fmt"  Ally HP unchanged: {startHp} -> {ally.hp}"

  test "cross-team attack deals damage":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker, UnitManAtArms)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(enemy, UnitManAtArms)
    let startHp = enemy.hp

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, enemy.pos))

    check enemy.hp < startHp
    echo fmt"  Enemy HP: {startHp} -> {enemy.hp}"

  test "converted unit is treated as new team member by combat":
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    # Monk converts enemy; add attacker first (id 1) so it exists before stepAction
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    let attacker = addAgentAt(env, 1, ivec2(10, 8))
    attacker.attackDamage = 5
    let target = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    check getTeamId(target) == 1

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, target.pos))
    check getTeamId(target) == 0

    # Now a team 0 attacker should NOT be able to damage the converted unit
    let hpBefore = target.hp
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, target.pos))
    check target.hp == hpBefore
    echo fmt"  Converted unit HP unchanged by former ally attack: {hpBefore} -> {target.hp}"

  test "converted unit can be attacked by former allies":
    ## After conversion, the unit's old team can now attack it
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    let target = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    # Convert to team 0
    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, target.pos))
    check getTeamId(target) == 0

    # Manually set teamIdOverride to verify combat team check
    # Use a separate fresh env for clarity
    let env2 = makeEmptyEnv()
    let unit = addAgentAt(env2, MapAgentsPerTeam, ivec2(10, 9))
    unit.teamIdOverride = 0  # Simulate conversion to team 0
    updateTeamMask(unit)     # Update cached mask after override change
    let attacker = addAgentAt(env2, MapAgentsPerTeam + 1, ivec2(10, 8))
    attacker.attackDamage = 5
    let hpBefore = unit.hp
    env2.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, unit.pos))
    check unit.hp < hpBefore
    echo fmt"  Former ally attacks converted unit: HP {hpBefore} -> {unit.hp}"

suite "Behavior: Monk Conversion Diplomatic Transitions":
  test "monk conversion changes unit team membership":
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    check getTeamId(enemy) == 1
    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, enemy.pos))
    check getTeamId(enemy) == 0
    echo fmt"  Enemy team changed: 1 -> {getTeamId(enemy)}"

  test "conversion requires population capacity":
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    # No house means no pop capacity beyond TownCenter
    # Without any TownCenter or House, popCap = 0 so conversion fails
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, enemy.pos))
    check getTeamId(enemy) == 1  # Should stay on enemy team (no pop cap)
    echo fmt"  No pop capacity -> conversion blocked, enemy still team {getTeamId(enemy)}"

  test "conversion assigns converted unit to nearest altar":
    let env = makeEmptyEnv()
    let nearAltar = ivec2(11, 10)
    let farAltar = ivec2(20, 20)
    discard addAltar(env, nearAltar, 0, 10)
    discard addAltar(env, farAltar, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = nearAltar, unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, enemy.pos))
    check getTeamId(enemy) == 0
    # Converted unit should be assigned to the monk's home altar
    check enemy.homeAltar == nearAltar
    echo fmt"  Converted unit home altar: ({enemy.homeAltar.x}, {enemy.homeAltar.y})"

  test "double conversion returns unit to original default team":
    let env = makeEmptyEnv()
    # Setup: team 0 altar and housing
    let altar0 = ivec2(12, 10)
    discard addAltar(env, altar0, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    # Setup: team 1 altar and housing
    let altar1 = ivec2(20, 10)
    discard addAltar(env, altar1, 1, 10)
    discard addBuilding(env, House, ivec2(20, 11), 1)

    # Create all agents before any stepAction (which pads to MapAgents)
    let monk0 = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altar0, unitClass = UnitMonk)
    let target = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    let monk1 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(10, 8), homeAltar = altar1, unitClass = UnitMonk)
    check getTeamId(target) == 1

    # Team 0 monk converts team 1 unit
    env.stepAction(monk0.agentId, 2'u8, dirIndex(monk0.pos, target.pos))
    check getTeamId(target) == 0

    # Team 1 monk converts the unit back
    env.stepAction(monk1.agentId, 2'u8, dirIndex(monk1.pos, target.pos))
    # The unit's default team is 1 (agentId = MapAgentsPerTeam), so converting back should clear override
    check getTeamId(target) == 1
    echo fmt"  Double conversion restored team: {getTeamId(target)}"

suite "Behavior: Monk Aura Heals Allies Only":
  test "monk aura heals nearby same-team allies":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    let ally = addAgentAt(env, 1, ivec2(10, 11))
    ally.hp = 1
    ally.maxHp = 10
    let hpBefore = ally.hp

    env.stepNoop()  # Triggers monk aura processing

    check ally.hp > hpBefore
    echo fmt"  Ally healed by aura: {hpBefore} -> {ally.hp}"

  test "monk aura does not heal enemies":
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    enemy.hp = 1
    enemy.maxHp = 10
    let hpBefore = enemy.hp

    env.stepNoop()

    check enemy.hp == hpBefore
    echo fmt"  Enemy NOT healed by aura: {hpBefore} -> {enemy.hp}"

  test "converted unit receives aura healing from new team monk":
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos, unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    # Convert enemy to team 0
    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, enemy.pos))
    check getTeamId(enemy) == 0

    # Damage the converted unit
    enemy.hp = 1
    enemy.maxHp = 10
    let hpBefore = enemy.hp

    # Aura should now heal the converted unit (same team as monk)
    env.stepNoop()
    check enemy.hp > hpBefore
    echo fmt"  Converted unit healed by new team monk: {hpBefore} -> {enemy.hp}"

suite "Behavior: Item Giving Between Units":
  test "same-team agent can give items to teammate":
    let env = makeEmptyEnv()
    let giver = addAgentAt(env, 0, ivec2(10, 10))
    let receiver = addAgentAt(env, 1, ivec2(10, 9))
    setInv(giver, ItemWood, 5)

    env.stepAction(giver.agentId, 5'u8, dirIndex(giver.pos, receiver.pos))

    let giverWood = getInv(giver, ItemWood)
    let receiverWood = getInv(receiver, ItemWood)
    check giverWood == 0
    check receiverWood == 5
    echo fmt"  Gave wood: giver={giverWood}, receiver={receiverWood}"

  test "cross-team agent can give items to enemy":
    ## The put action does not restrict by team - any adjacent agent can receive
    let env = makeEmptyEnv()
    let giver = addAgentAt(env, 0, ivec2(10, 10))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))
    setInv(giver, ItemWood, 5)

    env.stepAction(giver.agentId, 5'u8, dirIndex(giver.pos, enemy.pos))

    let giverWood = getInv(giver, ItemWood)
    let enemyWood = getInv(enemy, ItemWood)
    check giverWood == 0
    check enemyWood == 5
    echo fmt"  Cross-team give: giver={giverWood}, enemy={enemyWood}"

suite "Behavior: Tower and Building Team Targeting":
  test "guard tower fires at enemy but not allies":
    let env = makeEmptyEnv()
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)
    # Create both agents before any step call (step pads agents to MapAgents)
    let ally = addAgentAt(env, 0, ivec2(10, 13))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 12))
    let allyHpBefore = ally.hp
    let enemyHpBefore = enemy.hp

    env.stepNoop()
    check ally.hp == allyHpBefore  # Tower doesn't fire at allies
    check enemy.hp < enemyHpBefore  # Tower fires at enemy
    echo fmt"  Ally HP unchanged={allyHpBefore}, Enemy HP {enemyHpBefore}->{enemy.hp}"

  test "town center fires at enemy but not allies":
    let env = makeEmptyEnv()
    discard addBuilding(env, TownCenter, ivec2(10, 10), 0)
    let ally = addAgentAt(env, 0, ivec2(10, 14))
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 13))
    let allyHpBefore = ally.hp
    let enemyHpBefore = enemy.hp

    env.stepNoop()
    check ally.hp == allyHpBefore
    check enemy.hp < enemyHpBefore
    echo fmt"  TC: Ally HP unchanged={allyHpBefore}, Enemy HP {enemyHpBefore}->{enemy.hp}"

  test "converted unit is no longer targeted by new team tower":
    ## After conversion, a team's own tower should not fire at the converted ally
    let env = makeEmptyEnv()
    let altarPos = ivec2(12, 10)
    discard addAltar(env, altarPos, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)
    # Monk adjacent to enemy for conversion
    let monk = addAgentAt(env, 0, ivec2(10, 12), homeAltar = altarPos, unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 13))

    # Convert enemy to team 0
    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, enemy.pos))
    check getTeamId(enemy) == 0

    let hpAfterConversion = enemy.hp
    # Tower should NOT fire at newly converted ally
    env.stepNoop()
    check enemy.hp == hpAfterConversion
    echo fmt"  Converted unit safe from new team tower: HP={enemy.hp}"

suite "Behavior: Multi-team Interactions":
  test "three teams can coexist with independent combat":
    let env = makeEmptyEnv()
    let team0 = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(team0, UnitManAtArms)
    let team1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(team1, UnitManAtArms)
    let team2 = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(15, 15))
    let team2HpBefore = team2.hp

    # Team 0 attacks team 1 - team 2 is far away and unaffected
    for step in 0 ..< 10:
      env.stepAction(team0.agentId, 2'u8, dirIndex(team0.pos, team1.pos))

    check team1.hp < team1.maxHp  # team 1 took damage
    check team2.hp == team2HpBefore  # team 2 unaffected
    echo fmt"  Team1 HP={team1.hp}, Team2 HP={team2.hp} (unaffected)"

  test "altar attack respects team - cannot attack own altar":
    let env = makeEmptyEnv()
    let altar = addAltar(env, ivec2(10, 9), 0, 10)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.attackDamage = 5
    let heartsBefore = altar.hearts

    env.stepAction(agent.agentId, 2'u8, dirIndex(agent.pos, altar.pos))
    check altar.hearts == heartsBefore
    echo fmt"  Own altar hearts unchanged: {heartsBefore}"

  test "altar attack works against enemy altar":
    let env = makeEmptyEnv()
    let altar = addAltar(env, ivec2(10, 9), 1, 10)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.attackDamage = 5
    let heartsBefore = altar.hearts

    env.stepAction(agent.agentId, 2'u8, dirIndex(agent.pos, altar.pos))
    check altar.hearts < heartsBefore
    echo fmt"  Enemy altar hearts: {heartsBefore} -> {altar.hearts}"

suite "Behavior: Multi-team Diplomacy State Transitions (3+ teams)":
  test "four teams have distinct team IDs":
    let env = makeEmptyEnv()
    let t0 = addAgentAt(env, 0, ivec2(10, 10))
    let t1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    let t2 = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 12))
    let t3 = addAgentAt(env, MapAgentsPerTeam * 3, ivec2(10, 13))
    check getTeamId(t0) == 0
    check getTeamId(t1) == 1
    check getTeamId(t2) == 2
    check getTeamId(t3) == 3
    echo fmt"  Teams: {getTeamId(t0)}, {getTeamId(t1)}, {getTeamId(t2)}, {getTeamId(t3)}"

  test "each team can attack every other team":
    ## In a 3-team scenario, all cross-team pairs are enemies
    ## Test each pair separately to avoid adjacency issues after stepping
    let env1 = makeEmptyEnv()
    let a0 = addAgentAt(env1, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(a0, UnitManAtArms)
    let a1 = addAgentAt(env1, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(a1, UnitManAtArms)
    let hp1Before = a1.hp
    env1.stepAction(a0.agentId, 2'u8, dirIndex(a0.pos, a1.pos))
    check a1.hp < hp1Before
    echo fmt"  T0->T1: HP {hp1Before} -> {a1.hp}"

    let env2 = makeEmptyEnv()
    let b0 = addAgentAt(env2, 0, ivec2(10, 9), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(b0, UnitManAtArms)
    let b2 = addAgentAt(env2, MapAgentsPerTeam * 2, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(b2, UnitManAtArms)
    let hp0Before = b0.hp
    env2.stepAction(b2.agentId, 2'u8, dirIndex(b2.pos, b0.pos))
    check b0.hp < hp0Before
    echo fmt"  T2->T0: HP {hp0Before} -> {b0.hp}"

    let env3 = makeEmptyEnv()
    let c1 = addAgentAt(env3, MapAgentsPerTeam, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(c1, UnitManAtArms)
    let c2 = addAgentAt(env3, MapAgentsPerTeam * 2, ivec2(10, 9), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(c2, UnitManAtArms)
    let hp2Before = c2.hp
    env3.stepAction(c1.agentId, 2'u8, dirIndex(c1.pos, c2.pos))
    check c2.hp < hp2Before
    echo fmt"  T1->T2: HP {hp2Before} -> {c2.hp}"

  test "altar conquest transfers ownership to attacking team":
    ## When team 0 conquers team 1's altar, it becomes team 0's
    let env = makeEmptyEnv()
    let altar = addAltar(env, ivec2(10, 9), 1, 1)  # 1 heart - easily conquered
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.attackDamage = 5
    check altar.teamId == 1

    env.stepAction(agent.agentId, 2'u8, dirIndex(agent.pos, altar.pos))
    check altar.hearts == 0
    check altar.teamId == 0
    echo fmt"  Altar conquered: team 1 -> team {altar.teamId}"

  test "altar conquest transfers doors to conquering team":
    ## When an altar is conquered, doors belonging to the old team switch to the attacker
    let env = makeEmptyEnv()
    let altar = addAltar(env, ivec2(10, 9), 1, 1)
    let door = Thing(kind: Door, pos: ivec2(15, 15), teamId: 1)
    door.inventory = emptyInventory()
    env.add(door)
    let agent = addAgentAt(env, 0, ivec2(10, 10))
    agent.attackDamage = 5

    check door.teamId == 1
    env.stepAction(agent.agentId, 2'u8, dirIndex(agent.pos, altar.pos))
    check altar.teamId == 0
    check door.teamId == 0
    echo fmt"  Door team transferred: 1 -> {door.teamId}"

  test "door access changes after altar conquest for three teams":
    ## Team 2 cannot pass team 1's door. Team 0 conquers team 1's altar.
    ## Now door belongs to team 0. Team 2 still cannot pass.
    let env = makeEmptyEnv()
    let altar = addAltar(env, ivec2(10, 9), 1, 1)
    let door = Thing(kind: Door, pos: ivec2(15, 15), teamId: 1)
    door.inventory = emptyInventory()
    env.add(door)
    let t0agent = addAgentAt(env, 0, ivec2(10, 10))
    t0agent.attackDamage = 5
    let t1agent = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    let t2agent = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(25, 25))

    # Before conquest: team 1 can pass, team 0 and 2 cannot
    check env.canAgentPassDoor(t1agent, door.pos) == true
    check env.canAgentPassDoor(t0agent, door.pos) == false
    check env.canAgentPassDoor(t2agent, door.pos) == false

    # Team 0 conquers team 1's altar
    env.stepAction(t0agent.agentId, 2'u8, dirIndex(t0agent.pos, altar.pos))
    check door.teamId == 0

    # After conquest: team 0 can pass, team 1 and 2 cannot
    check env.canAgentPassDoor(t0agent, door.pos) == true
    check env.canAgentPassDoor(t1agent, door.pos) == false
    check env.canAgentPassDoor(t2agent, door.pos) == false
    echo fmt"  Door access updated after conquest: T0=pass, T1=blocked, T2=blocked"

  test "monk conversion in three-team scenario changes team correctly":
    ## Team 0 monk converts team 2 unit; team 1 is unaffected
    let env = makeEmptyEnv()
    let altar0 = ivec2(12, 10)
    discard addAltar(env, altar0, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altar0, unitClass = UnitMonk)
    let t1unit = addAgentAt(env, MapAgentsPerTeam, ivec2(20, 20))
    let t2unit = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 9))

    check getTeamId(t1unit) == 1
    check getTeamId(t2unit) == 2

    # Convert team 2 unit to team 0
    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, t2unit.pos))
    check getTeamId(t2unit) == 0  # Now on team 0
    check getTeamId(t1unit) == 1  # Unaffected
    echo fmt"  T2 unit -> team {getTeamId(t2unit)}, T1 unit still team {getTeamId(t1unit)}"

  test "converted unit from team 2 can be attacked by team 1":
    ## After conversion to team 0 via override, team 1 can attack the unit
    let env = makeEmptyEnv()
    # Create agents in ascending agentId order to avoid padding issues
    let t1attacker = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(t1attacker, UnitManAtArms)
    let t2unit = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(t2unit, UnitManAtArms)
    # Simulate conversion to team 0
    t2unit.teamIdOverride = 0
    updateTeamMask(t2unit)  # Update cached mask after override change
    check getTeamId(t2unit) == 0

    let hpBefore = t2unit.hp
    env.stepAction(t1attacker.agentId, 2'u8, dirIndex(t1attacker.pos, t2unit.pos))
    check t2unit.hp < hpBefore
    echo fmt"  T1 attacks converted unit: HP {hpBefore} -> {t2unit.hp}"

  test "converted unit cannot attack new teammates":
    ## After conversion to team 0, the unit cannot damage team 0 members
    let env = makeEmptyEnv()
    let altar0 = ivec2(12, 10)
    discard addAltar(env, altar0, 0, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altar0, unitClass = UnitMonk)
    let t0ally = addAgentAt(env, 1, ivec2(10, 8))
    let t2unit = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 9))
    t2unit.attackDamage = 5

    # Convert team 2 unit to team 0
    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, t2unit.pos))
    check getTeamId(t2unit) == 0

    # Converted unit tries to attack team 0 ally - should be blocked
    let allyHpBefore = t0ally.hp
    env.stepAction(t2unit.agentId, 2'u8, dirIndex(t2unit.pos, t0ally.pos))
    check t0ally.hp == allyHpBefore
    echo fmt"  Converted unit blocked from attacking new teammate: HP unchanged at {t0ally.hp}"

  test "triple conversion across three teams":
    ## Unit starts on team 2, converted to team 0, then to team 1
    let env = makeEmptyEnv()
    let altar0 = ivec2(12, 10)
    let altar1 = ivec2(20, 10)
    discard addAltar(env, altar0, 0, 10)
    discard addAltar(env, altar1, 1, 10)
    discard addBuilding(env, House, ivec2(12, 11), 0)
    discard addBuilding(env, House, ivec2(20, 11), 1)
    let monk0 = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altar0, unitClass = UnitMonk)
    let monk1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8), homeAltar = altar1, unitClass = UnitMonk)
    let target = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 9))

    check getTeamId(target) == 2

    # Team 0 monk converts target from team 2 to team 0
    env.stepAction(monk0.agentId, 2'u8, dirIndex(monk0.pos, target.pos))
    check getTeamId(target) == 0
    echo fmt"  Step 1: team 2 -> {getTeamId(target)}"

    # Team 1 monk converts target from team 0 to team 1
    env.stepAction(monk1.agentId, 2'u8, dirIndex(monk1.pos, target.pos))
    check getTeamId(target) == 1
    echo fmt"  Step 2: team 0 -> {getTeamId(target)}"

  test "monk cannot convert same-team unit":
    ## Monk attack on same-team unit should heal, not convert
    let env = makeEmptyEnv()
    let monk = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitMonk)
    let ally = addAgentAt(env, 1, ivec2(10, 9))
    ally.hp = 1
    ally.maxHp = 10
    let hpBefore = ally.hp

    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, ally.pos))
    check getTeamId(ally) == 0  # Still on team 0
    check ally.hp > hpBefore    # Was healed instead
    echo fmt"  Same-team monk heals: HP {hpBefore} -> {ally.hp}, team still {getTeamId(ally)}"

  test "conversion blocked when population cap is full":
    ## Monk conversion should fail if the team has no pop capacity
    let env = makeEmptyEnv()
    let altar0 = ivec2(12, 10)
    discard addAltar(env, altar0, 0, 10)
    # No houses means limited pop cap; fill it up
    let monk = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altar0, unitClass = UnitMonk)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 9))

    # No TownCenter or House for team 0 means popCap = 0, but monk already counts
    # Without housing, conversion should be blocked
    env.stepAction(monk.agentId, 2'u8, dirIndex(monk.pos, enemy.pos))
    check getTeamId(enemy) == 1  # Stays on team 1
    echo fmt"  Conversion blocked (no pop cap): enemy still team {getTeamId(enemy)}"

  test "guard tower targets nearest enemy across three teams":
    ## Tower on team 0 should fire at enemies from any other team
    let env = makeEmptyEnv()
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)
    let t0ally = addAgentAt(env, 0, ivec2(10, 13))
    let t1enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 12))
    let t2enemy = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 14))
    let allyHpBefore = t0ally.hp
    let t1HpBefore = t1enemy.hp
    let t2HpBefore = t2enemy.hp

    env.stepNoop()
    check t0ally.hp == allyHpBefore  # Ally untouched
    # At least one enemy should take damage (tower picks closest)
    let anyEnemyDamaged = (t1enemy.hp < t1HpBefore) or (t2enemy.hp < t2HpBefore)
    check anyEnemyDamaged
    echo fmt"  Tower: Ally HP={t0ally.hp}, T1 HP={t1enemy.hp}, T2 HP={t2enemy.hp}"

  test "rally points only visible to same-team agents":
    ## Rally points set on a building should only appear in same-team observations
    let env = makeEmptyEnv()
    let building = addBuilding(env, TownCenter, ivec2(10, 10), 0)
    building.rallyPoint = ivec2(10, 12)
    let t0agent = addAgentAt(env, 0, ivec2(10, 11))
    let t1agent = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 13))
    let t2agent = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 14))

    env.stepNoop()

    # Check rally point layer in observations
    let rpLayer = ord(RallyPointLayer)
    # Rally at (10,12) relative to t0agent at (10,11): obsX = 10-10+radius, obsY = 12-11+radius
    let obsRadius = ObservationRadius
    let t0obsX = 10 - t0agent.pos.x + obsRadius
    let t0obsY = 12 - t0agent.pos.y + obsRadius
    if t0obsX >= 0 and t0obsX < ObservationWidth and t0obsY >= 0 and t0obsY < ObservationHeight:
      check env.observations[t0agent.agentId][rpLayer][t0obsX][t0obsY] == 1
      echo fmt"  T0 sees rally point: {env.observations[t0agent.agentId][rpLayer][t0obsX][t0obsY]}"

    # Team 1 agent should NOT see team 0's rally point
    let t1obsX = 10 - t1agent.pos.x + obsRadius
    let t1obsY = 12 - t1agent.pos.y + obsRadius
    if t1obsX >= 0 and t1obsX < ObservationWidth and t1obsY >= 0 and t1obsY < ObservationHeight:
      check env.observations[t1agent.agentId][rpLayer][t1obsX][t1obsY] == 0
      echo fmt"  T1 does not see rally point: {env.observations[t1agent.agentId][rpLayer][t1obsX][t1obsY]}"

  test "team layer observation shows correct team IDs for three teams":
    ## The TeamLayer observation should encode team+1 for agents from different teams
    let env = makeEmptyEnv()
    let t0 = addAgentAt(env, 0, ivec2(10, 10))
    let t1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    let t2 = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 12))

    env.stepNoop()

    let teamLayer = ord(TeamLayer)
    let obsRadius = ObservationRadius
    # From t0's perspective, check team layer at t1's position (10,11)
    let t1obsX = 10 - t0.pos.x + obsRadius
    let t1obsY = 11 - t0.pos.y + obsRadius
    if t1obsX >= 0 and t1obsX < ObservationWidth and t1obsY >= 0 and t1obsY < ObservationHeight:
      check env.observations[t0.agentId][teamLayer][t1obsX][t1obsY] == 2  # team 1 + 1
      echo fmt"  T0 sees T1 as team: {env.observations[t0.agentId][teamLayer][t1obsX][t1obsY]}"

    # From t0's perspective, check team layer at t2's position (10,12)
    let t2obsX = 10 - t0.pos.x + obsRadius
    let t2obsY = 12 - t0.pos.y + obsRadius
    if t2obsX >= 0 and t2obsX < ObservationWidth and t2obsY >= 0 and t2obsY < ObservationHeight:
      check env.observations[t0.agentId][teamLayer][t2obsX][t2obsY] == 3  # team 2 + 1
      echo fmt"  T0 sees T2 as team: {env.observations[t0.agentId][teamLayer][t2obsX][t2obsY]}"

  test "altar conquest by team 2 against team 1 with team 0 uninvolved":
    ## Verifies that team 2 can conquer team 1's altar while team 0 is uninvolved
    let env = makeEmptyEnv()
    let altar1 = addAltar(env, ivec2(10, 9), 1, 1)
    let t0agent = addAgentAt(env, 0, ivec2(20, 20))
    let t2agent = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 10))
    t2agent.attackDamage = 5

    check altar1.teamId == 1
    env.stepAction(t2agent.agentId, 2'u8, dirIndex(t2agent.pos, altar1.pos))
    check altar1.teamId == 2  # Conquered by team 2
    echo fmt"  Team 2 conquered team 1 altar: now team {altar1.teamId}"

  test "multiple doors transfer on altar conquest":
    ## All doors belonging to the old team transfer when their altar is conquered
    let env = makeEmptyEnv()
    let altar = addAltar(env, ivec2(10, 9), 1, 1)
    let door1 = Thing(kind: Door, pos: ivec2(15, 15), teamId: 1)
    door1.inventory = emptyInventory()
    env.add(door1)
    let door2 = Thing(kind: Door, pos: ivec2(16, 16), teamId: 1)
    door2.inventory = emptyInventory()
    env.add(door2)
    let door0 = Thing(kind: Door, pos: ivec2(17, 17), teamId: 0)
    door0.inventory = emptyInventory()
    env.add(door0)
    let agent = addAgentAt(env, MapAgentsPerTeam * 2, ivec2(10, 10))
    agent.attackDamage = 5

    env.stepAction(agent.agentId, 2'u8, dirIndex(agent.pos, altar.pos))
    check door1.teamId == 2  # Transferred to team 2
    check door2.teamId == 2  # Transferred to team 2
    check door0.teamId == 0  # Unaffected (belongs to team 0, not team 1)
    echo fmt"  Doors: d1={door1.teamId}, d2={door2.teamId}, d0={door0.teamId}"
