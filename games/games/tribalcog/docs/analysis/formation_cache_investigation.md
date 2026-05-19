# Formation Cache Investigation

**Issue:** tv-2b0l4m
**Date:** 2026-02-11
**Status:** Investigation Complete

## Summary

The formation behavior functions in `fighter.nim` perform redundant lookups within the same step. The same agent-specific formation data is computed multiple times during behavior evaluation.

## Current Behavior

When the behavior tree evaluates formation behavior for an agent, it calls three functions in sequence:

1. `canStartFighterFormation` - Checks if formation behavior should activate
2. `shouldTerminateFighterFormation` - Checks if active behavior should terminate
3. `optFighterFormation` - Executes the formation movement

Each of these functions makes the **same expensive calls**:

| Function | Lines | Cost |
|----------|-------|------|
| `findAgentControlGroup(agentId)` | O(n*m) | Iterates all groups × members |
| `isFormationActive(groupIdx)` | O(1) | Array lookup (trivial) |
| `aliveGroupSize(groupIdx, env)` | O(m) | Iterates group members |
| `agentIndexInGroup(groupIdx, agentId, env)` | O(m) | Iterates until found |
| `calcGroupCenter(groupIdx, env)` | O(m) | Iterates all members |
| `getFormationTargetForAgent(...)` | Cached | Already has position cache |

For a single agent in a single step, these functions are called **2-3 times each**.

### Code Location

```
src/scripted/fighter.nim:1387-1460
├── canStartFighterFormation (lines 1387-1408)
├── shouldTerminateFighterFormation (lines 1410-1428)
└── optFighterFormation (lines 1430-1460)
```

### Example Redundancy

For an agent in a 10-member control group:
- `findAgentControlGroup`: Called 3× per step = 30+ iterations
- `aliveGroupSize`: Called 3× per step = 30 iterations
- `agentIndexInGroup`: Called 3× per step = 15 iterations (avg)
- `calcGroupCenter`: Called 3× per step = 30 iterations

**Total:** ~105 iterations per agent per step, where 35 would suffice.

## Existing Caching Infrastructure

The codebase has good caching patterns already:

1. **`PerAgentCache[T]`** in `ai_core.nim:85-126` - Per-agent per-step cache
2. **Formation position cache** in `formations.nim:37-47` - Caches computed positions
3. **Various fighter caches** in `fighter.nim:28-34` - meleeEnemy, siegeEnemy, etc.

## Proposed Solution

Add per-step caching for formation-related lookups using the existing `PerAgentCache` pattern.

### Option A: Per-Agent Formation Cache (Recommended)

Add a composite cache that stores all formation data for an agent in one lookup:

```nim
type
  FormationAgentData* = object
    groupIdx*: int
    myIndex*: int
    groupSize*: int
    center*: IVec2
    targetPos*: IVec2
    isActive*: bool

var formationAgentCache: PerAgentCache[FormationAgentData]

proc getFormationDataCached*(env: Environment, agentId: int): FormationAgentData =
  formationAgentCache.get(env, agentId) do (env: Environment, agentId: int) -> FormationAgentData:
    var data: FormationAgentData
    data.groupIdx = findAgentControlGroup(agentId)
    if data.groupIdx < 0:
      data.isActive = false
      return data
    data.isActive = isFormationActive(data.groupIdx)
    if not data.isActive:
      return data
    data.groupSize = aliveGroupSize(data.groupIdx, env)
    data.myIndex = agentIndexInGroup(data.groupIdx, agentId, env)
    data.center = calcGroupCenter(data.groupIdx, env)
    if data.myIndex >= 0 and data.center.x >= 0:
      data.targetPos = getFormationTargetForAgent(data.groupIdx, data.myIndex, data.center, data.groupSize)
    else:
      data.targetPos = ivec2(-1, -1)
    data
```

Then refactor the three formation procs to use this single cached call.

**Pros:**
- Single cache lookup per agent per step
- Follows existing patterns
- Easy to implement

**Cons:**
- Computes all data even if `canStart` returns false early
- Slight memory overhead per agent

### Option B: Per-Group Formation Cache

Cache at the group level, shared across all agents in the group:

```nim
type
  FormationGroupData = object
    size: int
    center: IVec2
    positions: array[MaxFormationSize, IVec2]

var formationGroupCache: array[ControlGroupCount, FormationGroupData]
var formationGroupCacheStep: int = -1
```

**Pros:**
- More efficient for large groups (compute once, share)
- Lower memory than per-agent

**Cons:**
- Still need per-agent lookups for `findAgentControlGroup` and `agentIndexInGroup`
- More complex invalidation

### Option C: Minimal Caching

Cache only the most expensive operation (`findAgentControlGroup`):

```nim
var agentGroupCache: PerAgentCache[int]

proc findAgentControlGroupCached*(env: Environment, agentId: int): int =
  agentGroupCache.get(env, agentId, findAgentControlGroup)
```

**Pros:**
- Simplest change
- Catches the O(n*m) lookup

**Cons:**
- Still has redundant O(m) calls for other functions

## Recommendation

**Option A** provides the best balance of simplicity and effectiveness. It:
- Eliminates all redundant lookups with minimal code change
- Follows the established `PerAgentCache` pattern
- Is easy to understand and maintain

## Impact Assessment

Per the AI_PERF_AUDIT.md:
- **Impact:** ~0.01ms per formation member per step
- **Scope:** Only affects agents in active formations
- **Priority:** Low (formations are optional, not always used)

This is a "nice to have" optimization, not critical. The formation system works correctly; this just reduces redundant computation.

## Implementation Checklist

If approved for implementation:

- [ ] Add `FormationAgentData` type to `formations.nim`
- [ ] Add `formationAgentCache: PerAgentCache[FormationAgentData]`
- [ ] Create `getFormationDataCached` proc
- [ ] Refactor `canStartFighterFormation` to use cache
- [ ] Refactor `shouldTerminateFighterFormation` to use cache
- [ ] Refactor `optFighterFormation` to use cache
- [ ] Add unit test for cache correctness
- [ ] Verify no performance regression

## Files to Modify

1. `src/formations.nim` - Add cache type and accessor
2. `src/scripted/fighter.nim` - Refactor three formation procs
3. `tests/behavior_formations.nim` - Add cache test
