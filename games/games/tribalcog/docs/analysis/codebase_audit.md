# Tribal Village Codebase Structure Audit

Date: 2026-01-28
Updated: 2026-02-12
Owner: Engineering / Analysis
Status: Complete (most recommendations implemented; see audit-world-sim-core.md for current state)

## 1. Codebase Overview

The tribal village codebase is a game simulation environment (~17,000 lines of Nim code) with Python bindings for RL training.

### File Structure

```
tribal_village/
├── tribal_village.nim       # Main game loop & rendering
├── src/
│   ├── types.nim           # Core type definitions (655 lines)
│   ├── environment.nim     # Game environment logic (large)
│   ├── step.nim            # Step/action execution (large)
│   ├── spawn.nim           # Map generation & spawning
│   ├── common.nim          # Shared utilities
│   ├── terrain.nim         # Terrain types & mechanics
│   ├── items.nim           # Item system
│   ├── combat.nim          # Combat mechanics
│   ├── agent_control.nim   # Controller interface (90 lines)
│   ├── ffi.nim             # Python FFI bindings
│   ├── renderer.nim        # Visual rendering
│   └── scripted/           # AI behavior system
│       ├── ai_core.nim     # Core AI utilities (1033 lines)
│       ├── ai_defaults.nim # Role assignment & decisions (960 lines)
│       ├── options.nim     # RL-style option definitions (993 lines)
│       ├── roles.nim       # Role/catalog system (393 lines)
│       ├── evolution.nim   # Role evolution (138 lines)
│       ├── gatherer.nim    # Gatherer behaviors (427 lines)
│       ├── builder.nim     # Builder behaviors (454 lines)
│       └── fighter.nim     # Fighter behaviors (654 lines)
├── tests/                  # Test suites
├── tribal_village_env/     # Python environment wrapper
│   ├── environment.py      # PufferLib integration
│   └── cogames/            # Training utilities
└── data/                   # Asset/config files
```

## 2. Architecture

### 2.1 Role System

Roles are defined in `src/scripted/roles.nim`:

```nim
type
  AgentRole* = enum
    Gatherer   # Resource collection
    Builder    # Construction & infrastructure
    Fighter    # Combat & defense
    Scripted   # Evolutionary/custom role
```

**Role Assignment** (in `ai_defaults.nim:699-706`):
- Agents assigned based on `slot mod 6`:
  - Slots 0, 1 → Gatherer
  - Slots 2, 3 → Builder
  - Slots 4, 5 → Fighter

### 2.2 Behavior System (Options Framework)

The system uses an RL-style "options" framework where each behavior has:

```nim
type OptionDef* = object
  name*: string
  canStart*: proc(...)   # Initiation condition
  shouldTerminate*: proc(...) # Termination condition
  act*: proc(...): uint8      # Per-tick action
  interruptible*: bool
```

Behaviors are executed via `runOptions()` which scans options in priority order.

### 2.3 Current Behavior Inventory

#### Gatherer Options (10 behaviors)
| Name | Purpose |
|------|---------|
| GathererPlantOnFertile | Plant wheat/trees on fertile tiles |
| GathererMarketTrade | Use market for resource trading |
| GathererCarryingStockpile | Drop off carried resources |
| GathererHearts | Collect hearts for altar |
| GathererResource | Gather wood/stone/gold |
| GathererFood | Harvest food sources |
| GathererIrrigate | Use water to create fertile tiles |
| GathererScavenge | Collect items from skeletons |
| GathererStoreValuables | Store items in storage buildings |
| GathererFallbackSearch | Spiral search fallback |

#### Builder Options (16 behaviors)
| Name | Purpose |
|------|---------|
| BuilderPlantOnFertile | Plant resources |
| BuilderDropoffCarrying | Drop off resources |
| BuilderPopCap | Build houses for population |
| BuilderCoreInfrastructure | Build Granary/LumberCamp/Quarry/MiningCamp |
| BuilderMillNearResource | Build mills near food |
| BuilderPlantIfMills | Plant if mills exist |
| BuilderCampThreshold | Build camps near resources |
| BuilderWallRing | Build defensive wall ring |
| BuilderTechBuildings | Build tech buildings |
| BuilderGatherScarce | Gather scarce resources |
| BuilderMarketTrade | Use market |
| BuilderVisitTradingHub | Visit neutral trading hubs |
| BuilderSmeltGold | Smelt gold at magma |
| BuilderCraftBread | Craft bread at clay oven |
| BuilderStoreValuables | Store valuables |
| BuilderFallbackSearch | Spiral search fallback |

#### Fighter Options (15 behaviors)
| Name | Purpose |
|------|---------|
| FighterBreakout | Break through walls when enclosed |
| FighterRetreat | Retreat when low HP |
| FighterMonk | Special monk behavior (relics) |
| FighterDividerDefense | Build defensive walls toward enemies |
| FighterLanterns | Place lanterns for vision |
| FighterDropoffFood | Drop off food |
| FighterTrain | Train military units |
| FighterMaintainGear | Get armor/spear from blacksmith |
| FighterHuntPredators | Hunt bears/wolves |
| FighterClearGoblins | Clear goblin structures |
| FighterSmeltGold | Smelt gold |
| FighterCraftBread | Craft bread |
| FighterStoreValuables | Store valuables |
| FighterAggressive | Attack tumors/spawners |
| FighterFallbackSearch | Spiral search fallback |

#### Meta Behaviors (28 behaviors in `options.nim`)
Cross-cutting behaviors available to evolutionary roles:
- Lantern management (FrontierPush, GapFill, Recovery, Logistics)
- Anti-tumor/spawner patrol
- Fortification (GuardTower, Outpost, Walls, Doors, Roads)
- Castle building
- Siege unit production
- Unit promotion
- Relic collection
- Predator/goblin hunting
- Fertile expansion
- Market manipulation
- Dock control
- Territory sweeping
- Temple fusion

## 3. Dead Code / Unused Features

### 3.1 Potentially Dead Code

1. ~~**`ScriptedTempleAssignEnabled = false`**~~ — Now enabled (`= true`, ai_defaults.nim:30).
   Temple hybrid assignment is active; `processTempleHybridRequests` and `pendingHybridRoles` execute at runtime.

2. **`EvolutionEnabled = defined(enableEvolution)`** (ai_defaults.nim:395)
   - Role evolution is compile-flag gated
   - When disabled, all evolution-related code is dead:
     - `generateRandomRole`, `applyScriptedScoring`, role fitness tracking

3. **Unused Constants** (builder.nim:1-16)
   - `WallRingRadiusSlack`, `DividerDoor*` constants defined but wall ring uses simple radius check

4. **Legacy Observation Layers** (types.nim) - **CLEANED (tv-lvcn)**
   - `AgentLayer` alias retained - used throughout step.nim and combat.nim
   - `altarHeartsLayer` alias retained - used in step.nim
   - Vestigial `AgentInventory*Layer` aliases and call sites removed (all mapped to same layer)

### 3.2 Feature Flag Dependencies

| Flag | Affects |
|------|---------|
| `enableEvolution` | Role scoring, history saving, temple hybrids |
| `renderTiming` | Timing profiler in main loop |
| `emscripten` | Web build conditionals |

## 4. Duplicated Logic

### 4.1 Resource Gathering Patterns

Multiple roles duplicate resource gathering:
- `ensureWood`, `ensureStone`, `ensureGold` called from Gatherer, Builder, Fighter
- Each has similar dropoff logic

**Recommendation**: These are already factored into shared procs in `ai_core.nim` - good design.

### 4.2 Building Construction

Multiple behaviors share building placement logic:
- `tryBuildAction`, `goToAdjacentAndBuild`, `goToStandAndBuild`
- Already well-factored in `ai_defaults.nim`

### 4.3 Market Trade Logic

**Status**: Consolidated

Shared market trading behavior is now defined in `options.nim`:
- `canStartMarketTrade*` - shared initiation condition (line 755)
- `optMarketTrade*` - shared action proc (line 777)

Used by:
- `GathererOptions` in gatherer.nim (as "GathererMarketTrade")
- `BuilderOptions` in builder.nim (as "BuilderMarketTrade")
- `MetaBehaviorOptions` in options.nim (as "BehaviorMarketManipulator")

## 5. Inconsistent Patterns

### 5.1 Termination Functions

Most behaviors use `optionsAlwaysTerminate` but some have custom logic:
- `shouldTerminateFighterBreakout` - checks if enclosed
- `shouldTerminateFighterRetreat` - checks HP threshold
- `shouldTerminateFighterDividerDefense` - checks enemy presence

Pattern is inconsistent - some behaviors could benefit from termination conditions.

### 5.2 Interruptible Flag

All behaviors set `interruptible: true` but the flag isn't always meaningful since most terminate immediately.

### 5.3 Building Count Caching

`getBuildingCount` caches per-step, but some behaviors query raw `env.thingsByKind` directly.

## 6. Extension Points for New Behaviors

### 6.1 Where New Behaviors Plug In

1. **Add to role-specific options array**:
   - `GathererOptions` in gatherer.nim
   - `BuilderOptions` in builder.nim
   - `FighterOptions` in fighter.nim
   - `MetaBehaviorOptions` in options.nim

2. **Register with behavior catalog** (automatic via `seedDefaultBehaviorCatalog`):
   ```nim
   catalog.addBehaviorSet(GathererOptions, BehaviorGatherer)
   ```

3. **Evolutionary roles** pick from registered behaviors

### 6.2 Suggested New Optional Behaviors

| Behavior | Role | Description |
|----------|------|-------------|
| EmergencyHeal | Any | Eat bread when HP < 50% (currently global, could be option) |
| DefensiveTurret | Fighter | Stay near guard towers for protection |
| ResourceScout | Gatherer | Scout for new resource nodes |
| AllySupport | Fighter | Stay near friendly units |
| BuildingRepair | Builder | Repair damaged buildings |
| WaterTransport | Gatherer | Carry water for irrigation |
| TownCenterDefense | Fighter | Patrol around town center |
| StrategicWalling | Builder | Wall off chokepoints |
| EconomyFocus | Gatherer | Prioritize lowest stockpile resource |
| UnitEscort | Fighter | Escort villagers |

### 6.3 Architecture for New Behaviors

```nim
# 1. Define canStart condition
proc canStartMyBehavior(controller: Controller, env: Environment, agent: Thing,
                        agentId: int, state: var AgentState): bool =
  # Return true when behavior should activate
  someCondition(agent)

# 2. Define action logic
proc optMyBehavior(controller: Controller, env: Environment, agent: Thing,
                   agentId: int, state: var AgentState): uint8 =
  # Return encoded action or 0 for pass
  let target = findTarget(env, agent)
  if isNil(target):
    return 0'u8
  actOrMove(controller, env, agent, agentId, state, target.pos, 3'u8)

# 3. Add to options array
let MyRoleOptions* = [
  # ... existing options ...
  OptionDef(
    name: "MyBehavior",
    canStart: canStartMyBehavior,
    shouldTerminate: optionsAlwaysTerminate,
    act: optMyBehavior,
    interruptible: true
  ),
]
```

## 7. Cleanup Recommendations

### High Priority

1. **Remove dead temple hybrid code** if feature won't be enabled
   - Or enable it and test

2. **Consolidate market trading** into single shared behavior

3. **Add meaningful termination conditions** to behaviors that would benefit

### Medium Priority

4. ~~**Document the include pattern**~~ - DONE: See ai_system.md "Understanding the include pattern" section

5. **Standardize building queries** - use `getBuildingCount` consistently

6. ~~**Consider extracting shared behaviors**~~ - DONE: SmeltGoldOption, CraftBreadOption, StoreValuablesOption defined in options.nim and used by Builder, Fighter, Gatherer roles

### Low Priority

7. **Review all behaviors for consistent interruptible usage**

8. **Add behavior fitness tracking** for non-evolutionary builds (useful metrics)

## 8. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Python Environment                       │
│  (tribal_village_env/environment.py - PufferLib wrapper)    │
└────────────────────────────┬────────────────────────────────┘
                             │ FFI (ctypes)
┌────────────────────────────▼────────────────────────────────┐
│                      src/ffi.nim                             │
│           (C-compatible interface to Nim)                    │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                  src/agent_control.nim                       │
│         (Controller interface: BuiltinAI / ExternalNN)       │
└──────┬─────────────────────────────────────────────┬────────┘
       │ BuiltinAI                                   │ ExternalNN
       ▼                                             ▼
┌──────────────────┐                     ┌─────────────────────┐
│ src/scripted/    │                     │ Python NN provides  │
│ ├── ai_core.nim  │                     │ actions directly    │
│ ├── ai_defaults  │                     └─────────────────────┘
│ ├── roles.nim    │
│ ├── options.nim  │
│ ├── gatherer.nim │
│ ├── builder.nim  │
│ ├── fighter.nim  │
│ └── evolution    │
└────────┬─────────┘
         │ decideAction()
         ▼
┌─────────────────────────────────────────────────────────────┐
│                     runOptions()                             │
│  1. Check active option (continue if not terminated)         │
│  2. Scan options by priority                                 │
│  3. First matching canStart() → call act()                  │
│  4. Return encoded action                                    │
└─────────────────────────────────────────────────────────────┘
```

## 9. Key Observations

1. **Well-structured behavior system** - The options framework is clean and extensible

2. **Good separation of concerns** - Core AI utils, role-specific behaviors, and evolution are properly separated

3. **Include vs Import** - Uses `include` for scripted modules which creates a single compilation unit but can make dependencies less clear

4. **Evolution system is optional** - Compile flag allows pure rule-based or evolutionary approaches

5. **Agent state is comprehensive** - `AgentState` tracks spiral search, escape mode, build targets, path planning

6. **Performance-conscious** - Building counts cached per-step, spiral search uses incremental state

This audit should help identify cleanup opportunities and guide addition of new optional behaviors.
