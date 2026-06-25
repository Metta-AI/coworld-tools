## Evolution helpers for sampling and recombining role definitions.

import roles
export roles

import ../entropy

type
  EvolutionConfig* = object
    minTiers*: int
    maxTiers*: int
    minTierSize*: int
    maxTierSize*: int
    mutationRate*: float32
    lockFitnessThreshold*: float32
    maxBehaviorsPerRole*: int

proc defaultEvolutionConfig*(): EvolutionConfig =
  EvolutionConfig(
    minTiers: 2,
    maxTiers: 4,
    minTierSize: 1,
    maxTierSize: 3,
    mutationRate: 0.15,
    lockFitnessThreshold: 0.7,
    maxBehaviorsPerRole: 12
  )

proc sampleUniqueIdsWeighted(rng: var Rand, catalog: RoleCatalog, count: int,
                             used: var seq[int]): seq[int] =
  if catalog.behaviors.len == 0 or count <= 0:
    return @[]
  var candidates: seq[int] = @[]
  var weights: seq[float32] = @[]
  for behavior in catalog.behaviors:
    var already = false
    for usedId in used:
      if usedId == behavior.id:
        already = true
        break
    if already:
      continue
    candidates.add behavior.id
    weights.add behaviorSelectionWeight(behavior)
  while result.len < count and candidates.len > 0:
    let idx = weightedPickIndex(rng, weights)
    result.add candidates[idx]
    used.add candidates[idx]
    candidates.delete(idx)
    weights.delete(idx)
  if result.len == 0 and catalog.behaviors.len > 0:
    let fallback = randIntExclusive(rng, 0, catalog.behaviors.len)
    result.add fallback
    used.add fallback

proc sampleRole*(catalog: var RoleCatalog, rng: var Rand,
                 config: EvolutionConfig = defaultEvolutionConfig()): RoleDef =
  let behaviorCount = catalog.behaviors.len
  if behaviorCount == 0:
    return RoleDef(name: "EmptyRole", kind: Scripted)
  let tierCount = randIntInclusive(rng, config.minTiers, config.maxTiers)
  var tiers: seq[RoleTier] = @[]
  var used: seq[int] = @[]
  for _ in 0 ..< tierCount:
    let tierSize = randIntInclusive(rng, config.minTierSize, config.maxTierSize)
    let cap = min(tierSize, config.maxBehaviorsPerRole)
    let ids = sampleUniqueIdsWeighted(rng, catalog, min(cap, behaviorCount), used)
    let selection = if randChance(rng, 0.5): TierShuffle else: TierFixed
    tiers.add RoleTier(behaviorIds: ids, selection: selection)
  let name = generateRoleName(catalog, tiers)
  newRoleDef(catalog, name, tiers, "sampled", Scripted)

proc recombineRoles*(catalog: var RoleCatalog, rng: var Rand,
                     left, right: RoleDef): RoleDef =
  if left.tiers.len == 0 and right.tiers.len == 0:
    return RoleDef(name: "EmptyRole", kind: Scripted)
  if left.tiers.len == 0:
    return right
  if right.tiers.len == 0:
    return left
  let cutLeft = randIntInclusive(rng, 0, left.tiers.len)
  let cutRight = randIntInclusive(rng, 0, right.tiers.len)
  var tiers: seq[RoleTier] = @[]
  if cutLeft > 0:
    tiers.add left.tiers[0 ..< cutLeft]
  if cutRight < right.tiers.len:
    tiers.add right.tiers[cutRight .. ^1]
  if tiers.len == 0:
    tiers.add left.tiers[0]
  let name = generateRoleName(catalog, tiers)
  let kind = if left.kind == right.kind: left.kind else: Scripted
  newRoleDef(catalog, name, tiers, "recombined", kind)

proc mutateRole*(catalog: RoleCatalog, rng: var Rand, role: RoleDef,
                 mutationRate: float32 = 0.15): RoleDef =
  result = role
  if catalog.behaviors.len == 0:
    return
  for i in 0 ..< result.tiers.len:
    if result.tiers[i].behaviorIds.len == 0:
      continue
    if randChance(rng, mutationRate):
      let idx = randIntExclusive(rng, 0, result.tiers[i].behaviorIds.len)
      let replacement = randIntExclusive(rng, 0, catalog.behaviors.len)
      result.tiers[i].behaviorIds[idx] = replacement
    if randChance(rng, mutationRate * 0.5):
      result.tiers[i].selection = if result.tiers[i].selection == TierFixed: TierShuffle else: TierFixed

proc recordRoleScore*(role: var RoleDef, score: float32,
                      won: bool, alpha: float32 = 0.2, weight: int = 1) =
  let count = max(1, weight)
  for _ in 0 ..< count:
    inc role.games
    if won:
      inc role.wins
    if role.games == 1:
      role.fitness = score
    else:
      role.fitness = role.fitness * (1 - alpha) + score * alpha

proc lockRoleNameIfFit*(role: var RoleDef, threshold: float32) =
  if role.fitness >= threshold:
    role.lockedName = true

proc roleSelectionWeight*(role: RoleDef): float32 =
  if role.games <= 0:
    return 0.1
  max(0.1, role.fitness)

proc pickRoleIdWeighted*(catalog: RoleCatalog, rng: var Rand,
                         roleIds: openArray[int]): int =
  if roleIds.len == 0:
    return -1
  var weights: seq[float32] = @[]
  for id in roleIds:
    if id >= 0 and id < catalog.roles.len:
      weights.add roleSelectionWeight(catalog.roles[id])
    else:
      weights.add 0.0
  let idx = weightedPickIndex(rng, weights)
  roleIds[idx]
