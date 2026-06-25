import std/[options, tables, algorithm, strutils]

import common
import nlanky_types
import nlanky_entity_map
import nlanky_nav

const
  SpawnRow = 100
  SpawnCol = 100

  JunctionAoeRange = 10
  HpSafetyMargin = 10

  TeamSufficientThreshold = 100

type
  NlankyContext* = object
    state*: StateSnapshot
    map*: EntityMap
    bb*: ptr Blackboard
    nav*: Navigator
    agentId*: int
    step*: int
    myTeamId*: Option[int]

  Goal* = ref object of RootObj

method name*(g: Goal): string {.base.} =
  "Goal"

method isSatisfied*(g: Goal, ctx: var NlankyContext): bool {.base.} =
  false

method preconditions*(g: Goal): seq[Goal] {.base.} =
  @[]

method execute*(g: Goal, ctx: var NlankyContext): Option[NavAction] {.base.} =
  some(naNoop)

proc locKey(pos: Location): string =
  $pos.y & "," & $pos.x

proc directionBiasFor(agentId: int): string =
  let dirs = ["north", "east", "south", "west"]
  dirs[agentId mod 4]

proc hasRoleGear(s: StateSnapshot, role: string): bool =
  case role
  of "miner": s.minerGear
  of "scout": s.scoutGear
  of "aligner": s.alignerGear
  of "scrambler": s.scramblerGear
  else: false

proc teamResourcesSufficient(ctx: NlankyContext): bool =
  let s = ctx.state
  s.teamCarbon > TeamSufficientThreshold and
    s.teamOxygen > TeamSufficientThreshold and
    s.teamGermanium > TeamSufficientThreshold and
    s.teamSilicon > TeamSufficientThreshold

proc moveToward(current, target: Location): NavAction =
  let dr = target.y - current.y
  let dc = target.x - current.x

  # Exactly adjacent bump into target.
  if dr == 1 and dc == 0:
    return naMoveSouth
  if dr == -1 and dc == 0:
    return naMoveNorth
  if dr == 0 and dc == 1:
    return naMoveEast
  if dr == 0 and dc == -1:
    return naMoveWest

  if abs(dr) >= abs(dc):
    if dr > 0: return naMoveSouth
    if dr < 0: return naMoveNorth
  if dc > 0: return naMoveEast
  if dc < 0: return naMoveWest
  naMoveNorth

proc deepestUnsatisfied(goal: Goal, ctx: var NlankyContext): Goal =
  for pre in goal.preconditions():
    if not pre.isSatisfied(ctx):
      return deepestUnsatisfied(pre, ctx)
  goal

proc evaluateGoals*(goals: seq[Goal], ctx: var NlankyContext): NavAction =
  for g in goals:
    if g.isSatisfied(ctx):
      continue
    let leaf = deepestUnsatisfied(g, ctx)
    let actOpt = leaf.execute(ctx)
    if actOpt.isNone:
      continue
    ctx.bb[].strs["_active_goal"] = g.name() & ">" & leaf.name()
    return actOpt.get()
  ctx.bb[].strs["_active_goal"] = "idle"
  naNoop

# ---------------------------------------------------------------------------
# Survive
# ---------------------------------------------------------------------------

type
  SurviveGoal* = ref object of Goal
    hpThreshold: int

method name*(g: SurviveGoal): string =
  "Survive"

proc isInSafeZone(ctx: NlankyContext): bool =
  let pos = ctx.state.position
  for (hpos, _) in ctx.map.find(kindContains="hub"):
    if manhattan(pos, hpos) <= JunctionAoeRange:
      return true
  for (jpos, _) in ctx.map.find(kindContains="junction", alignment=alCogs):
    if manhattan(pos, jpos) <= JunctionAoeRange:
      return true
  false

proc nearestSafeZone(ctx: NlankyContext): Option[Location] =
  let pos = ctx.state.position
  var bestDist = high(int)
  var best: Option[Location] = none(Location)
  for (hpos, _) in ctx.map.find(kindContains="hub"):
    let d = manhattan(pos, hpos)
    if d < bestDist:
      bestDist = d
      best = some(hpos)
  for (jpos, _) in ctx.map.find(kindContains="junction", alignment=alCogs):
    let d = manhattan(pos, jpos)
    if d < bestDist:
      bestDist = d
      best = some(jpos)
  best

method isSatisfied*(g: SurviveGoal, ctx: var NlankyContext): bool =
  discard g
  if isInSafeZone(ctx):
    return true
  let safePos = nearestSafeZone(ctx)
  if safePos.isNone:
    return ctx.state.hp > 20
  let dist = manhattan(ctx.state.position, safePos.get())
  let stepsToSafety = max(0, dist - JunctionAoeRange)
  let hpNeeded = stepsToSafety + HpSafetyMargin
  ctx.state.hp > hpNeeded

method execute*(g: SurviveGoal, ctx: var NlankyContext): Option[NavAction] =
  let safePos = nearestSafeZone(ctx)
  if safePos.isNone:
    return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))
  some(ctx.nav.getAction(ctx.state.position, safePos.get(), ctx.map, reachAdjacent=true))

# ---------------------------------------------------------------------------
# Gear
# ---------------------------------------------------------------------------

type
  GetGearGoal = ref object of Goal
    role: string
    stationType: string
    minStep: int
    costC: int
    costO: int
    costG: int
    costS: int
    reserve: int
    goalName: string

const
  GearMaxBumpsAtStation = 5
  GearMaxTotalAttempts = 80
  GearRetryInterval = 150

proc teamCanAffordGear(g: GetGearGoal, s: StateSnapshot): bool =
  (s.teamCarbon >= g.costC + g.reserve) and
    (s.teamOxygen >= g.costO + g.reserve) and
    (s.teamGermanium >= g.costG + g.reserve) and
    (s.teamSilicon >= g.costS + g.reserve)

method name*(g: GetGearGoal): string =
  g.goalName

method isSatisfied*(g: GetGearGoal, ctx: var NlankyContext): bool =
  if hasRoleGear(ctx.state, g.role):
    ctx.bb[].ints[g.goalName & "_total_attempts"] = 0
    ctx.bb[].ints[g.goalName & "_bump_count"] = 0
    return true

  if g.minStep > 0 and ctx.step < g.minStep:
    return true

  let giveupStep = ctx.bb[].ints.getOrDefault(g.goalName & "_giveup_step", -9999)
  if ctx.step - giveupStep < GearRetryInterval:
    return true

  if not teamCanAffordGear(g, ctx.state):
    return true

  false

method execute*(g: GetGearGoal, ctx: var NlankyContext): Option[NavAction] =
  let attemptsKey = g.goalName & "_total_attempts"
  let giveupKey = g.goalName & "_giveup_step"
  let bumpKey = g.goalName & "_bump_count"
  let lastDistKey = g.goalName & "_last_dist"

  var attempts = ctx.bb[].ints.getOrDefault(attemptsKey, 0) + 1
  ctx.bb[].ints[attemptsKey] = attempts

  if attempts > GearMaxTotalAttempts:
    ctx.bb[].ints[giveupKey] = ctx.step
    ctx.bb[].ints[attemptsKey] = 0
    ctx.bb[].ints[bumpKey] = 0
    return none(NavAction)

  let station = ctx.map.findNearest(ctx.state.position, kindContains=g.stationType, alignment=alCogs)

  if station.isNone:
    let stationArea = Location(x: SpawnCol, y: SpawnRow + 5)
    let areaDist = manhattan(ctx.state.position, stationArea)
    if areaDist > 2:
      return some(ctx.nav.getAction(ctx.state.position, stationArea, ctx.map, reachAdjacent=true))
    return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))

  let (stationPos, _) = station.get()
  let dist = manhattan(ctx.state.position, stationPos)

  let lastDist = ctx.bb[].ints.getOrDefault(lastDistKey, 999)
  ctx.bb[].ints[lastDistKey] = dist

  if dist <= 1:
    var bumps = ctx.bb[].ints.getOrDefault(bumpKey, 0) + 1
    ctx.bb[].ints[bumpKey] = bumps
    if bumps > GearMaxBumpsAtStation:
      ctx.bb[].ints[bumpKey] = 0
      ctx.nav.clearCache()
      return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))
    return some(moveToward(ctx.state.position, stationPos))

  ctx.bb[].ints[bumpKey] = 0
  if dist >= lastDist and attempts > 10:
    ctx.nav.clearCache()
  some(ctx.nav.getAction(ctx.state.position, stationPos, ctx.map, reachAdjacent=true))

type
  GetMinerGearGoal* = ref object of GetGearGoal

method name*(g: GetMinerGearGoal): string =
  g.goalName

proc newMinerGearGoal(): GetMinerGearGoal =
  # Miner gear has no reserve requirement (miners are the economy).
  GetMinerGearGoal(
    role: "miner",
    stationType: "miner",
    minStep: 0,
    costC: 1, costO: 1, costG: 3, costS: 1,
    reserve: 0,
    goalName: "GetMinerGear",
  )

type
  GetScoutGearGoal* = ref object of GetGearGoal

method name*(g: GetScoutGearGoal): string =
  g.goalName

proc newScoutGearGoal(): GetScoutGearGoal =
  GetScoutGearGoal(
    role: "scout",
    stationType: "scout",
    minStep: 0,
    costC: 1, costO: 1, costG: 1, costS: 3,
    reserve: 1,
    goalName: "GetScoutGear",
  )

type
  GetAlignerGearGoal* = ref object of GetGearGoal

method name*(g: GetAlignerGearGoal): string =
  g.goalName

proc newAlignerGearGoal(): GetAlignerGearGoal =
  GetAlignerGearGoal(
    role: "aligner",
    stationType: "aligner",
    minStep: 25,
    costC: 3, costO: 1, costG: 1, costS: 1,
    reserve: 1,
    goalName: "GetAlignerGear",
  )

type
  GetScramblerGearGoal* = ref object of GetGearGoal

method name*(g: GetScramblerGearGoal): string =
  g.goalName

proc newScramblerGearGoal(): GetScramblerGearGoal =
  GetScramblerGearGoal(
    role: "scrambler",
    stationType: "scrambler",
    minStep: 25,
    costC: 1, costO: 3, costG: 1, costS: 1,
    reserve: 1,
    goalName: "GetScramblerGear",
  )

# ---------------------------------------------------------------------------
# Miner: explore hub, pick resource, mine, deposit
# ---------------------------------------------------------------------------

const ResourceTypes = ["carbon", "oxygen", "germanium", "silicon"]

proc extractorRecentlyFailed(ctx: NlankyContext, pos: Location): bool =
  let failedStep = ctx.bb[].ints.getOrDefault("mine_failed_" & locKey(pos), -9999)
  ctx.step - failedStep < 30

type
  ExploreHubGoal* = ref object of Goal

method name*(g: ExploreHubGoal): string =
  "ExploreHub"

method isSatisfied*(g: ExploreHubGoal, ctx: var NlankyContext): bool =
  discard g
  var found = 0
  for r in ResourceTypes:
    if ctx.map.find(kind=r & "_extractor").len > 0:
      found += 1
  if found >= 4:
    return true
  if ctx.step > 15:
    return true
  false

method execute*(g: ExploreHubGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  let offsets = [(-5, -5), (-5, 5), (5, 5), (5, -5)]
  let idxKey = "_hub_corner_idx"
  var cornerIdx = ctx.bb[].ints.getOrDefault(idxKey, ctx.agentId mod 4)
  let (dr, dc) = offsets[cornerIdx]
  var target = Location(x: SpawnCol + dc, y: SpawnRow + dr)
  if manhattan(ctx.state.position, target) <= 2:
    cornerIdx = (cornerIdx + 1) mod 4
    ctx.bb[].ints[idxKey] = cornerIdx
    let (dr2, dc2) = offsets[cornerIdx]
    target = Location(x: SpawnCol + dc2, y: SpawnRow + dr2)
  some(ctx.nav.getAction(ctx.state.position, target, ctx.map, reachAdjacent=true))

type
  PickResourceGoal* = ref object of Goal

method name*(g: PickResourceGoal): string =
  "PickResource"

const
  PickReevaluateInterval = 50
  PickCriticalThreshold = 20
  PickAboveMeanThreshold = 0.20
  PickBelowMeanThreshold = 0.10
  PickMinMeanForBottleneck = 30.0

proc teamAmount(s: StateSnapshot, res: string): int =
  case res
  of "carbon": s.teamCarbon
  of "oxygen": s.teamOxygen
  of "germanium": s.teamGermanium
  of "silicon": s.teamSilicon
  else: 0

method isSatisfied*(g: PickResourceGoal, ctx: var NlankyContext): bool =
  discard g
  if teamResourcesSufficient(ctx) and ctx.state.cargoTotal() == 0:
    return true

  if not ctx.bb[].strs.hasKey("target_resource"):
    return false
  let currentTarget = ctx.bb[].strs.getOrDefault("target_resource", "")

  # Critical re-evaluation: any resource < 20 and not currently targeting it.
  var criticallyLow: seq[string] = @[]
  for r in ResourceTypes:
    if teamAmount(ctx.state, r) < PickCriticalThreshold:
      criticallyLow.add(r)
  if criticallyLow.len > 0 and currentTarget notin criticallyLow:
    # Switch to lowest critically-low resource.
    var lowest = criticallyLow[0]
    for r in criticallyLow:
      if teamAmount(ctx.state, r) < teamAmount(ctx.state, lowest):
        lowest = r
    ctx.bb[].strs.del("target_resource")
    ctx.bb[].strs["_bottleneck_target"] = lowest
    return false

  # Bottleneck switching.
  let meanCount =
    (ctx.state.teamCarbon + ctx.state.teamOxygen + ctx.state.teamGermanium + ctx.state.teamSilicon).float / 4.0
  if meanCount >= PickMinMeanForBottleneck:
    let targetAmount = teamAmount(ctx.state, currentTarget).float
    let aboveMeanLimit = meanCount * (1.0 + PickAboveMeanThreshold)
    let belowMeanLimit = meanCount * (1.0 - PickBelowMeanThreshold)
    if targetAmount > aboveMeanLimit:
      var bottlenecks: seq[string] = @[]
      for r in ResourceTypes:
        if teamAmount(ctx.state, r).float < belowMeanLimit:
          bottlenecks.add(r)
      if bottlenecks.len > 0:
        var lowestB = bottlenecks[0]
        for r in bottlenecks:
          if teamAmount(ctx.state, r) < teamAmount(ctx.state, lowestB):
            lowestB = r
        ctx.bb[].strs["_bottleneck_target"] = lowestB
        ctx.bb[].strs.del("target_resource")
        return false

  let lastPick = ctx.bb[].ints.getOrDefault("_target_resource_step", 0)
  if ctx.step - lastPick >= PickReevaluateInterval:
    ctx.bb[].strs.del("target_resource")
    return false

  true

method execute*(g: PickResourceGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  if ctx.bb[].strs.hasKey("_bottleneck_target"):
    let b = ctx.bb[].strs["_bottleneck_target"]
    ctx.bb[].strs.del("_bottleneck_target")
    ctx.bb[].strs["target_resource"] = b
    ctx.bb[].ints["_target_resource_step"] = ctx.step
    return none(NavAction)

  # Consider only resources with known usable extractors.
  var available: seq[(int, string)] = @[]
  for r in ResourceTypes:
    var usable = false
    for (pos, e) in ctx.map.find(kind=r & "_extractor"):
      if e.inventoryAmount == 0:
        continue
      if extractorRecentlyFailed(ctx, pos):
        continue
      usable = true
      break
    if usable:
      available.add((teamAmount(ctx.state, r), r))

  if available.len == 0:
    ctx.bb[].strs["target_resource"] = "carbon"
    ctx.bb[].ints["_target_resource_step"] = ctx.step
    return none(NavAction)

  var below: seq[(int, string)] = @[]
  for (amt, r) in available:
    if amt < TeamSufficientThreshold:
      below.add((amt, r))
  if below.len > 0:
    below.sort(proc(a, b: (int, string)): int = cmp(a[0], b[0]))
    ctx.bb[].strs["target_resource"] = below[0][1]
  else:
    available.sort(proc(a, b: (int, string)): int = cmp(a[0], b[0]))
    ctx.bb[].strs["target_resource"] = available[0][1]
  ctx.bb[].ints["_target_resource_step"] = ctx.step
  none(NavAction)

type
  DepositCargoGoal* = ref object of Goal

method name*(g: DepositCargoGoal): string =
  "DepositCargo"

const DepositMaxAttemptsPerDepot = 5

proc findCogsDepot(ctx: NlankyContext): Option[Location] =
  let pos = ctx.state.position

  proc recentlyFailed(p: Location): bool =
    let failedStep = ctx.bb[].ints.getOrDefault("deposit_failed_" & locKey(p), -9999)
    ctx.step - failedStep < 100

  var bestDist = high(int)
  var best: Option[Location] = none(Location)

  for (hpos, _) in ctx.map.find(kindContains="hub", alignment=alCogs):
    if recentlyFailed(hpos):
      continue
    let d = manhattan(pos, hpos)
    if d < bestDist:
      bestDist = d
      best = some(hpos)

  for (jpos, _) in ctx.map.find(kindContains="junction", alignment=alCogs):
    if recentlyFailed(jpos):
      continue
    let d = manhattan(pos, jpos)
    if d < bestDist:
      bestDist = d
      best = some(jpos)

  best

method isSatisfied*(g: DepositCargoGoal, ctx: var NlankyContext): bool =
  discard g
  let cargo = ctx.state.cargoTotal()

  if cargo == 0:
    if ctx.bb[].bools.getOrDefault("_depositing", false):
      ctx.bb[].bools["_depositing"] = false
    ctx.bb[].ints["_deposit_last_cargo"] = 0
    return true

  if ctx.bb[].bools.getOrDefault("_depositing", false):
    return false

  if cargo >= ctx.state.cargoCapacity():
    ctx.bb[].bools["_depositing"] = true
    return false

  let lastCargo = ctx.bb[].ints.getOrDefault("_deposit_last_cargo", 0)
  let cargoIncreased = cargo > lastCargo
  ctx.bb[].ints["_deposit_last_cargo"] = cargo
  if cargoIncreased:
    return true

  if ctx.bb[].bools.getOrDefault("_at_extractor", false):
    ctx.bb[].bools["_depositing"] = true
    return false

  true

method execute*(g: DepositCargoGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  if ctx.state.cargoTotal() == 0:
    ctx.bb[].bools["_depositing"] = false
    ctx.bb[].ints["_deposit_last_cargo"] = 0
    return none(NavAction)

  let prevCargo = ctx.bb[].ints.getOrDefault("prev_deposit_cargo", ctx.state.cargoTotal())
  let curCargo = ctx.state.cargoTotal()
  ctx.bb[].ints["prev_deposit_cargo"] = curCargo

  let depot = findCogsDepot(ctx)
  if depot.isNone:
    return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))
  let depotPos = depot.get()

  let dist = manhattan(ctx.state.position, depotPos)
  if dist <= 1:
    let attemptsKey = "deposit_attempts_" & locKey(depotPos)
    var attempts = ctx.bb[].ints.getOrDefault(attemptsKey, 0) + 1
    if curCargo < prevCargo:
      ctx.bb[].ints[attemptsKey] = 0
    else:
      ctx.bb[].ints[attemptsKey] = attempts
      if attempts > DepositMaxAttemptsPerDepot:
        ctx.bb[].ints["deposit_failed_" & locKey(depotPos)] = ctx.step
        ctx.bb[].ints[attemptsKey] = 0
        return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))
    return some(moveToward(ctx.state.position, depotPos))

  ctx.bb[].ints["deposit_attempts_" & locKey(depotPos)] = 0
  some(ctx.nav.getAction(ctx.state.position, depotPos, ctx.map, reachAdjacent=true))

type
  MineResourceGoal* = ref object of Goal

method name*(g: MineResourceGoal): string =
  "MineResource"

const MineMaxAttemptsPerExtractor = 5

proc findExtractor(ctx: NlankyContext, resource: string): Option[Location] =
  var bestDist = high(int)
  var best: Option[Location] = none(Location)
  for (pos, e) in ctx.map.find(kind=resource & "_extractor"):
    if e.inventoryAmount == 0:
      continue
    if extractorRecentlyFailed(ctx, pos):
      continue
    let d = manhattan(ctx.state.position, pos)
    if d < bestDist:
      bestDist = d
      best = some(pos)
  best

method isSatisfied*(g: MineResourceGoal, ctx: var NlankyContext): bool =
  discard g
  if teamResourcesSufficient(ctx) and ctx.state.cargoTotal() == 0:
    return true
  false

method execute*(g: MineResourceGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  let targetRes = ctx.bb[].strs.getOrDefault("target_resource", "carbon")

  let prevCargo = ctx.bb[].ints.getOrDefault("prev_cargo", 0)
  let curCargo = ctx.state.cargoTotal()
  ctx.bb[].ints["prev_cargo"] = curCargo

  var targetPos = findExtractor(ctx, targetRes)
  if targetPos.isNone:
    for r in ResourceTypes:
      if r == targetRes:
        continue
      targetPos = findExtractor(ctx, r)
      if targetPos.isSome:
        ctx.bb[].strs["target_resource"] = r
        ctx.bb[].ints["_target_resource_step"] = ctx.step
        break

  if targetPos.isNone:
    ctx.bb[].strs.del("target_resource")
    return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))

  let pos = targetPos.get()
  let dist = manhattan(ctx.state.position, pos)
  if dist <= 1:
    ctx.bb[].bools["_at_extractor"] = true
    let attemptsKey = "mine_attempts_" & locKey(pos)
    var attempts = ctx.bb[].ints.getOrDefault(attemptsKey, 0) + 1
    if curCargo > prevCargo:
      ctx.bb[].ints[attemptsKey] = 0
    else:
      ctx.bb[].ints[attemptsKey] = attempts
      if attempts > MineMaxAttemptsPerExtractor:
        ctx.bb[].ints["mine_failed_" & locKey(pos)] = ctx.step
        ctx.bb[].ints[attemptsKey] = 0
        ctx.bb[].strs.del("target_resource")
        ctx.bb[].bools["_at_extractor"] = false
        return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))
    return some(moveToward(ctx.state.position, pos))

  ctx.bb[].bools["_at_extractor"] = false
  some(ctx.nav.getAction(ctx.state.position, pos, ctx.map, reachAdjacent=true))

# ---------------------------------------------------------------------------
# Shared: hearts, emergency mine, fallback mine
# ---------------------------------------------------------------------------

type
  GetHeartsGoal* = ref object of Goal
    minHearts: int

method name*(g: GetHeartsGoal): string =
  "GetHearts"

const
  HeartMaxHubBumps = 5
  HeartCooldownSteps = 30
  HeartReserve = 1
  HeartElementCost = 1  # Each heart costs this many of EACH element

proc teamCanAffordHeart(s: StateSnapshot): bool =
  s.teamCarbon >= HeartElementCost + HeartReserve and
    s.teamOxygen >= HeartElementCost + HeartReserve and
    s.teamGermanium >= HeartElementCost + HeartReserve and
    s.teamSilicon >= HeartElementCost + HeartReserve

method isSatisfied*(g: GetHeartsGoal, ctx: var NlankyContext): bool =
  if ctx.state.heart >= g.minHearts:
    if ctx.bb[].ints.hasKey("_heart_hub_bumps"):
      ctx.bb[].ints.del("_heart_hub_bumps")
    if ctx.bb[].ints.hasKey("_heart_cooldown_until"):
      ctx.bb[].ints.del("_heart_cooldown_until")
    return true
  if not teamCanAffordHeart(ctx.state):
    return true
  let cooldownUntil = ctx.bb[].ints.getOrDefault("_heart_cooldown_until", 0)
  if ctx.step < cooldownUntil:
    return true
  false

method execute*(g: GetHeartsGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  let hub = ctx.map.findNearest(ctx.state.position, kindContains="hub", alignment=alCogs)
  if hub.isNone:
    return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))

  let (hubPos, _) = hub.get()
  let dist = manhattan(ctx.state.position, hubPos)
  if dist <= 1:
    var bumps = ctx.bb[].ints.getOrDefault("_heart_hub_bumps", 0) + 1
    ctx.bb[].ints["_heart_hub_bumps"] = bumps
    if bumps > HeartMaxHubBumps:
      ctx.bb[].ints["_heart_cooldown_until"] = ctx.step + HeartCooldownSteps
      ctx.bb[].ints["_heart_hub_bumps"] = 0
      return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))
    return some(moveToward(ctx.state.position, hubPos))

  ctx.bb[].ints["_heart_hub_bumps"] = 0
  some(ctx.nav.getAction(ctx.state.position, hubPos, ctx.map, reachAdjacent=true))

proc findDeposit(ctx: NlankyContext): Option[Location] =
  let pos = ctx.state.position
  var bestDist = high(int)
  var best: Option[Location] = none(Location)

  for (hpos, _) in ctx.map.find(kindContains="hub", alignment=alCogs):
    let d = manhattan(pos, hpos)
    if d < bestDist:
      bestDist = d
      best = some(hpos)
  for (jpos, _) in ctx.map.find(kindContains="junction", alignment=alCogs):
    let d = manhattan(pos, jpos)
    if d < bestDist:
      bestDist = d
      best = some(jpos)
  best

type
  EmergencyMineGoal* = ref object of Goal

method name*(g: EmergencyMineGoal): string =
  "EmergencyMine"

const
  EmergencyCriticalLow = 3
  EmergencyRecoveryThreshold = 8

method isSatisfied*(g: EmergencyMineGoal, ctx: var NlankyContext): bool =
  discard g
  if ctx.state.heart > 0:
    return true
  if not ctx.state.minerGear:
    return true

  let s = ctx.state
  let resources = [s.teamCarbon, s.teamOxygen, s.teamGermanium, s.teamSilicon]
  var minRes = resources[0]
  for r in resources:
    if r < minRes:
      minRes = r

  let inEmergency = ctx.bb[].bools.getOrDefault("_emergency_mine_active", false)
  if inEmergency:
    var allRecovered = true
    for r in resources:
      if r <= EmergencyRecoveryThreshold:
        allRecovered = false
        break
    if allRecovered:
      ctx.bb[].bools["_emergency_mine_active"] = false
      return true
    return false
  else:
    if minRes < EmergencyCriticalLow:
      ctx.bb[].bools["_emergency_mine_active"] = true
      return false
    return true

method execute*(g: EmergencyMineGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  let s = ctx.state
  var lowest = "carbon"
  for r in ResourceTypes:
    if teamAmount(s, r) < teamAmount(s, lowest):
      lowest = r

  var target: Option[Location] = none(Location)
  var bestDist = high(int)
  for (pos, e) in ctx.map.find(kind=lowest & "_extractor"):
    if e.inventoryAmount == 0 or extractorRecentlyFailed(ctx, pos):
      continue
    let d = manhattan(ctx.state.position, pos)
    if d < bestDist:
      bestDist = d
      target = some(pos)

  if target.isNone:
    for r in ResourceTypes:
      for (pos, e) in ctx.map.find(kind=r & "_extractor"):
        if e.inventoryAmount == 0 or extractorRecentlyFailed(ctx, pos):
          continue
        let d = manhattan(ctx.state.position, pos)
        if d < bestDist:
          bestDist = d
          target = some(pos)

  if target.isSome and bestDist <= 1:
    let lastCargo = ctx.bb[].ints.getOrDefault("_emg_last_cargo", -1)
    let cargoIncreased = (lastCargo != -1) and (ctx.state.cargoTotal() > lastCargo)
    ctx.bb[].ints["_emg_last_cargo"] = ctx.state.cargoTotal()
    if cargoIncreased and ctx.state.cargoTotal() < ctx.state.cargoCapacity():
      return some(moveToward(ctx.state.position, target.get()))

  if ctx.state.cargoTotal() > 0:
    let depot = findDeposit(ctx)
    if depot.isSome:
      let d = manhattan(ctx.state.position, depot.get())
      if d <= 1:
        return some(moveToward(ctx.state.position, depot.get()))
      return some(ctx.nav.getAction(ctx.state.position, depot.get(), ctx.map, reachAdjacent=true))

  if target.isSome:
    if bestDist <= 1:
      return some(moveToward(ctx.state.position, target.get()))
    return some(ctx.nav.getAction(ctx.state.position, target.get(), ctx.map, reachAdjacent=true))

  some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))

type
  FallbackMineGoal* = ref object of Goal

method name*(g: FallbackMineGoal): string =
  "FallbackMine"

method isSatisfied*(g: FallbackMineGoal, ctx: var NlankyContext): bool =
  discard g
  if teamResourcesSufficient(ctx) and ctx.state.cargoTotal() == 0:
    return true
  false

method execute*(g: FallbackMineGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  var bestDist = high(int)
  var best: Option[Location] = none(Location)
  for r in ResourceTypes:
    for (pos, e) in ctx.map.find(kind=r & "_extractor"):
      if e.inventoryAmount == 0 or extractorRecentlyFailed(ctx, pos):
        continue
      let d = manhattan(ctx.state.position, pos)
      if d < bestDist:
        bestDist = d
        best = some(pos)

  if best.isSome and bestDist <= 1:
    let lastCargo = ctx.bb[].ints.getOrDefault("_fb_last_cargo", -1)
    let cargoIncreased = (lastCargo != -1) and (ctx.state.cargoTotal() > lastCargo)
    ctx.bb[].ints["_fb_last_cargo"] = ctx.state.cargoTotal()
    if cargoIncreased and ctx.state.cargoTotal() < ctx.state.cargoCapacity():
      return some(moveToward(ctx.state.position, best.get()))

  if ctx.state.cargoTotal() > 0:
    let depot = findDeposit(ctx)
    if depot.isSome:
      let d = manhattan(ctx.state.position, depot.get())
      if d <= 1:
        return some(moveToward(ctx.state.position, depot.get()))
      return some(ctx.nav.getAction(ctx.state.position, depot.get(), ctx.map, reachAdjacent=true))

  if best.isSome:
    if bestDist <= 1:
      return some(moveToward(ctx.state.position, best.get()))
    return some(ctx.nav.getAction(ctx.state.position, best.get(), ctx.map, reachAdjacent=true))

  some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))

# ---------------------------------------------------------------------------
# Scout
# ---------------------------------------------------------------------------

type
  ExploreGoal* = ref object of Goal

method name*(g: ExploreGoal): string =
  "Explore"

method isSatisfied*(g: ExploreGoal, ctx: var NlankyContext): bool =
  discard g
  false

method execute*(g: ExploreGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))

# ---------------------------------------------------------------------------
# Aligner / Scrambler junction behavior
# ---------------------------------------------------------------------------

type
  AlignJunctionGoal* = ref object of Goal

method name*(g: AlignJunctionGoal): string =
  "AlignJunction"

const
  AlignMaxAttemptsPerTarget = 5
  AlignMaxNavStepsPerTarget = 40
  AlignCooldownSteps = 50
  AlignConnectivityRadius = 15
  AlignHubSearchRadius = 15

proc alignRecentlyFailed(ctx: NlankyContext, p: Location): bool =
  let failedStep = ctx.bb[].ints.getOrDefault("align_failed_" & locKey(p), -9999)
  ctx.step - failedStep < AlignCooldownSteps

proc sqDist(a: Location, b: Location): int =
  let dr = a.y - b.y
  let dc = a.x - b.x
  dr * dr + dc * dc

proc getHomeHub(ctx: NlankyContext): Option[Location] =
  let homeHubKey = "_align_home_hub"
  if ctx.bb[].locs.hasKey(homeHubKey):
    return some(ctx.bb[].locs[homeHubKey])

  var hubOpt = ctx.map.findNearest(ctx.state.position, kindContains="hub", alignment=alCogs)
  if hubOpt.isNone:
    # Fallback for partial/ambiguous tag observations: still anchor around the nearest hub.
    hubOpt = ctx.map.findNearest(ctx.state.position, kindContains="hub")
    if hubOpt.isNone:
      return none(Location)
  let (hubPos, _) = hubOpt.get()
  ctx.bb[].locs[homeHubKey] = hubPos
  some(hubPos)

proc buildConnectedCogsNodes(ctx: NlankyContext, homeHub: Location): seq[Location] =
  let r2 = AlignConnectivityRadius * AlignConnectivityRadius
  var connected: seq[Location] = @[homeHub]
  var pending: seq[Location] = @[]

  for (jpos, _) in ctx.map.find(kindContains="junction", alignment=alCogs):
    pending.add(jpos)

  var changed = true
  while changed:
    changed = false
    var nextPending: seq[Location] = @[]
    for jpos in pending:
      var joinsNetwork = false
      for cpos in connected:
        if sqDist(jpos, cpos) <= r2:
          joinsNetwork = true
          break
      if joinsNetwork:
        connected.add(jpos)
        changed = true
      else:
        nextPending.add(jpos)
    pending = nextPending

  connected

proc isConnectedToCogsNetwork(ctx: NlankyContext, p: Location): bool =
  let homeHubOpt = getHomeHub(ctx)
  if homeHubOpt.isNone:
    return false

  let connected = buildConnectedCogsNodes(ctx, homeHubOpt.get())
  let r2 = AlignConnectivityRadius * AlignConnectivityRadius
  for cpos in connected:
    if sqDist(p, cpos) <= r2:
      return true

  false

proc getAlignHubSearchTarget(ctx: var NlankyContext, homeHub: Location): Location =
  let offsets = [
    (-AlignHubSearchRadius, 0),
    (0, -AlignHubSearchRadius),
    (AlignHubSearchRadius, 0),
    (0, AlignHubSearchRadius),
    (-AlignHubSearchRadius div 2, -AlignHubSearchRadius div 2),
    (AlignHubSearchRadius div 2, -AlignHubSearchRadius div 2),
    (AlignHubSearchRadius div 2, AlignHubSearchRadius div 2),
    (-AlignHubSearchRadius div 2, AlignHubSearchRadius div 2),
  ]
  let key = "_align_hub_scan_idx"
  # Seed aligners across the 4 cardinal spokes first (agents 4..7 map to 0..3).
  var idx = ctx.bb[].ints.getOrDefault(key, ctx.agentId mod 4)
  var target = Location(x: homeHub.x + offsets[idx][1], y: homeHub.y + offsets[idx][0])
  if manhattan(ctx.state.position, target) <= 2:
    idx = (idx + 1) mod offsets.len
    ctx.bb[].ints[key] = idx
    target = Location(x: homeHub.x + offsets[idx][1], y: homeHub.y + offsets[idx][0])
  target

proc alignSearchAction(ctx: var NlankyContext): NavAction =
  let homeHubOpt = getHomeHub(ctx)
  if homeHubOpt.isSome:
    let target = getAlignHubSearchTarget(ctx, homeHubOpt.get())
    return ctx.nav.getAction(ctx.state.position, target, ctx.map, reachAdjacent=true)
  ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId))

proc findBestAlignableJunction(ctx: NlankyContext): Option[Location] =
  let pos = ctx.state.position
  var bestDist = high(int)
  var best: Option[Location] = none(Location)

  for (jpos, e) in ctx.map.find(kind="junction"):
    if e.alignment != alNone:
      continue
    if alignRecentlyFailed(ctx, jpos):
      continue
    if not isConnectedToCogsNetwork(ctx, jpos):
      continue

    let d = manhattan(pos, jpos)
    if d < bestDist:
      bestDist = d
      best = some(jpos)

  best

proc isAlignableTarget(ctx: NlankyContext, p: Location): bool =
  if p notin ctx.map.entities:
    return false
  let ent = ctx.map.entities[p]
  if ent.kind != "junction":
    return false
  if ent.alignment != alNone:
    return false
  if alignRecentlyFailed(ctx, p):
    return false
  if not isConnectedToCogsNetwork(ctx, p):
    return false
  true

proc findAdjacentAlignableJunction(ctx: NlankyContext): Option[Location] =
  let p = ctx.state.position
  let neighbors = [
    Location(x: p.x, y: p.y - 1),
    Location(x: p.x, y: p.y + 1),
    Location(x: p.x - 1, y: p.y),
    Location(x: p.x + 1, y: p.y),
  ]
  for npos in neighbors:
    if isAlignableTarget(ctx, npos):
      return some(npos)
  none(Location)

method isSatisfied*(g: AlignJunctionGoal, ctx: var NlankyContext): bool =
  discard g
  if not ctx.state.alignerGear:
    return true
  if ctx.state.heart < 1:
    return true
  false

method execute*(g: AlignJunctionGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  let navKey = "_align_nav_steps"
  let targetKey = "_align_nav_target"
  ctx.bb[].ints[navKey] = ctx.bb[].ints.getOrDefault(navKey, 0) + 1
  var navSteps = ctx.bb[].ints[navKey]

  var targetOpt = none(Location)
  let adjacent = findAdjacentAlignableJunction(ctx)
  if adjacent.isSome:
    targetOpt = adjacent
  if ctx.bb[].locs.hasKey(targetKey):
    let existingTarget = ctx.bb[].locs[targetKey]
    if targetOpt.isNone and isAlignableTarget(ctx, existingTarget):
      targetOpt = some(existingTarget)
  if targetOpt.isNone:
    targetOpt = findBestAlignableJunction(ctx)
  if targetOpt.isNone:
    ctx.bb[].ints[navKey] = 0
    return some(alignSearchAction(ctx))
  let target = targetOpt.get()

  let prevTarget = ctx.bb[].locs.getOrDefault(targetKey, Location(x: -9999, y: -9999))
  if prevTarget != target:
    ctx.bb[].ints[navKey] = 0
    navSteps = 0
  ctx.bb[].locs[targetKey] = target

  if navSteps > AlignMaxNavStepsPerTarget:
    ctx.bb[].ints["align_failed_" & locKey(target)] = ctx.step
    ctx.bb[].ints[navKey] = 0
    return some(alignSearchAction(ctx))

  let dist = manhattan(ctx.state.position, target)
  if dist <= 1:
    let attemptsKey = "align_attempts_" & locKey(target)
    var attempts = ctx.bb[].ints.getOrDefault(attemptsKey, 0) + 1
    ctx.bb[].ints[attemptsKey] = attempts
    if attempts > AlignMaxAttemptsPerTarget:
      ctx.bb[].ints["align_failed_" & locKey(target)] = ctx.step
      ctx.bb[].ints[attemptsKey] = 0
      return some(alignSearchAction(ctx))
    return some(moveToward(ctx.state.position, target))

  ctx.bb[].ints["align_attempts_" & locKey(target)] = 0
  some(ctx.nav.getAction(ctx.state.position, target, ctx.map, reachAdjacent=true))

type
  ScrambleJunctionGoal* = ref object of Goal

method name*(g: ScrambleJunctionGoal): string =
  "ScrambleJunction"

const
  ScrambleMaxAttemptsPerTarget = 5
  ScrambleMaxNavStepsPerTarget = 40
  ScrambleCooldownSteps = 50

proc scrambleRecentlyFailed(ctx: NlankyContext, p: Location): bool =
  let failedStep = ctx.bb[].ints.getOrDefault("scramble_failed_" & locKey(p), -9999)
  ctx.step - failedStep < ScrambleCooldownSteps

proc findBestEnemyJunction(ctx: NlankyContext): Option[Location] =
  let pos = ctx.state.position

  var enemies: seq[Location] = @[]
  for (jpos, e) in ctx.map.find(kindContains="junction", alignment=alClips):
    if not scrambleRecentlyFailed(ctx, jpos):
      enemies.add(jpos)
  if enemies.len == 0:
    return none(Location)

  var neutrals: seq[Location] = @[]
  for (jpos, e) in ctx.map.find(kindContains="junction"):
    if e.alignment == alNone:
      neutrals.add(jpos)

  var best: Option[Location] = none(Location)
  var bestScoreBlocked = low(int)
  var bestDist = high(int)
  for epos in enemies:
    var blocked = 0
    for npos in neutrals:
      if manhattan(epos, npos) <= JunctionAoeRange:
        blocked += 1
    let dist = manhattan(pos, epos)
    # Higher blocked is better; tie-break by distance.
    if blocked > bestScoreBlocked or (blocked == bestScoreBlocked and dist < bestDist):
      bestScoreBlocked = blocked
      bestDist = dist
      best = some(epos)
  best

method isSatisfied*(g: ScrambleJunctionGoal, ctx: var NlankyContext): bool =
  discard g
  if not ctx.state.scramblerGear:
    return true
  if ctx.state.heart < 1:
    return true
  false

method execute*(g: ScrambleJunctionGoal, ctx: var NlankyContext): Option[NavAction] =
  discard g
  let navKey = "_scramble_nav_steps"
  let targetKey = "_scramble_nav_target"
  ctx.bb[].ints[navKey] = ctx.bb[].ints.getOrDefault(navKey, 0) + 1
  var navSteps = ctx.bb[].ints[navKey]

  let targetOpt = findBestEnemyJunction(ctx)
  if targetOpt.isNone:
    ctx.bb[].ints[navKey] = 0
    return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))
  let target = targetOpt.get()

  let prevTarget = ctx.bb[].locs.getOrDefault(targetKey, Location(x: -9999, y: -9999))
  if prevTarget != target:
    ctx.bb[].ints[navKey] = 0
    navSteps = 0
  ctx.bb[].locs[targetKey] = target

  if navSteps > ScrambleMaxNavStepsPerTarget:
    ctx.bb[].ints["scramble_failed_" & locKey(target)] = ctx.step
    ctx.bb[].ints[navKey] = 0
    return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))

  let dist = manhattan(ctx.state.position, target)
  if dist <= 1:
    let attemptsKey = "scramble_attempts_" & locKey(target)
    var attempts = ctx.bb[].ints.getOrDefault(attemptsKey, 0) + 1
    ctx.bb[].ints[attemptsKey] = attempts
    if attempts > ScrambleMaxAttemptsPerTarget:
      ctx.bb[].ints["scramble_failed_" & locKey(target)] = ctx.step
      ctx.bb[].ints[attemptsKey] = 0
      return some(ctx.nav.explore(ctx.state.position, ctx.map, directionBias=directionBiasFor(ctx.agentId)))
    return some(moveToward(ctx.state.position, target))

  ctx.bb[].ints["scramble_attempts_" & locKey(target)] = 0
  some(ctx.nav.getAction(ctx.state.position, target, ctx.map, reachAdjacent=true))

# ---------------------------------------------------------------------------
# Stem
# ---------------------------------------------------------------------------

type
  SelectRoleGoal* = ref object of Goal
    selected: bool

method name*(g: SelectRoleGoal): string =
  "SelectRole"

method isSatisfied*(g: SelectRoleGoal, ctx: var NlankyContext): bool =
  discard ctx
  g.selected

method execute*(g: SelectRoleGoal, ctx: var NlankyContext): Option[NavAction] =
  # Simple distribution: 5 miners, rest aligners (mirrors Python).
  let role =
    if ctx.agentId < 5:
      "miner"
    else:
      "aligner"
  ctx.bb[].strs["selected_role"] = role
  ctx.bb[].strs["change_role"] = role
  g.selected = true
  some(naNoop)

# ---------------------------------------------------------------------------
# Commander Directive
# ---------------------------------------------------------------------------

const
  CmdMaxNavSteps = 40
  CmdMaxBumps = 5
  CmdCooldownSteps = 50

proc cmdRecentlyFailed(ctx: NlankyContext, prefix: string, p: Location): bool =
  let failedStep = ctx.bb[].ints.getOrDefault(prefix & "_failed_" & locKey(p), -9999)
  ctx.step - failedStep < CmdCooldownSteps

proc findVibeTaggedJunction(
  ctx: NlankyContext, vibe: string, wantAlignment: Alignment
): Option[Location] =
  ## Find nearest junction with the given vibe whose alignment matches.
  var bestDist = high(int)
  var best = none(Location)
  for pos, ent in ctx.map.entities:
    if not ent.kind.contains("junction"):
      continue
    if ent.vibe != vibe:
      continue
    if ent.alignment == wantAlignment:
      continue
    if cmdRecentlyFailed(ctx, "cmd_" & vibe, pos):
      continue
    let dist = manhattan(pos, ctx.state.position)
    if dist < bestDist:
      bestDist = dist
      best = some(pos)
  best

proc executeCommanderNav(
  ctx: var NlankyContext, prefix: string, targetOpt: Option[Location]
): Option[NavAction] =
  ## Shared navigate-and-bump logic for commander directives.
  let navKey = prefix & "_nav_steps"
  let targetKey = prefix & "_nav_target"
  ctx.bb[].ints[navKey] = ctx.bb[].ints.getOrDefault(navKey, 0) + 1
  var navSteps = ctx.bb[].ints[navKey]
  if targetOpt.isNone:
    ctx.bb[].ints[navKey] = 0
    return none(NavAction)
  let target = targetOpt.get()
  let prevTarget = ctx.bb[].locs.getOrDefault(targetKey, Location(x: -9999, y: -9999))
  if prevTarget != target:
    ctx.bb[].ints[navKey] = 0
    navSteps = 0
  ctx.bb[].locs[targetKey] = target
  if navSteps > CmdMaxNavSteps:
    ctx.bb[].ints[prefix & "_failed_" & locKey(target)] = ctx.step
    ctx.bb[].ints[navKey] = 0
    return none(NavAction)
  let dist = manhattan(ctx.state.position, target)
  if dist <= 1:
    let attemptsKey = prefix & "_attempts_" & locKey(target)
    var attempts = ctx.bb[].ints.getOrDefault(attemptsKey, 0) + 1
    ctx.bb[].ints[attemptsKey] = attempts
    if attempts > CmdMaxBumps:
      ctx.bb[].ints[prefix & "_failed_" & locKey(target)] = ctx.step
      ctx.bb[].ints[attemptsKey] = 0
      return none(NavAction)
    return some(moveToward(ctx.state.position, target))
  ctx.bb[].ints[prefix & "_attempts_" & locKey(target)] = 0
  some(ctx.nav.getAction(ctx.state.position, target, ctx.map, reachAdjacent=true))

# Commander Align: heart vibe on non-cogs junction → align it.

type
  CommanderAlignGoal* = ref object of Goal

method name*(g: CommanderAlignGoal): string =
  "CommanderAlign"

method preconditions*(g: CommanderAlignGoal): seq[Goal] =
  @[Goal(newAlignerGearGoal()), Goal(GetHeartsGoal(minHearts: 1))]

method isSatisfied*(g: CommanderAlignGoal, ctx: var NlankyContext): bool =
  findVibeTaggedJunction(ctx, "heart", alCogs).isNone

method execute*(g: CommanderAlignGoal, ctx: var NlankyContext): Option[NavAction] =
  executeCommanderNav(ctx, "cmd_heart",
    findVibeTaggedJunction(ctx, "heart", alCogs))

# Commander Scramble: scrambler vibe on non-neutral junction → scramble it.

type
  CommanderScrambleGoal* = ref object of Goal

method name*(g: CommanderScrambleGoal): string =
  "CommanderScramble"

method preconditions*(g: CommanderScrambleGoal): seq[Goal] =
  @[Goal(newScramblerGearGoal()), Goal(GetHeartsGoal(minHearts: 1))]

method isSatisfied*(g: CommanderScrambleGoal, ctx: var NlankyContext): bool =
  findVibeTaggedJunction(ctx, "scrambler", alCogs).isNone

method execute*(g: CommanderScrambleGoal, ctx: var NlankyContext): Option[NavAction] =
  executeCommanderNav(ctx, "cmd_scrambler",
    findVibeTaggedJunction(ctx, "scrambler", alCogs))

# Commander Mine: miner vibe on extractor → go mine it.

type
  CommanderMineGoal* = ref object of Goal

method name*(g: CommanderMineGoal): string =
  "CommanderMine"

method preconditions*(g: CommanderMineGoal): seq[Goal] =
  @[Goal(newMinerGearGoal())]

proc findMinerVibeTarget(ctx: NlankyContext): Option[Location] =
  var bestDist = high(int)
  var best = none(Location)
  for pos, ent in ctx.map.entities:
    if ent.vibe != "miner":
      continue
    if not ent.kind.contains("extractor"):
      continue
    if cmdRecentlyFailed(ctx, "cmd_miner", pos):
      continue
    let dist = manhattan(pos, ctx.state.position)
    if dist < bestDist:
      bestDist = dist
      best = some(pos)
  best

method isSatisfied*(g: CommanderMineGoal, ctx: var NlankyContext): bool =
  findMinerVibeTarget(ctx).isNone

method execute*(g: CommanderMineGoal, ctx: var NlankyContext): Option[NavAction] =
  executeCommanderNav(ctx, "cmd_miner", findMinerVibeTarget(ctx))

# Commander Scout: scout vibe on any object → walk to it.

type
  CommanderScoutGoal* = ref object of Goal

method name*(g: CommanderScoutGoal): string =
  "CommanderScout"

proc findScoutVibeTarget(ctx: NlankyContext): Option[Location] =
  var bestDist = high(int)
  var best = none(Location)
  for pos, ent in ctx.map.entities:
    if ent.vibe != "scout":
      continue
    if cmdRecentlyFailed(ctx, "cmd_scout", pos):
      continue
    let dist = manhattan(pos, ctx.state.position)
    if dist < bestDist:
      bestDist = dist
      best = some(pos)
  best

method isSatisfied*(g: CommanderScoutGoal, ctx: var NlankyContext): bool =
  findScoutVibeTarget(ctx).isNone

method execute*(g: CommanderScoutGoal, ctx: var NlankyContext): Option[NavAction] =
  executeCommanderNav(ctx, "cmd_scout", findScoutVibeTarget(ctx))

# ---------------------------------------------------------------------------
# Goal lists
# ---------------------------------------------------------------------------

proc makeGoalList*(role: string): seq[Goal] =
  case role
  of "miner":
    @[
      Goal(SurviveGoal(hpThreshold: 15)),
      Goal(EmergencyMineGoal()),
      Goal(CommanderAlignGoal()),
      Goal(CommanderScrambleGoal()),
      Goal(CommanderMineGoal()),
      Goal(CommanderScoutGoal()),
      Goal(newMinerGearGoal()),
      Goal(ExploreHubGoal()),
      Goal(PickResourceGoal()),
      Goal(DepositCargoGoal()),
      Goal(MineResourceGoal()),
    ]
  of "scout":
    @[
      Goal(SurviveGoal(hpThreshold: 50)),
      Goal(EmergencyMineGoal()),
      Goal(CommanderAlignGoal()),
      Goal(CommanderScrambleGoal()),
      Goal(CommanderMineGoal()),
      Goal(CommanderScoutGoal()),
      Goal(newScoutGearGoal()),
      Goal(ExploreGoal()),
    ]
  of "aligner":
    @[
      Goal(SurviveGoal(hpThreshold: 50)),
      Goal(EmergencyMineGoal()),
      Goal(CommanderAlignGoal()),
      Goal(CommanderScrambleGoal()),
      Goal(CommanderMineGoal()),
      Goal(CommanderScoutGoal()),
      Goal(newAlignerGearGoal()),
      Goal(GetHeartsGoal(minHearts: 1)),
      Goal(AlignJunctionGoal()),
      Goal(FallbackMineGoal()),
    ]
  of "scrambler":
    @[
      Goal(SurviveGoal(hpThreshold: 30)),
      Goal(EmergencyMineGoal()),
      Goal(CommanderAlignGoal()),
      Goal(CommanderScrambleGoal()),
      Goal(CommanderMineGoal()),
      Goal(CommanderScoutGoal()),
      Goal(newScramblerGearGoal()),
      Goal(GetHeartsGoal(minHearts: 1)),
      Goal(ScrambleJunctionGoal()),
      Goal(FallbackMineGoal()),
    ]
  of "stem":
    @[
      Goal(SurviveGoal(hpThreshold: 20)),
      Goal(EmergencyMineGoal()),
      Goal(CommanderAlignGoal()),
      Goal(CommanderScrambleGoal()),
      Goal(CommanderMineGoal()),
      Goal(CommanderScoutGoal()),
      Goal(SelectRoleGoal(selected: false)),
    ]
  else:
    @[]
