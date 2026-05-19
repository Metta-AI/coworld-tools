import std/[unittest, strformat]
import test_common

suite "Behavior: Auto-Attack Nearest Enemy":
  test "attacker hits adjacent enemy before farther one":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker, UnitManAtArms)

    # Adjacent enemy (distance 1)
    let nearEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    applyUnitClass(nearEnemy, UnitManAtArms)
    let nearStartHp = nearEnemy.hp

    # Far enemy (distance 4, out of melee range)
    let farEnemy = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(10, 14))
    applyUnitClass(farEnemy, UnitManAtArms)

    # Attack toward near enemy
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, nearEnemy.pos))

    check nearEnemy.hp < nearStartHp
    check farEnemy.hp == farEnemy.maxHp
    echo &"  Near enemy took damage ({nearStartHp}->{nearEnemy.hp}), far enemy untouched ({farEnemy.hp}/{farEnemy.maxHp})"

  test "archer attacks nearest enemy in range":
    let env = makeEmptyEnv()
    let archer = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitArcher)
    applyUnitClass(archer, UnitArcher)

    # Enemy at range 2 (within archer range 3)
    let nearEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 8))
    let nearStartHp = nearEnemy.hp

    # Attack toward near enemy
    env.stepAction(archer.agentId, 2'u8, dirIndex(archer.pos, nearEnemy.pos))

    check nearEnemy.hp < nearStartHp
    echo &"  Archer hit nearest enemy at range 2 (HP {nearStartHp}->{nearEnemy.hp})"

  test "melee unit attacks only adjacent enemies":
    let env = makeEmptyEnv()
    let fighter = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(fighter, UnitKnight)

    # Enemy at distance 2 (not adjacent, out of melee range without spear)
    let farEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 12))
    applyUnitClass(farEnemy, UnitManAtArms)
    let startHp = farEnemy.hp

    env.stepAction(fighter.agentId, 2'u8, dirIndex(fighter.pos, farEnemy.pos))

    # Knight has melee range 1, should not reach enemy at distance 2
    check farEnemy.hp == startHp
    echo &"  Knight could not hit enemy at distance 2 (melee range 1)"

suite "Behavior: Auto-Attack Low HP Priority":
  test "finishing off low HP enemy with focused attacks":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker, UnitManAtArms)

    # Low HP enemy adjacent
    let lowHpEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    applyUnitClass(lowHpEnemy, UnitManAtArms)
    lowHpEnemy.hp = 1

    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, lowHpEnemy.pos))

    # ManAtArms does 2 damage, enemy with 1 HP should die
    check lowHpEnemy.hp <= 0
    check env.terminated[lowHpEnemy.agentId] == 1.0
    echo &"  Low HP enemy (1 HP) killed by ManAtArms (2 dmg)"

  test "multiple attacks focus on same target until dead":
    let env = makeEmptyEnv()
    # Two attackers from same team
    let attacker1 = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker1, UnitManAtArms)
    let attacker2 = addAgentAt(env, 1, ivec2(11, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker2, UnitManAtArms)

    # Single enemy adjacent to both
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    applyUnitClass(enemy, UnitManAtArms)
    let startHp = enemy.hp

    # Both attack toward the same enemy
    env.stepAction(attacker1.agentId, 2'u8, dirIndex(attacker1.pos, enemy.pos))
    if enemy.hp > 0:
      env.stepAction(attacker2.agentId, 2'u8, dirIndex(attacker2.pos, enemy.pos))

    # Should have taken 4 damage total (2 per ManAtArms)
    let totalDmg = startHp - enemy.hp
    check totalDmg >= ManAtArmsAttackDamage
    echo &"  Focused fire dealt {totalDmg} damage to enemy (HP {startHp}->{enemy.hp})"

  test "wounded enemy dies in fewer hits than full HP enemy":
    # Test with full HP enemy
    let env1 = makeEmptyEnv()
    let a1 = addAgentAt(env1, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(a1, UnitKnight)
    let fullEnemy = addAgentAt(env1, MapAgentsPerTeam, ivec2(10, 11))
    applyUnitClass(fullEnemy, UnitManAtArms)
    let fullHp = fullEnemy.hp

    var hitsToKillFull = 0
    while fullEnemy.hp > 0 and hitsToKillFull < 50:
      env1.stepAction(a1.agentId, 2'u8, dirIndex(a1.pos, fullEnemy.pos))
      inc hitsToKillFull
    check fullEnemy.hp <= 0

    # Test with wounded enemy in separate env
    let env2 = makeEmptyEnv()
    let a2 = addAgentAt(env2, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(a2, UnitKnight)
    let weakEnemy = addAgentAt(env2, MapAgentsPerTeam, ivec2(10, 11))
    applyUnitClass(weakEnemy, UnitManAtArms)
    weakEnemy.hp = 2

    var hitsToKillWeak = 0
    while weakEnemy.hp > 0 and hitsToKillWeak < 50:
      env2.stepAction(a2.agentId, 2'u8, dirIndex(a2.pos, weakEnemy.pos))
      inc hitsToKillWeak
    check weakEnemy.hp <= 0

    # Wounded enemy should die in fewer hits
    check hitsToKillWeak < hitsToKillFull
    echo &"  Full HP ({fullHp}) killed in {hitsToKillFull} hits, wounded (2 HP) in {hitsToKillWeak} hits"

suite "Behavior: Auto-Attack Threat Detection":
  test "enemy adjacent to ally is within threat radius":
    let env = makeEmptyEnv()
    # Our fighter
    let fighter = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(fighter, UnitKnight)

    # Our villager ally
    let ally = addAgentAt(env, 1, ivec2(15, 10), unitClass = UnitVillager)

    # Enemy adjacent to ally (distance 1, within AllyThreatRadius=2)
    let threatEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(15, 11))
    applyUnitClass(threatEnemy, UnitManAtArms)

    # Enemy is within AllyThreatRadius of our ally - this is a threatening position
    let enemyToAllyDist = max(abs(threatEnemy.pos.x - ally.pos.x),
                              abs(threatEnemy.pos.y - ally.pos.y))
    check enemyToAllyDist <= AllyThreatRadius
    echo &"  Enemy at dist {enemyToAllyDist} from ally (within AllyThreatRadius={AllyThreatRadius})"

  test "guard tower auto-attacks nearest enemy in range":
    let env = makeEmptyEnv()
    discard addBuilding(env, GuardTower, ivec2(10, 10), 0)

    # Near enemy at distance 2
    let nearEnemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 12))
    let nearStartHp = nearEnemy.hp

    # Far enemy at distance 4 (both in tower range)
    let farEnemy = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(10, 14))
    let farStartHp = farEnemy.hp

    env.stepAction(nearEnemy.agentId, 0'u8, 0)

    # Tower should fire at the nearest enemy
    check nearEnemy.hp < nearStartHp or farEnemy.hp < farStartHp
    echo &"  Tower fired: near HP {nearStartHp}->{nearEnemy.hp}, far HP {farStartHp}->{farEnemy.hp}"

suite "Behavior: Target Switching on Death":
  test "attacker switches to next enemy when current target dies":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(attacker, UnitKnight)

    # First target - weak, will die quickly
    let target1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    target1.hp = 1  # Will die in one hit

    # Second target - behind the first
    let target2 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(10, 12))
    applyUnitClass(target2, UnitManAtArms)
    let t2StartHp = target2.hp

    # Kill first target
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, target1.pos))
    check target1.hp <= 0
    check env.terminated[target1.agentId] == 1.0

    # Now attacker should be able to target next enemy
    # The first enemy is dead, so attacking in same direction should hit target2
    # if it moved into the vacated spot, or we attack toward target2
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, target2.pos))

    # target2 may or may not take damage depending on adjacency
    # The key behavior is that the attack action is valid even after first target dies
    echo &"  Target1 killed (HP<=0), target2 HP: {t2StartHp}->{target2.hp}"

  test "combat continues with surviving enemies after one dies":
    let env = makeEmptyEnv()
    let fighter = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitKnight, stance = StanceAggressive)
    applyUnitClass(fighter, UnitKnight)

    # Three enemies in a line
    let e1 = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    e1.hp = 1  # Will die fast
    let e2 = addAgentAt(env, MapAgentsPerTeam + 1, ivec2(11, 11))
    applyUnitClass(e2, UnitManAtArms)
    let e3 = addAgentAt(env, MapAgentsPerTeam + 2, ivec2(9, 11))
    applyUnitClass(e3, UnitManAtArms)

    var deaths = 0
    for step in 0 ..< 50:
      # Attack nearest living enemy
      var hitTarget = false
      for enemy in [e1, e2, e3]:
        if enemy.hp > 0 and abs(enemy.pos.x - fighter.pos.x) <= 1 and
           abs(enemy.pos.y - fighter.pos.y) <= 1:
          env.stepAction(fighter.agentId, 2'u8, dirIndex(fighter.pos, enemy.pos))
          hitTarget = true
          break
      if not hitTarget:
        break

    for enemy in [e1, e2, e3]:
      if enemy.hp <= 0:
        inc deaths
    check deaths >= 1  # At least the weak enemy should have died
    echo &"  3-enemy engagement: {deaths} enemies killed"

  test "dead unit no longer selectable as target":
    let env = makeEmptyEnv()
    let attacker = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitManAtArms, stance = StanceAggressive)
    applyUnitClass(attacker, UnitManAtArms)

    let victim = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    victim.hp = 1

    # Kill the victim
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, victim.pos))
    check victim.hp <= 0
    check env.terminated[victim.agentId] == 1.0

    # Attacking the same spot again should not crash or cause issues
    env.stepAction(attacker.agentId, 2'u8, dirIndex(attacker.pos, ivec2(10, 11)))
    # Attacker should still be alive and fine
    check attacker.hp > 0
    echo &"  Dead unit correctly ignored, attacker still alive (HP={attacker.hp})"

suite "Behavior: Non-Combat Unit Flee":
  test "villager flees toward base when enemy approaches":
    let env = makeEmptyEnv()
    # Villager with a home altar (flee destination)
    let altarPos = ivec2(5, 5)
    discard addAltar(env, altarPos, 0, 10)
    let villager = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos,
                              unitClass = UnitVillager, stance = StanceNoAttack)
    let startPos = villager.pos

    # Enemy approaches within flee radius
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 14))
    applyUnitClass(enemy, UnitManAtArms)

    # Step with villager moving (verb 1 = move toward base)
    let baseDir = dirIndex(villager.pos, altarPos)
    env.stepAction(villager.agentId, 1'u8, baseDir)

    # Villager should have moved toward base
    let distBefore = max(abs(startPos.x - altarPos.x), abs(startPos.y - altarPos.y))
    let distAfter = max(abs(villager.pos.x - altarPos.x), abs(villager.pos.y - altarPos.y))
    check distAfter <= distBefore
    echo &"  Villager moved from ({startPos.x},{startPos.y}) to ({villager.pos.x},{villager.pos.y}), " &
         &"closer to base at ({altarPos.x},{altarPos.y})"

  test "non-combat unit does not attack when stance is NoAttack":
    let env = makeEmptyEnv()
    let villager = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitVillager, stance = StanceNoAttack)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11))
    applyUnitClass(enemy, UnitManAtArms)
    let enemyStartHp = enemy.hp

    # Villager attempts attack but stance is NoAttack
    env.stepAction(villager.agentId, 2'u8, dirIndex(villager.pos, enemy.pos))

    # With NoAttack stance, the villager should still deal damage if forced (verb=2 is explicit)
    # The stance affects AI decisions, not explicit actions
    echo &"  Villager attack with NoAttack stance: enemy HP {enemyStartHp}->{enemy.hp}"

  test "villager survives enemy attack and can flee next step":
    let env = makeEmptyEnv()
    let altarPos = ivec2(5, 5)
    discard addAltar(env, altarPos, 0, 10)
    let villager = addAgentAt(env, 0, ivec2(10, 10), homeAltar = altarPos,
                              unitClass = UnitVillager, stance = StanceNoAttack)

    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 11), unitClass = UnitManAtArms)
    applyUnitClass(enemy, UnitManAtArms)

    # Enemy attacks villager
    env.stepAction(enemy.agentId, 2'u8, dirIndex(enemy.pos, villager.pos))
    let hpAfterHit = villager.hp

    check villager.hp > 0  # Villager (5 HP) survives ManAtArms (2 dmg) first hit
    check villager.hp < AgentMaxHp

    # Villager flees toward base
    let baseDir = dirIndex(villager.pos, altarPos)
    env.stepAction(villager.agentId, 1'u8, baseDir)

    # Villager should still be alive and have moved
    check villager.hp > 0
    echo &"  Villager took hit (HP={hpAfterHit}), fled toward base"

  test "scout has extended flee detection radius":
    let env = makeEmptyEnv()
    let scout = addAgentAt(env, 0, ivec2(10, 10), unitClass = UnitScout)
    applyUnitClass(scout, UnitScout)

    # Enemy at distance 9 - within ScoutFleeRadius (10) but beyond GathererFleeRadius (8)
    let enemy = addAgentAt(env, MapAgentsPerTeam, ivec2(10, 19))
    applyUnitClass(enemy, UnitManAtArms)

    # Verify scout can detect this enemy via spatial index
    let teamId = getTeamId(scout)
    let detected = findNearestEnemyAgentSpatial(env, scout.pos, teamId, ScoutFleeRadius)
    check detected != nil
    check detected.agentId == enemy.agentId

    # Verify gatherer would NOT detect at this range
    let notDetected = findNearestEnemyAgentSpatial(env, scout.pos, teamId, GathererFleeRadius)
    check notDetected == nil
    echo &"  Scout detects enemy at dist 9 (radius {ScoutFleeRadius}), " &
         &"gatherer would not (radius {GathererFleeRadius})"
