# Subsystem Audit: World Simulation Core

**Issue:** tv-wisp-ywl24
**Files:** step.nim (2679 lines), environment.nim (2729 lines), spawn.nim (1849 lines), types.nim (1531 lines)
**Total:** 8788 lines

---

## Executive Summary

The world simulation core has grown organically to 9321 lines across 4 files. The main `step()` function in step.nim is 2650 lines (lines 1088-3737), making it difficult to maintain and understand. This audit identifies logical sections that could be extracted, duplicated state management, and opportunities to simplify spawn.nim.

---

## 1. step.nim Analysis (2679 lines)

### 1.1 Current Structure

```
Lines 1-104:      Configuration and includes (~100 lines)
Lines 173-374:    Visual effects decay procs (~200 lines)
Lines 381-625:    Building attack/garrison logic (~245 lines)
Lines 626-729:    Auras/survival/utility procs (~105 lines)
Lines 730-907:    Victory condition checks (~175 lines)
Lines 908-950:    Victory orchestration (~40 lines)
Lines 951-1087:   Tumor processing (~135 lines)
Lines 248-2602:   THE MAIN step() FUNCTION (~2355 lines)
Lines 2603-2679:  reset() function (~77 lines)
```

### 1.2 Extractable Sections

#### A. Visual Effects Module (`step_visuals.nim`) - ~200 lines
**Lines 173-374**

| Proc | Lines | Purpose |
|------|-------|---------|
| spawnProjectile | 173-189 | Create visual projectile |
| stepDecayProjectiles | 191-206 | Decay projectile pool |
| stepDecayDamageNumbers | 208-218 | Decay damage floaters |
| stepRagdolls | 220-239 | Physics for ragdolls |
| stepDecayDebris | 241-257 | Building debris particles |
| stepDecaySpawnEffects | 259-269 | Unit spawn animations |
| stepDecayDyingUnits | 271-281 | Death animations |
| stepDecayGatherSparkles | 283-299 | Resource gather FX |
| stepDecayConstructionDust | 301-317 | Building dust particles |
| stepDecayUnitTrails | 319-335 | Movement trails |
| stepDecayWaterRipples | 337-347 | Water effects |
| stepDecayActionTints | 349-373 | Combat tint decay |
| stepDecayShields | 375-379 | Shield timer decay |

**Benefit:** All follow identical pattern (countdown decay, in-place compaction). Common abstraction possible.

#### B. Building Combat Module (`building_combat.nim`) - ~245 lines
**Lines 381-625**

| Proc | Lines | Purpose |
|------|-------|---------|
| stepTryTowerAttack | 381-503 | Tower attack targeting |
| stepTryTownCenterAttack | 505-554 | TC defensive fire |
| garrisonCapacity | 556-563 | Building garrison limits |
| garrisonUnitInBuilding | 565-586 | Add unit to garrison |
| ungarrisonAllUnits | 588-624 | Evacuate building |

**Benefit:** Encapsulates all defensive building logic.

#### C. Aura Effects Module (`auras.nim`) - ~100 lines
**Lines 626-729**

| Proc | Lines | Purpose |
|------|-------|---------|
| stepApplySurvivalPenalty | 626-638 | Per-step survival cost |
| stepApplyTankAuras | 640-661 | Man-at-Arms/Knight auras |
| stepApplyMonkAuras | 663-699 | Monk healing auras |
| stepRechargeMonkFaith | 701-710 | Faith regeneration |
| isOutOfBounds | 712-715 | Bounds check |
| isBlockedByShield | 717-728 | Shield line-of-sight |
| applyFertileRadius | 730-753 | Farm fertility |

**Benefit:** Separates passive effects from action processing.

#### D. Victory Conditions Module (`victory.nim`) - ~195 lines
**Lines 755-950**

| Proc | Lines | Purpose |
|------|-------|---------|
| teamHasUnitsOrBuildings | 755-768 | Team elimination check |
| checkConquestVictory | 770-782 | Conquest mode win |
| checkWonderVictory | 784-801 | Wonder timer win |
| checkRelicVictory | 803-827 | Relic collection win |
| checkRegicideVictory | 829-849 | King survival win |
| checkKingOfTheHillVictory | 851-894 | Hill control win |
| updateWonderTracking | 896-906 | Wonder timer tick |
| checkVictoryConditions | 908-949 | Victory orchestration |

**Benefit:** Victory logic is self-contained and testable independently.

#### E. Tumor Processing Module (`tumors.nim`) - ~135 lines
**Lines 951-1087**

| Proc | Lines | Purpose |
|------|-------|---------|
| stepProcessTumors | 951-1018 | Tumor expansion/claiming |
| stepApplyTumorDamage | 1020-1086 | Tumor damage to units |

**Benefit:** Encapsulates the tumor/creep mechanic entirely.

#### F. Animal AI Module (`animal_ai.nim`) - ~220 lines
**Lines 2978-3216 (inside step())**

Currently inline in step(). Contains:
- Cow herd aggregation and movement
- Wolf pack hunting behavior
- Bear wandering and aggression
- Helper procs: `stepToward`, `tryStep`, `selectNewCornerTarget`

**Benefit:** Animal behavior is self-contained logic that doesn't need to be inline.

#### G. Respawn/Population Module (`respawn.nim`) - ~120 lines
**Lines 3306-3428 (inside step())**

Currently inline in step(). Contains:
- Dead agent respawn at altars
- Temple hybrid spawning
- Population cap enforcement

**Benefit:** Population mechanics are independent of action processing.

### 1.3 The Main Action Handler (lines 1282-2804)

The action case statement is ~1520 lines. Breakdown:

| Action | Lines | Size | Complexity |
|--------|-------|------|------------|
| NOOP (0) | 1282-1283 | 2 | Trivial |
| Move (1) | 1284-1488 | 205 | High (terrain checks, cavalry, water) |
| Attack/Gather (2) | 1489-1788 | 300 | High (combat, resources, monk) |
| Build (3) | 1789-2429 | **640** | **Very High** |
| Research (4) | 2430-2455 | 26 | Medium |
| Trade (5) | 2456-2528 | 73 | Medium |
| Garrison (6) | 2529-2566 | 38 | Low |
| Ungarrison (7) | 2567-2622 | 56 | Low |
| Production (8) | 2623-2771 | 149 | Medium |
| Orient (9) | 2772-2781 | 10 | Trivial |
| SetRallyPoint (10) | 2782-2804 | 23 | Low |

**Recommendation:** The Build action at 640 lines is the largest single block. Consider:
1. Extract building placement validation to helper procs
2. Use lookup tables for building costs/types
3. Split foundation placement from multi-tile buildings

---

## 2. Duplicated State Management

### 2.1 Team Population Tracking

**step.nim (lines 1233-1251):**
```nim
for i in 0 ..< MapRoomObjectsTeams:
  env.stepTeamPopCaps[i] = 0
  env.stepTeamPopCounts[i] = 0
for thing in env.thingsByKind[TownCenter]:
  ...
for thing in env.thingsByKind[House]:
  ...
```

**Issue:** This logic is recalculated every step. Consider:
- Incremental tracking when buildings are added/removed
- Cached values in Environment that update on change

### 2.2 Grid/Spatial Index Updates

Both step.nim and environment.nim update:
- `env.grid[x][y]`
- `updateSpatialIndex(env, thing, oldPos)`

**Issue:** No single source of truth. Entity position changes happen in multiple places.

**Recommendation:** Create `moveEntity(env, thing, newPos)` proc in environment.nim that handles all bookkeeping.

### 2.3 Observation Layer Updates

**step.nim:** `env.updateObservations(...)` called inline during action processing
**environment.nim:** `rebuildObservations()` rebuilds entire observation tensor

**Issue:** The lazy-rebuild approach (`observationsDirty = true`) is good, but the inline `updateObservations` calls during step() are now potentially redundant since observations are rebuilt when accessed.

---

## 3. spawn.nim Analysis (1818 lines)

### 3.1 Overly Long Functions

| Function | Lines | Size | Issue |
|----------|-------|------|-------|
| initTerrainAndBiomes | 234-529 | 296 | Terrain gen + biome placement mixed |
| initTradingHub | 530-756 | 227 | Trading post placement |
| initTeams | 1014-1276 | 263 | All team initialization |
| initResources | 1482-1636 | 155 | Resource distribution |
| initWildlife | 1637-1735 | 99 | Animal spawning |

### 3.2 Simplification Opportunities

1. **Extract biome-specific logic** from initTerrainAndBiomes into separate procs:
   - `placeBiomeForest()`
   - `placeBiomeDesert()`
   - `placeBiomeTundra()`
   - `placeBiomeSwamp()`

2. **Use configuration tables** for resource cluster placement instead of hardcoded loops

3. **Extract team component placement** from initTeams:
   - `placeTeamTownCenter()`
   - `placeTeamStartingUnits()`
   - `placeTeamStartingResources()`

---

## 4. types.nim Analysis (1350 lines)

### 4.1 Type Organization

The file is well-organized with:
- Map constants (lines 17-126)
- TeamMask utilities (lines 127-195)
- Observation layers enum (lines 198-296)
- Unit classes and stances (lines 305-401)
- Thing types and enums (remaining)

### 4.2 Potentially Unused Types

After searching the codebase, all major types appear to be in use. However:

1. **ActionTint constants** (lines 69-117) - 49 constants. Some may be legacy:
   - `ActionTintMixed` (line 94) - verify usage
   - Various bonus tint codes - may be consolidatable

2. **ObservationName layers** (lines 198-296) - 86 layers. Very comprehensive but:
   - Some cliff layers may be unused if cliff rendering was simplified

### 4.3 Recommendations

1. Add section comments for better navigation:
   ```nim
   # ============ Map Constants ============
   # ============ Team Utilities ============
   # ============ Observation Layers ============
   ```

2. Consider splitting into:
   - `types/core.nim` - fundamental types
   - `types/observations.nim` - observation layers
   - `types/units.nim` - unit classes/stances

---

## 5. Priority Refactoring Recommendations

### High Priority (Significant Impact)

1. **Extract Visual Effects** - Move `stepDecay*` procs to `step_visuals.nim`
   - Low risk, high clarity gain
   - ~200 lines out of step.nim

2. **Extract Victory Conditions** - Move to `victory.nim`
   - Self-contained, easily testable
   - ~195 lines out of step.nim

3. **Extract Animal AI** - Move cow/wolf/bear behavior to `animal_ai.nim`
   - Currently inline in step(), easy to extract
   - ~220 lines out of step()

### Medium Priority (Moderate Impact)

4. **Extract Building Combat** - Move to `building_combat.nim`
   - Tower/TC attack logic is distinct from action processing
   - ~245 lines out of step.nim

5. **Simplify Build Action** - The 640-line build handler needs:
   - Helper procs for validation
   - Lookup tables for costs
   - Separation of placement logic by building type

### Lower Priority (Cleanup)

6. **Centralize Entity Movement** - Single `moveEntity()` proc
7. **Review Observation Updates** - Remove redundant inline updates
8. **Consolidate ActionTint constants** - Verify all are used

---

## 6. Proposed File Structure After Refactoring

```
src/
├── step.nim               # Main step() (2679 lines)
├── step_visuals.nim       # Visual effects decay (260 lines) ✅ extracted
├── building_combat.nim    # Tower/TC attacks, garrison (259 lines) ✅ extracted
├── auras.nim              # Passive aura effects (107 lines) ✅ extracted
├── victory.nim            # Victory conditions (235 lines) ✅ extracted
├── tumors.nim             # Tumor mechanics (183 lines) ✅ extracted
├── animal_ai.nim          # Cow/wolf/bear behavior (284 lines) ✅ extracted
├── respawn.nim            # Population/respawn (144 lines) ✅ extracted
├── environment.nim        # Core env state (2729 lines)
├── spawn.nim              # Map generation (1849 lines)
└── types.nim              # Type definitions (1531 lines)
```

---

## Appendix: Line Count Summary

All Phase 1 extractions are complete.

| File | Original | Current |
|------|----------|---------|
| step.nim | 3810 | 2679 |
| step_visuals.nim | (in step.nim) | 260 |
| building_combat.nim | (in step.nim) | 259 |
| auras.nim | (in step.nim) | 107 |
| victory.nim | (in step.nim) | 235 |
| tumors.nim | (in step.nim) | 183 |
| animal_ai.nim | (in step.nim) | 284 |
| respawn.nim | (in step.nim) | 144 |

Total lines remain similar, but step.nim becomes ~35% smaller and more focused.
