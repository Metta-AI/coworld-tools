import std/[unittest]
import scripted/evolution
import entropy

suite "Evolution - Default Config":
  test "default config has valid ranges":
    let config = defaultEvolutionConfig()
    check config.minTiers >= 1
    check config.maxTiers >= config.minTiers
    check config.minTierSize >= 1
    check config.maxTierSize >= config.minTierSize
    check config.mutationRate > 0.0
    check config.mutationRate < 1.0
    check config.lockFitnessThreshold > 0.0
    check config.maxBehaviorsPerRole > 0

  test "default config specific values":
    let config = defaultEvolutionConfig()
    check config.minTiers == 2
    check config.maxTiers == 4
    check config.mutationRate == 0.15'f32
    check config.lockFitnessThreshold == 0.7'f32

suite "Evolution - Role Catalog":
  test "initRoleCatalog starts empty":
    let catalog = initRoleCatalog()
    check catalog.behaviors.len == 0
    check catalog.roles.len == 0
    check catalog.nextRoleId == 0
    check catalog.nextNameId == 0

  test "addBehavior registers behavior with correct id":
    var catalog = initRoleCatalog()
    let opt = OptionDef(name: "TestBehavior1")
    let id = catalog.addBehavior(opt, BehaviorCustom)
    check id == 0
    check catalog.behaviors.len == 1
    check catalog.behaviors[0].name == "TestBehavior1"
    check catalog.behaviors[0].source == BehaviorCustom

  test "addBehavior deduplicates by name":
    var catalog = initRoleCatalog()
    let opt1 = OptionDef(name: "TestBehavior")
    let opt2 = OptionDef(name: "TestBehavior")
    let id1 = catalog.addBehavior(opt1, BehaviorCustom)
    let id2 = catalog.addBehavior(opt2, BehaviorCustom)
    check id1 == id2
    check catalog.behaviors.len == 1

  test "findBehaviorId returns -1 for missing":
    let catalog = initRoleCatalog()
    check findBehaviorId(catalog, "NoSuchBehavior") == -1

  test "findBehaviorId finds registered behavior":
    var catalog = initRoleCatalog()
    let opt = OptionDef(name: "MyBehavior")
    discard catalog.addBehavior(opt, BehaviorCustom)
    check findBehaviorId(catalog, "MyBehavior") == 0

  test "registerRole assigns sequential ids":
    var catalog = initRoleCatalog()
    let role1 = newRoleDef(catalog, "Role1", @[], "test")
    let role2 = newRoleDef(catalog, "Role2", @[], "test")
    let id1 = registerRole(catalog, role1)
    let id2 = registerRole(catalog, role2)
    check id1 == 0
    check id2 == 1
    check catalog.roles.len == 2

  test "findRoleId returns -1 for missing":
    let catalog = initRoleCatalog()
    check findRoleId(catalog, "NoSuchRole") == -1

suite "Evolution - Sample Role":
  test "sampleRole from empty catalog returns EmptyRole":
    var catalog = initRoleCatalog()
    var rng = initRand(42)
    let role = sampleRole(catalog, rng)
    check role.name == "EmptyRole"

  test "sampleRole produces valid role with behaviors":
    var catalog = initRoleCatalog()
    for i in 0 ..< 10:
      let opt = OptionDef(name: "Behavior" & $i)
      discard catalog.addBehavior(opt, BehaviorCustom)
    var rng = initRand(42)
    let role = sampleRole(catalog, rng)
    check role.tiers.len >= 2  # minTiers default is 2
    check role.tiers.len <= 4  # maxTiers default is 4
    # Each tier should have at least one behavior
    for tier in role.tiers:
      check tier.behaviorIds.len >= 1

  test "sampleRole uses different seeds produce different results":
    var catalog = initRoleCatalog()
    for i in 0 ..< 10:
      let opt = OptionDef(name: "Behavior" & $i)
      discard catalog.addBehavior(opt, BehaviorCustom)
    var rng1 = initRand(42)
    var rng2 = initRand(999)
    let role1 = sampleRole(catalog, rng1)
    let role2 = sampleRole(catalog, rng2)
    # Different seeds should produce different roles (with high probability)
    var different = false
    if role1.tiers.len != role2.tiers.len:
      different = true
    else:
      for i in 0 ..< role1.tiers.len:
        if role1.tiers[i].behaviorIds != role2.tiers[i].behaviorIds:
          different = true
          break
    check different == true

suite "Evolution - Recombine Roles":
  test "recombine with both empty returns EmptyRole":
    var catalog = initRoleCatalog()
    var rng = initRand(42)
    let left = RoleDef(name: "Empty1", kind: Scripted, tiers: @[])
    let right = RoleDef(name: "Empty2", kind: Scripted, tiers: @[])
    let result = recombineRoles(catalog, rng, left, right)
    check result.name == "EmptyRole"

  test "recombine with one empty returns the other":
    var catalog = initRoleCatalog()
    let opt = OptionDef(name: "Behavior0")
    discard catalog.addBehavior(opt, BehaviorCustom)
    var rng = initRand(42)
    let tier = RoleTier(behaviorIds: @[0], selection: TierFixed)
    let left = RoleDef(name: "HasTiers", kind: Scripted, tiers: @[tier])
    let right = RoleDef(name: "Empty", kind: Scripted, tiers: @[])
    let result = recombineRoles(catalog, rng, left, right)
    check result.tiers.len >= 1

  test "recombine produces at least one tier":
    var catalog = initRoleCatalog()
    for i in 0 ..< 5:
      let opt = OptionDef(name: "B" & $i)
      discard catalog.addBehavior(opt, BehaviorCustom)
    var rng = initRand(42)
    let tier1 = RoleTier(behaviorIds: @[0, 1], selection: TierFixed)
    let tier2 = RoleTier(behaviorIds: @[2, 3], selection: TierShuffle)
    let left = RoleDef(name: "Left", kind: Scripted, tiers: @[tier1, tier2])
    let right = RoleDef(name: "Right", kind: Scripted, tiers: @[tier2, tier1])
    let result = recombineRoles(catalog, rng, left, right)
    check result.tiers.len >= 1

suite "Evolution - Mutate Role":
  test "mutate with zero rate makes no changes":
    var catalog = initRoleCatalog()
    for i in 0 ..< 5:
      let opt = OptionDef(name: "B" & $i)
      discard catalog.addBehavior(opt, BehaviorCustom)
    var rng = initRand(42)
    let tier = RoleTier(behaviorIds: @[0, 1, 2], selection: TierFixed)
    let role = RoleDef(name: "Test", kind: Scripted, tiers: @[tier])
    let result = mutateRole(catalog, rng, role, mutationRate = 0.0)
    check result.tiers[0].behaviorIds == @[0, 1, 2]
    check result.tiers[0].selection == TierFixed

  test "mutate with high rate changes behaviors":
    var catalog = initRoleCatalog()
    for i in 0 ..< 10:
      let opt = OptionDef(name: "B" & $i)
      discard catalog.addBehavior(opt, BehaviorCustom)
    var rng = initRand(42)
    let tier = RoleTier(behaviorIds: @[0, 1, 2], selection: TierFixed)
    let role = RoleDef(name: "Test", kind: Scripted, tiers: @[tier])
    # Run mutation many times to confirm it can change things
    var changed = false
    for seed in 0 ..< 50:
      var testRng = initRand(seed)
      let mutated = mutateRole(catalog, testRng, role, mutationRate = 1.0)
      if mutated.tiers[0].behaviorIds != @[0, 1, 2] or
         mutated.tiers[0].selection != TierFixed:
        changed = true
        break
    check changed == true

  test "mutate empty catalog returns role unchanged":
    let catalog = initRoleCatalog()
    var rng = initRand(42)
    let role = RoleDef(name: "Test", kind: Scripted, tiers: @[])
    let result = mutateRole(catalog, rng, role, mutationRate = 0.5)
    check result.tiers.len == 0

suite "Evolution - Record Role Score":
  test "first score sets fitness directly":
    var role = RoleDef(name: "Test", kind: Scripted, games: 0, fitness: 0.0)
    recordRoleScore(role, 0.8, won = true)
    check role.games == 1
    check role.wins == 1
    check role.fitness == 0.8'f32

  test "subsequent scores use EMA":
    var role = RoleDef(name: "Test", kind: Scripted, games: 0, fitness: 0.0)
    recordRoleScore(role, 1.0, won = true)
    check role.fitness == 1.0'f32
    recordRoleScore(role, 0.0, won = false)
    # EMA: 1.0 * 0.8 + 0.0 * 0.2 = 0.8
    check role.fitness == 0.8'f32
    check role.games == 2
    check role.wins == 1

  test "wins accumulate correctly":
    var role = RoleDef(name: "Test", kind: Scripted, games: 0, wins: 0)
    recordRoleScore(role, 0.5, won = true)
    recordRoleScore(role, 0.3, won = false)
    recordRoleScore(role, 0.7, won = true)
    check role.games == 3
    check role.wins == 2

  test "weight parameter records multiple games":
    var role = RoleDef(name: "Test", kind: Scripted, games: 0, fitness: 0.0)
    recordRoleScore(role, 0.5, won = false, weight = 3)
    check role.games == 3

suite "Evolution - Lock Role Name":
  test "lock name when fitness exceeds threshold":
    var role = RoleDef(name: "Test", kind: Scripted, fitness: 0.8, lockedName: false)
    lockRoleNameIfFit(role, 0.7)
    check role.lockedName == true

  test "do not lock name when fitness below threshold":
    var role = RoleDef(name: "Test", kind: Scripted, fitness: 0.5, lockedName: false)
    lockRoleNameIfFit(role, 0.7)
    check role.lockedName == false

  test "lock name at exact threshold":
    var role = RoleDef(name: "Test", kind: Scripted, fitness: 0.7, lockedName: false)
    lockRoleNameIfFit(role, 0.7)
    check role.lockedName == true

suite "Evolution - Selection Weights":
  test "roleSelectionWeight returns 0.1 for zero games":
    let role = RoleDef(name: "Test", kind: Scripted, games: 0, fitness: 0.0)
    check roleSelectionWeight(role) == 0.1'f32

  test "roleSelectionWeight returns fitness when positive":
    let role = RoleDef(name: "Test", kind: Scripted, games: 5, fitness: 0.6)
    check roleSelectionWeight(role) == 0.6'f32

  test "roleSelectionWeight minimum is 0.1":
    let role = RoleDef(name: "Test", kind: Scripted, games: 5, fitness: 0.01)
    check roleSelectionWeight(role) == 0.1'f32

  test "behaviorSelectionWeight returns 1.0 for zero games":
    let behavior = BehaviorDef(id: 0, name: "Test", games: 0, fitness: 0.0)
    check behaviorSelectionWeight(behavior) == 1.0'f32

  test "behaviorSelectionWeight returns fitness when positive":
    let behavior = BehaviorDef(id: 0, name: "Test", games: 5, fitness: 0.5)
    check behaviorSelectionWeight(behavior) == 0.5'f32

suite "Evolution - Weighted Pick":
  test "pickRoleIdWeighted returns -1 for empty array":
    let catalog = initRoleCatalog()
    var rng = initRand(42)
    let empty: seq[int] = @[]
    check pickRoleIdWeighted(catalog, rng, empty) == -1

  test "pickRoleIdWeighted returns sole role":
    var catalog = initRoleCatalog()
    var role = newRoleDef(catalog, "Only", @[], "test")
    role.games = 5
    role.fitness = 0.8
    discard registerRole(catalog, role)
    var rng = initRand(42)
    check pickRoleIdWeighted(catalog, rng, [0]) == 0

  test "weightedPickIndex always returns valid index":
    var rng = initRand(42)
    let weights = [0.1'f32, 0.5, 0.3, 0.1]
    for i in 0 ..< 100:
      let idx = weightedPickIndex(rng, weights)
      check idx >= 0
      check idx < weights.len

  test "weightedPickIndex with all zero weights returns valid index":
    var rng = initRand(42)
    let weights = [0.0'f32, 0.0, 0.0]
    let idx = weightedPickIndex(rng, weights)
    check idx >= 0
    check idx < weights.len

  test "generateRoleName increments name id":
    var catalog = initRoleCatalog()
    let opt = OptionDef(name: "TestBehavior")
    discard catalog.addBehavior(opt, BehaviorCustom)
    let tier = RoleTier(behaviorIds: @[0], selection: TierFixed)
    let name1 = generateRoleName(catalog, @[tier])
    let name2 = generateRoleName(catalog, @[tier])
    check name1 != name2
    check catalog.nextNameId == 2
