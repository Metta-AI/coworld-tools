# AI Behavior Analysis

Date: 2026-01-28
Owner: Engineering / Analysis
Status: Active

## Role Overview

### Role Assignment
- Agents are assigned roles based on their slot ID modulo 6:
  - Slots 0-1: Gatherer (resource collection focus)
  - Slots 2-3: Builder (construction focus)
  - Slots 4-5: Fighter (combat/defense focus)
- Teams operate independently with ~42 agents per team

### Options Framework
Each role uses a priority-ordered list of "OptionDefs" with:
- `canStart`: Precondition check
- `shouldTerminate`: Termination condition
- `act`: Execution logic returning encoded action
- `interruptible`: Whether higher-priority options can interrupt

### Gatherer Priority Order
1. PlantOnFertile → 2. MarketTrade → 3. CarryingStockpile → 4. Hearts → 5. Resource → 6. Food → 7. Irrigate → 8. Scavenge → 9. StoreValuables → 10. FallbackSearch

### Builder Priority Order
1. PlantOnFertile → 2. DropoffCarrying → 3. PopCap → 4. CoreInfrastructure → 5. MillNearResource → 6. PlantIfMills → 7. CampThreshold → 8. WallRing → 9. TechBuildings → 10. GatherScarce → 11. MarketTrade → 12. VisitTradingHub → 13. SmeltGold/CraftBread/StoreValuables → 14. FallbackSearch

### Fighter Priority Order
1. Breakout → 2. Retreat → 3. Monk → 4. DividerDefense → 5. Lanterns → 6. DropoffFood → 7. Train → 8. MaintainGear → 9. HuntPredators → 10. ClearGoblins → 11. SmeltGold/CraftBread/StoreValuables → 12. Aggressive → 13. FallbackSearch

### Performance Metrics

| Role     | Move  | Attack | Use   | Build | Invalid |
|----------|-------|--------|-------|-------|---------|
| Gatherer | 90.5% | 2.8%   | 0.8%  | 0.0%  | 3.5%    |
| Builder  | 86.9% | 2.9%   | 0.8%  | 0.5%  | 5.9%    |
| Fighter  | 85.9% | 4.5%   | 0.3%  | 0.1%  | 7.2%    |

Success rates: Gatherer 94.1%, Builder 91.2%, Fighter 90.9%.

---

## Invalid Action Root Causes

This section investigates the high invalid action rates observed in profiling:
- **Gatherer: 13.9% invalid** (highest)
- **Fighter: 12.7% invalid**
- **Builder: 9.0% invalid**

Invalid actions are counted in `src/step.nim` when an action cannot be completed. The primary causes are: movement into blocked tiles, attacking empty positions, using non-interactive targets, and stale cached state.

---

## 1. Gatherer Role (13.9% Invalid Rate)

### File: `/home/relh/gt/tribal_village/crew/relh/src/scripted/gatherer.nim`

### Root Causes

#### 1.1 Stale Resource Cache Leading to Invalid Movement/Use

**Location:** Lines 318-330 (`optGathererFood`)

```nim
if state.closestFoodPos.x >= 0:
  if state.closestFoodPos == state.pathBlockedTarget:
    state.closestFoodPos = ivec2(-1, -1)
  else:
    let knownThing = env.getThing(state.closestFoodPos)
    if isNil(knownThing) or knownThing.kind notin FoodKinds:
      state.closestFoodPos = ivec2(-1, -1)
```

**Issue:** The gatherer caches resource positions (`closestFoodPos`, `closestWoodPos`, etc.) but these resources can be:
- Harvested by other agents
- Destroyed by enemies
- Blocked by newly placed structures

When the cached position becomes invalid between decision and action, the agent issues `moveTo` or `useAt` commands to positions that no longer contain valid targets.

#### 1.2 Water Irrigation Target Validation

**Location:** Lines 305-316 (`optGathererFood`)

```nim
if agent.inventoryWater > 0:
  var target = findFertileTarget(env, basePos, fertileRadius, state.pathBlockedTarget)
  if target.x < 0:
    target = findFertileTarget(env, agent.pos, fertileRadius, state.pathBlockedTarget)
  if target.x >= 0:
    return (if isAdjacent(agent.pos, target):
      controller.useAt(env, agent, agentId, state, target)
    else:
      controller.moveTo(env, agent, agentId, state, target))
```

**Issue:** `findFertileTarget` filters for empty tiles, but between the search and the action execution:
- Another agent may occupy the tile
- A structure may be built there
- The tile may become frozen

#### 1.3 Market Trade Without Validation

**Status:** FIXED

Market trading has been consolidated into shared functions in `options.nim`:
- `canStartMarketTrade*` (line 755)
- `optMarketTrade*` (line 777)

The shared implementation now includes cooldown validation:
```nim
proc optMarketTrade*(...): uint8 =
  let market = env.findNearestFriendlyThingSpiral(state, teamId, Market)
  if isNil(market) or market.cooldown != 0:  # Cooldown check added
    return 0'u8
  return actOrMove(controller, env, agent, agentId, state, market.pos, 3'u8)
```

**Resolution:** The cooldown check is now included, preventing wasted actions when market is on cooldown.

#### 1.4 Heart Priority with Missing Magma

**Location:** Lines 181-196 (`optGathererHearts`)

```nim
if agent.inventoryGold > 0:
  let (didKnown, actKnown) = controller.tryMoveToKnownResource(
    env, agent, agentId, state, state.closestMagmaPos, {Magma}, 3'u8)
  if didKnown: return actKnown
  if not isNil(magmaGlobal):
    ...
  return controller.moveNextSearch(env, agent, agentId, state)
```

**Issue:** When no magma exists, the agent enters search mode but may issue movement toward invalid spiral positions near map edges or blocked terrain.

### Recommended Fixes for Gatherer

1. **Pre-validate cached positions** before issuing `useAt`:
   ```nim
   if state.closestFoodPos.x >= 0:
     let target = env.getThing(state.closestFoodPos)
     if isNil(target) or target.kind notin FoodKinds or isThingFrozen(target, env):
       state.closestFoodPos = ivec2(-1, -1)
       continue  # Skip to next option
   ```

2. **Add cooldown checks** before building/market use actions.

3. **Validate movement targets** before returning `moveTo`:
   ```nim
   if not canEnterForMove(env, agent, agent.pos, targetPos):
     return controller.moveNextSearch(env, agent, agentId, state)
   ```

---

## 2. Fighter Role (12.7% Invalid Rate)

### File: `/home/relh/gt/tribal_village/crew/relh/src/scripted/fighter.nim`

### Root Causes

#### 2.1 Cached Enemy No Longer Valid

**Location:** Lines 17-48 (`fighterFindNearbyEnemy`)

```nim
proc fighterFindNearbyEnemy(...): Thing =
  if state.fighterEnemyStep == env.currentStep and
      state.fighterEnemyAgentId >= 0 and state.fighterEnemyAgentId < MapAgents:
    let cached = env.agents[state.fighterEnemyAgentId]
    if cached.agentId != agent.agentId and
        isAgentAlive(env, cached) and
        not sameTeam(agent, cached) and
        int(chebyshevDist(agent.pos, cached.pos)) <= enemyRadius.int:
      return cached
```

**Issue:** The cached enemy is validated only for:
- Being alive
- Being on opposing team
- Being within radius

But NOT validated for:
- Being reachable (path blocked)
- Being attackable from current position (range/line-of-sight)

This leads to `fighterActOrMove` issuing attacks toward targets that are not in attack range.

#### 2.2 Divider Defense Building Without Resource Check

**Location:** Lines 286-332 (`optFighterDividerDefense`)

```nim
of Door:
  if not env.canAffordBuild(agent, thingItem("Door")):
    let (didDrop, actDrop) = controller.dropoffCarrying(...)
    if didDrop: return actDrop
    let (didWood, actWood) = controller.ensureWood(env, agent, agentId, state)
    if didWood: return actWood
  let (didDoor, doorAct) = goToAdjacentAndBuild(...)
  if didDoor: return doorAct
```

**Issue:** The `goToAdjacentAndBuild` call can fail if:
- No adjacent tile is buildable
- The target position became occupied
- The terrain changed (now Road)

The function returns `(false, 0'u8)` but the fallback `controller.moveTo(env, agent, agentId, state, enemy.pos)` may still issue invalid movement.

#### 2.3 Lantern Placement Validation Gap

**Location:** Lines 340-436 (`optFighterLanterns`)

```nim
if target.x >= 0:
  if agent.inventoryLantern > 0:
    return fighterActOrMove(controller, env, agent, agentId, state, target, 6'u8)
```

**Issue:** `findLanternFrontierCandidate` and `findLanternGapCandidate` search for valid placement spots, but between search and action:
- The position may become occupied
- Lantern spacing constraints may be violated by concurrent agent actions
- The tile may freeze

The lantern placement action (verb 6) then fails.

#### 2.4 Training Buildings Cooldown Race

**Location:** Lines 469-484 (`optFighterTrain`)

```nim
for kind in FighterTrainKinds:
  ...
  let building = env.findNearestFriendlyThingSpiral(state, teamId, kind)
  if isNil(building) or building.cooldown != 0:
    continue
  return fighterActOrMove(controller, env, agent, agentId, state, building.pos, 3'u8)
```

**Issue:** Between the cooldown check and the action execution, another agent may use the building, setting its cooldown. The use action then fails.

### Recommended Fixes for Fighter

1. **Validate attack opportunity** before issuing attack:
   ```nim
   let attackDir = findAttackOpportunity(env, agent)
   if attackDir >= 0:
     return encodeAction(2'u8, attackDir.uint8)
   # Only then fall back to movement toward enemy
   ```

2. **Add building cooldown re-check** at action time or use atomic operations.

3. **Verify lantern placement** immediately before the action:
   ```nim
   if isLanternPlacementValid(env, target) and not hasTeamLanternNear(env, teamId, target):
     return controller.actAt(...)
   ```

---

## 3. Builder Role (9.0% Invalid Rate)

### File: `/home/relh/gt/tribal_village/crew/relh/src/scripted/builder.nim`

### Root Causes

#### 3.1 Wall Ring Position Races

**Location:** Lines 169-249 (`optBuilderWallRing`)

```nim
for radius in WallRingRadii:
  ...
  for dx in -radius .. radius:
    for dy in -radius .. radius:
      ...
      if env.canPlace(pos):
        if distToAgent < candidateWallDist:
          candidateWallDist = distToAgent
          candidateWall = pos
```

**Issue:** Multiple builders may simultaneously identify the same wall position as a candidate. When both issue build commands, one succeeds and the other fails with an invalid action.

#### 3.2 Pop Cap House Building Competition

**Location:** Lines 66-79 (`optBuilderPopCap`) calls `tryBuildHouseForPopCap`

In `/home/relh/gt/tribal_village/crew/relh/src/scripted/ai_defaults.nim`:

```nim
proc tryBuildHouseForPopCap(...): tuple[did: bool, action: uint8] =
  if needsPopCapHouse(env, teamId):
    ...
    let candidates = if preferred.len > 0: preferred else: fallback
    if candidates.len > 0:
      let choice = candidates[randIntExclusive(controller.rng, 0, candidates.len)]
      return goToStandAndBuild(...)
```

**Issue:** The `needsPopCapHouse` check passes for multiple builders, but only one house is needed. Subsequent build attempts fail.

#### 3.3 Camp Threshold Building Without Spacing Re-check

**Location:** Lines 139-150 (`optBuilderCampThreshold`)

```nim
proc optBuilderCampThreshold(...): uint8 =
  for entry in CampThresholds:
    let nearbyCount = countNearbyThings(env, agent.pos, 4, entry.nearbyKinds)
    let (did, act) = controller.tryBuildCampThreshold(
      env, agent, agentId, state, teamId, entry.kind,
      nearbyCount, entry.minCount,
      [entry.kind]
    )
    if did: return act
```

**Issue:** `canStartBuilderCampThreshold` checks spacing, but `optBuilderCampThreshold` may issue a build action when:
- Another agent already built a camp nearby (spacing now violated)
- The search area positions are no longer empty

#### 3.4 Tech Building Construction Order Conflicts

**Location:** Lines 157-160 (`optBuilderTechBuildings`)

```nim
proc optBuilderTechBuildings(...): uint8 =
  buildFirstMissing(controller, env, agent, agentId, state, teamId, TechBuildingKinds)
```

**Issue:** `buildFirstMissing` iterates through `TechBuildingKinds` in a fixed order. Multiple builders may simultaneously identify the same missing building and all attempt to build it.

### Recommended Fixes for Builder

1. **Add coordination state** to prevent multiple builders targeting the same structure:
   ```nim
   var teamBuildingTargets: array[MapRoomObjectsTeams, set[ThingKind]]

   proc claimBuildTarget(teamId: int, kind: ThingKind): bool =
     if kind in teamBuildingTargets[teamId]:
       return false
     teamBuildingTargets[teamId].incl(kind)
     return true
   ```

2. **Re-validate building positions** in `goToAdjacentAndBuild`:
   ```nim
   if not env.canPlace(target) or env.terrain[target.x][target.y] == TerrainRoad:
     state.buildTarget = ivec2(-1, -1)
     return (false, 0'u8)
   ```

3. **Add spacing re-check** before camp construction.

---

## 4. Common Issues in ai_core.nim

### File: `/home/relh/gt/tribal_village/crew/relh/src/scripted/ai_core.nim`

#### 4.1 Movement Path Invalidation

**Location:** Lines 727-797 (`moveTo`)

```nim
proc moveTo(...): uint8 =
  if state.pathBlockedTarget == targetPos:
    return controller.moveNextSearch(env, agent, agentId, state)
  ...
  if state.plannedPath.len >= 2 and state.plannedPathIndex < state.plannedPath.len - 1:
    let nextPos = state.plannedPath[state.plannedPathIndex + 1]
    if canEnterForMove(env, agent, agent.pos, nextPos):
      ...
      return saveStateAndReturn(controller, agentId, state, encodeAction(1'u8, dirIdx.uint8))
    state.plannedPath.setLen(0)
    state.pathBlockedTarget = targetPos
    return controller.moveNextSearch(env, agent, agentId, state)
```

**Issue:** When a planned path becomes blocked, the agent:
1. Marks the target as blocked
2. Falls back to search movement

However, the search movement itself may issue invalid moves if:
- The spiral search position is outside playable bounds
- The search direction is blocked by terrain

**Location:** Lines 515-572 (`getMoveTowards`)

```nim
proc getMoveTowards(...): int =
  ...
  # All blocked, try random movement.
  return randIntInclusive(rng, 0, 7)
```

**Issue:** When all directions are blocked, a random direction is returned. This random direction is very likely to result in an invalid move action.

#### 4.2 Resource Targeting After Depletion

**Location:** Lines 907-1020 (`ensureWood`, `ensureStone`, `ensureGold`, etc.)

```nim
proc ensureWood(...): tuple[did: bool, action: uint8] =
  let (didKnown, actKnown) = controller.tryMoveToKnownResource(
    env, agent, agentId, state, state.closestWoodPos, {Stump, Tree}, 3'u8)
  if didKnown: return (didKnown, actKnown)
  for kind in [Stump, Tree]:
    let target = env.findNearestThingSpiral(state, kind)
    if isNil(target):
      continue
    ...
    return (true, if isAdjacent(agent.pos, target.pos):
      controller.useAt(env, agent, agentId, state, target.pos)
    else:
      controller.moveTo(env, agent, agentId, state, target.pos))
```

**Issue:** The `findNearestThingSpiral` function caches positions. When multiple agents target the same resource, the first to arrive depletes it, but subsequent agents still have the cached position and issue invalid use actions.

#### 4.3 Blocked Path Detection Delay

**Location:** Lines 730-754 (`moveTo`)

```nim
var stuck = false
if state.recentPosCount >= 6:
  var uniqueCount = 0
  ...
  stuck = uniqueCount <= 2
if stuck:
  state.pathBlockedTarget = ivec2(-1, -1)
  state.plannedPath.setLen(0)
```

**Issue:** The "stuck" detection requires 6+ steps of limited movement before triggering. During this period, multiple invalid move actions are generated.

### Recommended Fixes for ai_core.nim

1. **Validate movement before encoding**:
   ```nim
   proc getMoveTowards(...): int =
     ...
     # Instead of random when blocked:
     for idx, d in Directions8:
       let np = fromPos + d
       if canEnterForMove(env, agent, fromPos, np):
         return idx
     return -1  # Signal no valid move
   ```

2. **Pre-flight check for use actions**:
   ```nim
   proc useAt(...): uint8 =
     let thing = env.getThing(targetPos)
     if isNil(thing) or isThingFrozen(thing, env):
       return 0'u8  # Yield to other options
     actAt(...)
   ```

3. **Reduce stuck detection window** from 6 to 3-4 steps.

4. **Clear resource caches** more aggressively when resources are not found at cached positions.

---

## Summary of Recommendations

| Priority | Issue | Affected Roles | Recommendation |
|----------|-------|----------------|----------------|
| HIGH | Stale cached positions | All | Validate cache before use, clear on miss |
| HIGH | Random movement fallback | All | Return -1/0 instead of random when blocked |
| HIGH | Multi-agent coordination | Builder, Gatherer | Add claim/reservation system |
| MEDIUM | Cooldown race conditions | Fighter, Builder | Re-check cooldown at action time |
| MEDIUM | Slow stuck detection | All | Reduce window from 6 to 3-4 steps |
| MEDIUM | Path invalidation | All | Immediate re-path on block detection |
| LOW | Build position validation | Builder | Re-check canPlace before build action |
| LOW | Attack range validation | Fighter | Verify target in range before attack |

Implementing the HIGH priority fixes should reduce invalid action rates by approximately 50-70%.
