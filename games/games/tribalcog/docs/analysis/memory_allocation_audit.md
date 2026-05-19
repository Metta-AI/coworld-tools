# Memory Allocation Audit: Entity Spawning and Despawning

Date: 2026-02-18
Status: Completed
Issue: tv-vx80f9

## Executive Summary

This audit profiles memory allocation patterns in the tribal_village entity spawning
and despawning systems. The codebase has a solid foundation with object pooling for
high-frequency entities, arena allocators for temporary data, and pre-allocated
capacities for combat arrays. One bug was found (Corpse bypass of object pool) and
several optimization opportunities identified.

## Current Memory Architecture

### Object Pool System (`ThingPool`)

Located in `src/types.nim` and `src/placement.nim`.

**Pooled entity kinds** (`PoolableKinds`):
- Tumor
- Corpse
- Skeleton
- Stubble
- Lantern
- Stump

**Pool operations:**
- `acquireThing(env, kind)` - Gets from pool or allocates new
- `releaseThing(env, thing)` - Returns to pool for reuse
- `resetThing(thing, kind)` - Resets all fields for reuse

**Pool statistics tracking:**
```nim
PoolStats = object
  acquired: int    # Total acquisitions
  released: int    # Total releases
  poolSize: int    # Current free pool size
```

### Arena Allocator (`Arena`)

Per-step temporary allocations use pre-allocated sequences that reset to len=0
but retain capacity:

```nim
Arena = object
  things1-4: seq[Thing]    # Scratch buffers
  positions1-2: seq[IVec2] # Position buffers
  ints1-2: seq[int]        # Index/count buffers
  itemCounts: seq[tuple]   # Inventory data
  strings: seq[string]     # Formatting buffer
```

### Pre-allocated Capacities

- `ProjectilePoolCapacity = 128`
- `ActionTintPoolCapacity = 256`
- `ArenaDefaultCap = 1024`

## Entity Creation Analysis

### Spawn Sites by Frequency

**High frequency (pooled - correct):**
| Entity | Location | Uses Pool |
|--------|----------|-----------|
| Tumor | spawn.nim:8 | ✓ `acquireThing` |
| Stump | environment.nim:2362 | ✓ `acquireThing` |
| Lantern | combat.nim:596, step.nim:1533 | ✓ `acquireThing` |
| Corpse | step.nim:583 | ✓ `acquireThing` |
| Skeleton | step.nim:1100 | ✓ `acquireThing` |
| Stubble | step.nim:1015 | ✓ `acquireThing` |

**BUG FOUND - Pool bypass:**
| Entity | Location | Issue |
|--------|----------|-------|
| Corpse | combat.nim:563 | Uses `Thing(kind: Corpse)` directly |

**Low frequency (not pooled - acceptable):**
- Wall, GuardTower, Castle, TownCenter, House, Temple
- Door, GoblinHive, GoblinHut, GoblinTotem
- Cliffs, Waterfalls (map generation only)
- ControlPoint

**Medium frequency (pooling candidates):**
| Entity | Create Sites | Destroy Sites | Recommendation |
|--------|--------------|---------------|----------------|
| Relic | 5 locations | step.nim:992 | Consider pooling |
| Wheat | 3 locations | step.nim:1014 | Consider pooling |
| Tree | step.nim:1585 | environment.nim:2361 | Consider pooling |

## Entity Destruction Analysis

### Despawn Sites (`removeThing` calls)

Total: 28 call sites across 8 files

**High-frequency despawn paths:**
1. `step.nim` - Resource gathering (14 sites)
   - Corpse/Skeleton looting
   - Bush/Tree/Wheat harvesting
   - Lantern collection
   - Relic pickup

2. `tumors.nim` - Tumor lifecycle (2 sites)
   - Tumor decay
   - Predator removal

3. `combat.nim` - Building destruction (1 site)
   - Drops relics before removal

**Low-frequency despawn paths:**
- `spawn.nim` - Map generation cleanup (5 sites)
- `connectivity.nim` - Path carving (2 sites)
- `animal_ai.nim` - Predator kills tumor (1 site)

### Despawn Memory Behavior

The `removeThing` function properly:
1. Removes from spatial index
2. Clears grid position
3. Updates observations
4. Uses swap-and-pop for O(1) list removal
5. Returns poolable kinds to pool via `releaseThing`

## Findings

### Bug: Corpse Pool Bypass

**Location:** `src/combat.nim:563`

**Current code:**
```nim
let corpse = Thing(kind: (if dropInv.len > 0: Corpse else: Skeleton), pos: deathPos)
```

**Issue:** Creates Corpse/Skeleton directly, bypassing object pool.

**Fix:** Use `acquireThing` for Corpse, but note the conditional logic requires
careful handling since the kind varies.

**Impact:** Memory fragmentation during extended combat. Each agent death
allocates a new object instead of reusing pooled instances.

### Optimization Opportunity: Expand PoolableKinds

**Candidates for pooling:**

| Kind | Create/s | Destroy/s | Impact |
|------|----------|-----------|--------|
| Relic | Medium | Medium | Small |
| Wheat | High (farming) | High | Medium |
| Tree | Low (planting) | High (chopping) | Small |

**Recommendation:** Add Wheat and Tree to PoolableKinds if farming/forestry
becomes performance-critical.

### Good Patterns Found

1. **Swap-and-pop list removal** - O(1) instead of O(n)
2. **Arena allocator** - Eliminates per-step allocations
3. **Pre-allocated capacities** - Avoids seq growth during combat
4. **setLen(0) preservation** - Keeps allocated capacity
5. **Pool statistics** - Enables runtime monitoring

## Recommendations

### Immediate (Bug Fix)

1. Fix `combat.nim:563` to use `acquireThing`:
```nim
let kind = if dropInv.len > 0: Corpse else: Skeleton
let corpse = acquireThing(env, kind)
corpse.pos = deathPos
```

### Short Term

2. Add pool statistics logging (optional compile flag):
```nim
when defined(poolStats):
  proc logPoolStats*(env: Environment) =
    echo "ThingPool: acquired=", env.thingPool.stats.acquired,
         " released=", env.thingPool.stats.released,
         " poolSize=", env.thingPool.stats.poolSize
```

3. Consider adding Wheat to PoolableKinds if farming is heavy.

### Long Term

4. Profile with `TV_PROFILE_STEPS` to measure actual allocation pressure
5. Consider per-kind pool size caps to bound memory usage
6. Add memory pressure monitoring for adaptive pool sizing

## Test Methodology

1. Static analysis of all `Thing(kind:` and `acquireThing` call sites
2. Static analysis of all `removeThing` call sites
3. Review of pool infrastructure in types.nim and placement.nim
4. Cross-reference with existing documentation

## Files Analyzed

- `src/spawn.nim` - Map generation, entity spawning
- `src/respawn.nim` - Population respawn system
- `src/step.nim` - Game tick, resource gathering
- `src/combat.nim` - Combat, death handling
- `src/tumors.nim` - Tumor lifecycle
- `src/placement.nim` - Pool implementation
- `src/environment.nim` - Tree chopping
- `src/types.nim` - Pool data structures
- `src/step_visuals.nim` - Projectile pool

## Conclusion

The memory allocation architecture is well-designed with proper pooling for
high-frequency entities. One bug (combat.nim Corpse bypass) should be fixed.
The existing pool statistics infrastructure enables easy monitoring if needed.
No major memory leaks or allocation hotspots identified beyond the documented
bug.
