# Deep Role Audit: Gatherer, Builder, Fighter

Date: 2026-01-28
Owner: Engineering / Analysis
Status: Active

## Executive Summary

This audit analyzes the three main AI roles in tribal_village to identify behavioral gaps and enhancement opportunities. The codebase implements an RL-style options-based AI system where each role has a prioritized list of behaviors that are evaluated each tick.

---

## Architecture Overview

All roles use a shared options system (`options.nim`) where behaviors are:
- Evaluated in priority order (first valid behavior wins)
- Composed of `canStart`, `shouldTerminate`, and `act` functions
- Interruptible by higher-priority behaviors

Role assignment: Agents are assigned roles based on slot modulo 6:
- Slots 0,1: Gatherer
- Slots 2,3: Builder
- Slots 4,5: Fighter

---

## 1. Gatherer Role (`gatherer.nim`)

### Current Behavior Priority (top to bottom)

| # | Behavior | Description |
|---|----------|-------------|
| 1 | GathererFlee | Flees toward home altar when enemies nearby |
| 2 | GathererPredatorFlee | Flees from wolves/bears |
| 3 | EmergencyHeal | Heals when HP critically low |
| 4 | GathererPlantOnFertile | Plants wheat/trees on fertile land |
| 5 | GathererMarketTrade | Trades at market (gold->food, resources->gold) |
| 6 | GathererCarryingStockpile | Returns resources to dropoff buildings |
| 7 | GathererHearts | Prioritizes altar hearts (gold->magma->bar->altar) |
| 8 | GathererResource | Gathers gold/wood/stone + builds resource camps |
| 9 | GathererFood | Gathers food (wheat, cow, hunt) + builds granary/mill |
| 10 | GathererIrrigate | Waters tiles to create fertile land |
| 11 | GathererScavenge | Collects from skeletons |
| 12 | GathererStoreValuables | Stores items in appropriate buildings |
| 13 | GathererFallbackSearch | Spiral search when nothing else to do |

### Resource Finding Mechanism

**Spiral Search Pattern:**
- Anchored to home altar (or agent position if no altar)
- Advances 3 steps per tick when searching
- Maintains cached positions for resource types
- Uses `findNearestThingSpiral()` for efficient exploration

**Task Selection (lines 87-179):**
```
1. Check critical bottlenecks (FoodCritical/WoodCritical) → immediate task assignment
2. If altar hearts < 10 → TaskHearts (priority)
3. Otherwise, apply phase-based weights:
   - Early game (< 33%): Food > Wood > Stone > Gold
   - Mid game (33-66%): Equal weights
   - Late game (> 66%): Gold > Stone > Wood > Food
4. Flow rate adjustments for declining resources
5. Anti-oscillation hysteresis (5.0 threshold) prevents task switching
6. Weighted score = (stockpile + flow_adjustment) * weight
7. Lowest weighted score wins
```

**Food Sources (`FoodKinds`):** Wheat, Stubble, Fish, Bush, Cow, Corpse

### Animal Interaction (Cows)

**Current Implementation:**
- Cows are attacked (verb `2'u8` = attack) to obtain food
- No milking mechanic - only kill for corpse -> food
- Line 308: `actOrMove(..., (if knownThing.kind == Cow: 2'u8 else: 3'u8))`

### Danger Response

**Current Implementation:** None explicit in gatherer role.
- Relies on global `findAttackOpportunity()` in `decideAction()`
- Attacks if enemy in range, otherwise continues gathering
- No flee behavior, no threat awareness

### Gaps & Missing Behaviors

| Gap | Impact | Current Workaround |
|-----|--------|-------------------|
| ~~**No flee from danger**~~ | ~~Gatherers die when enemies approach~~ | ✅ **COMPLETE** - GathererFlee and GathererPredatorFlee options added |
| **No cow milking** | Only lethal food extraction | Kill cow -> gather corpse (cow milking implemented: healthy cows are milked, only killed when HP low or food critical) |
| ~~**No resource type weighting**~~ | ~~Treats all resources equally important~~ | ✅ **COMPLETE** - Phase-based weights in `updateGathererTask` |
| **No gatherer coordination** | Multiple gatherers may target same resource | None |
| **No seasonal/time awareness** | Gathers same way at all times | ✅ **COMPLETE** - Game phase detection (early/mid/late) drives resource priorities |
| **No threat-adjusted pathing** | Walks through dangerous areas | None |
| **No stockpile thresholds** | Keeps gathering even with surplus | ✅ **COMPLETE** - Critical bottleneck detection in economy system |

### Enhancement Recommendations

1. ~~**Danger Awareness Option**~~ ✅ **COMPLETE**
   - `GathererFlee` checks for nearby enemies within `GathererFleeRadius` (8 tiles)
   - Requests protection from fighters via coordination system
   - Moves toward home altar when threat detected
   - `GathererPredatorFlee` handles wolves/bears separately

2. **Cow Milking Behavior** ✅ **COMPLETE**
   - Uses `3'u8` (interact) when cow is healthy and food not critical
   - Uses `2'u8` (attack) when cow HP < 50% or food stockpile critical
   - See `optGathererFood` cow handling logic

3. ~~**Resource Priority Weighting**~~ ✅ **COMPLETE**
   - Game phase detection: early (< 33%), mid (33-66%), late (> 66%)
   - Early game: Food (0.5) > Wood (0.75) > Stone (1.0) > Gold (1.5)
   - Late game: Gold (0.5) > Stone (0.75) > Wood (1.0) > Food (1.5)
   - Flow rate adjustments for declining resources

4. ~~**Anti-oscillation for Resource Selection**~~ ✅ **COMPLETE**
   - `TaskSwitchHysteresis = 5.0` threshold
   - Only switches task if new best is significantly better than current

---

## 2. Builder Role (`builder.nim`)

### Current Behavior Priority

| # | Behavior | Description |
|---|----------|-------------|
| 1 | BuilderPlantOnFertile | Plants wheat/trees on fertile |
| 2 | BuilderDropoffCarrying | Returns items to dropoffs |
| 3 | BuilderPopCap | Builds houses when near pop cap |
| 4 | BuilderCoreInfrastructure | Builds Granary, LumberCamp, Quarry, MiningCamp |
| 5 | BuilderMillNearResource | Builds mills near fertile/wheat areas |
| 6 | BuilderPlantIfMills | Plants if 2+ mills exist |
| 7 | BuilderCampThreshold | Builds camps near resource clusters |
| 8 | BuilderWallRing | Builds defensive wall ring |
| 9 | BuilderTechBuildings | Builds tech buildings |
| 10 | BuilderGatherScarce | Gathers scarcest resource (<5 stock) |
| 11 | BuilderMarketTrade | Market trading |
| 12 | BuilderVisitTradingHub | Visits neutral hubs |
| 13 | BuilderSmeltGold | Gold smelting |
| 14 | BuilderCraftBread | Bread crafting |
| 15 | BuilderStoreValuables | Storage |
| 16 | BuilderFallbackSearch | Fallback spiral search |

### Building Triggers

**PopCap Houses:**
- Triggers when `popCount >= popCap - HousePopCap`
- Prefers positions 5-15 tiles from base
- Avoids clustering (checks for adjacent houses)
- Spreads houses to avoid lines

**Core Infrastructure:**
- Builds first missing from: `[Granary, LumberCamp, Quarry, MiningCamp]`
- Order is fixed (granary first)

**Wall Ring:**
- Requires: home altar + lumber camp + 3 wood
- Fixed radius of 7 tiles (`WallRingRadius`)
- Places up to 2 doors (`WallRingMaxDoors`)
- Checks multiple radii: 7, 6, 8 tiles

**Tech Buildings:**
- Fixed order: `[WeavingLoom, ClayOven, Blacksmith, Barracks, ArcheryRange, Stable, SiegeWorkshop, MangonelWorkshop, Outpost, Castle, Market, Monastery]`

### Structure Repair

**Current Implementation:** None. No repair behavior exists.
- Damaged structures remain damaged
- No detection of damaged friendly structures
- No repair action implementation

### Defensive vs Economic Priority

**Current Implementation:** No explicit prioritization.
- Wall ring (defensive) is priority 8
- Resource camps are priority 7
- Tech buildings are priority 9
- Order is static regardless of threat level

### Threat Response While Building

**Current Implementation:** None.
- Builders continue building even under attack
- No interrupt for nearby enemies
- No construction abandonment logic

### Gaps & Missing Behaviors

| Gap | Impact | Current Workaround |
|-----|--------|-------------------|
| **No structure repair** | Damaged buildings stay damaged | None |
| **Static defense/economy priority** | May wall when starving, or farm when besieged | Fixed order |
| **No threat response** | Dies while building | None |
| **Fixed wall radius** | Doesn't adapt to expansion | None |
| **No construction coordination** | Two builders may try same building | None |
| **No rebuild after destruction** | Lost buildings not replaced | CoreInfrastructure catches some |
| **No road building** | No pathways between bases | Only in options.nim as meta-behavior |
| **No expansion building** | No forward bases | Only visits neutral hubs |

### Enhancement Recommendations

1. **Structure Repair Option** (high priority)
   ```nim
   proc canStartBuilderRepair: bool =
     # Find any damaged friendly structure
     for thing in env.things:
       if thing.teamId == teamId and isBuildingKind(thing.kind):
         if thing.hp < thing.maxHp:
           return true
     false
   ```
   - Insert before BuilderWallRing (priority 7)

2. **Threat-Aware Building** (high priority)
   - Add `canStartBuilderFlee` similar to gatherer recommendation
   - Also add partial construction abandonment when enemy in range

3. **Dynamic Defense Priority**
   - Add state tracking for "under threat"
   - When threat detected, reorder: WallRing -> TechBuildings -> Infrastructure
   - When safe, reorder: Infrastructure -> TechBuildings -> WallRing

4. **Adaptive Wall Radius**
   - Calculate radius based on current territory/building count
   - Expand wall ring as village grows

5. **Builder Coordination**
   - Track "claimed" building slots
   - Prevent multiple builders on same construction

---

## 3. Fighter Role (`fighter.nim`)

### Current Behavior Priority

| # | Behavior | Description |
|---|----------|-------------|
| 1 | FighterBreakout | Attacks walls/doors when enclosed |
| 2 | FighterRetreat | Retreats when HP <= 1/3 max |
| 3 | FighterMonk | Monk-specific (relics, convert) |
| 4 | FighterDividerDefense | Villagers build walls vs enemy |
| 5 | FighterLanterns | Places lanterns for vision |
| 6 | FighterDropoffFood | Drops off food items |
| 7 | FighterTrain | Trains units at military buildings |
| 8 | FighterMaintainGear | Gets armor/spear at blacksmith |
| 9 | FighterHuntPredators | Hunts bears/wolves (HP >= 50%) |
| 10 | FighterClearGoblins | Clears goblin structures |
| 11 | FighterSmeltGold | Gold smelting |
| 12 | FighterCraftBread | Bread crafting |
| 13 | FighterStoreValuables | Storage |
| 14 | FighterAggressive | Hunts tumors/spawners, food |
| 15 | FighterFallbackSearch | Fallback search |

### Combat Decision Making

**Attack Opportunity Detection (`findAttackOpportunity`):**
- Scans all things for valid targets
- Respects range by unit class:
  - Archer: `ArcherBaseRange`
  - Mangonel: `MangonelAoELength`
  - Others: 2 (with spear) or 1 (without)
- Must be in cardinal/diagonal line with target

**Target Priority (by unit class):**

| Mangonel Priority | Standard Priority |
|-------------------|-------------------|
| 1. Attackable structures | 1. Tumors |
| 2. Tumors | 2. Spawners |
| 3. Spawners | 3. Enemy agents |
| 4. Enemy agents | 4. Structures |

### Siege Engine Conversion (KEY FINDING)

**Question:** "Do fighters convert to siege engines when seeing enemy walls?"

**Answer:** Not exactly. The current implementation:

1. `FighterTrain` checks `fighterSeesEnemyStructure()` at line 446-448
2. Only trains siege units (SiegeWorkshop, MangonelWorkshop) if enemy structures visible
3. **Requires a UnitVillager** to be at the training building
4. Fighters themselves don't "convert" - they trigger villager training

**Relevant Code:**
```nim
const FighterSiegeTrainKinds = [MangonelWorkshop, SiegeWorkshop]

proc canStartFighterTrain(...): bool =
  if agent.unitClass != UnitVillager:
    return false  # Only villagers can train!
  let seesEnemyStructure = fighterSeesEnemyStructure(env, agent)
  for kind in FighterTrainKinds:
    if kind in FighterSiegeTrainKinds and not seesEnemyStructure:
      continue  # Skip siege if no enemy structures
    ...
```

**Gap:** The "fighter" role assigns this behavior to fighter-slot villagers (slots 4,5), not to actual combat units. Combat units have no siege-related behaviors.

### Retreat/Healing Behavior

**Retreat (`FighterRetreat`):**
- Triggers when `agent.hp * 3 <= agent.maxHp` (HP <= 33%)
- Moves toward nearest: Outpost, Barracks, TownCenter, or Monastery
- Terminates when HP > 33%

**Healing:**
- Global in `decideAction`: eats bread when `hp * 2 < maxHp` (HP < 50%)
- No seeking of healers/monasteries
- No health potion behavior

### Group Tactics

**Current Implementation:** None.
- Each fighter acts independently
- No formation logic
- No coordinated attacks
- No flanking or pincer movements
- `FighterAggressive` checks for allies nearby but only for HP threshold decision

### Gaps & Missing Behaviors

| Gap | Impact | Current Workaround |
|-----|--------|-------------------|
| **No actual siege conversion** | Combat units can't become siege | Villagers train siege units |
| **No kiting for ranged** | Archers stand still while attacking | None |
| **No tactical retreat** | Retreat is just "run home" | None |
| **No group coordination** | Fighters act independently | None |
| **No target swapping** | Stuck attacking same target | None |
| **No priority for protecting structures** | Ignores enemy siege | Standard priority |
| **No ally-aware engagement** | May engage alone vs group | None |
| **No healer-seeking** | Only self-heal with bread | None |
| **No formation movement** | Scattered approach | None |
| **No cover/terrain use** | Ignores defensive positions | None |
| **No ambush behavior** | Always direct approach | None |

### Enhancement Recommendations

1. **True Siege Conversion** (critical)
   - Allow combat units (not just villagers) to interact with SiegeWorkshop
   - Add `FighterBecomeSiege` option:
   ```nim
   proc canStartFighterBecomeSiege: bool =
     if agent.unitClass in {UnitManAtArms, UnitKnight}:
       if fighterSeesEnemyStructure(env, agent):
         if controller.getBuildingCount(env, teamId, SiegeWorkshop) > 0:
           return true
     false
   ```

2. **Kiting for Ranged Units** (high priority)
   - After attacking, check if melee enemy approaching
   - Move away while maintaining attack range
   - Insert between attack and FighterAggressive

3. **Group Combat Tactics** (medium priority)
   - Count nearby allies before engaging
   - Wait for allies to catch up
   - Focus fire on same target as allies

4. **Tactical Retreat** (medium priority)
   - Consider escape routes, not just destination
   - Lead enemies away from base if possible
   - Retreat toward allies, not just buildings

5. **Anti-Siege Priority** (high priority)
   - Add option to prioritize attacking enemy siege units
   - Especially if they're attacking friendly structures

6. **Target Swapping**
   - Re-evaluate target every N ticks
   - Switch to lower HP enemy if available
   - Switch to higher threat if ally in danger

---

## Cross-Role Analysis

### Missing Interactions

| From Role | To Role | Missing Interaction |
|-----------|---------|---------------------|
| Fighter | Builder | No request for defensive structures |
| Builder | Fighter | No awareness of combat needs |
| Gatherer | Fighter | No call for protection |
| Fighter | Gatherer | No escort behavior |
| Builder | Gatherer | No coordination on resource buildings |

### Global Gaps

1. **No communication/coordination system** between agents
2. **No role switching** based on situation (can't become fighter if threatened)
3. ~~**No shared threat map** across all agents~~ ✅ **COMPLETE** - Implemented in `ai_core.nim` with `ThreatMap` type, per-team tracking, and full API (`reportThreat`, `getNearestThreat`, `getThreatsInRange`, `getTotalThreatStrength`, `hasKnownThreats`). All agents update the map via `updateThreatMapFromVision` each tick. Scouts actively use it for tactical decisions.
4. **No strategic planning** (all tactical/reactive)
5. **No economy-to-military conversion** during crises

---

## Priority Enhancement Ranking

| Priority | Enhancement | Affected Role(s) | Status |
|----------|-------------|------------------|--------|
| 1 | ~~Danger flee behavior~~ | Gatherer, Builder | ✅ COMPLETE |
| 2 | True siege conversion | Fighter | Open |
| 3 | Structure repair | Builder | Open |
| 4 | Kiting for ranged | Fighter | Open |
| 5 | Group combat tactics | Fighter | Open |
| 6 | Threat-aware building | Builder | Open |
| 7 | Anti-siege priority | Fighter | Open |
| 8 | ~~Resource priority weighting~~ | Gatherer | ✅ COMPLETE |
| 9 | Builder coordination | Builder | Open |
| 10 | ~~Cow milking~~ | Gatherer | ✅ COMPLETE |

---

## File Reference

- `src/scripted/ai_core.nim` - Core AI types, movement, pathfinding
- `src/scripted/ai_defaults.nim` - Building behaviors, role catalog
- `src/scripted/options.nim` - Shared meta-behaviors
- `src/scripted/gatherer.nim` - Gatherer options
- `src/scripted/builder.nim` - Builder options
- `src/scripted/fighter.nim` - Fighter options
- `src/scripted/roles.nim` - Role catalog management
- `src/scripted/evolution.nim` - Evolutionary role system
