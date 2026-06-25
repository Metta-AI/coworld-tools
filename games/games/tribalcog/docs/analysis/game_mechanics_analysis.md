# Game Mechanics Analysis: Invalid Action Sources

Date: 2026-01-28
Owner: Engineering / Analysis
Status: Active
Task: tv-w0r.3
Context: Profiling showed 340,934 total invalid actions in 3,000 steps (~114 per step)

---

## Executive Summary

Analysis of `/home/relh/Code/tribal-village/src/step.nim` reveals **32 distinct locations** where `actionInvalid` is incremented. The majority of failures fall into three categories:

1. **Attack failures** (11 locations) - attacks that hit nothing
2. **Movement failures** (6 locations) - blocked movement
3. **Resource/precondition failures** (15 locations) - missing items, wrong terrain, frozen tiles

---

## Action Encoding

From `src/common_types.nim`:
- **ActionVerbCount** = 11
- **ActionArgumentCount** = 28
- Action value = `verb * 28 + argument`
- Arguments 0-7 represent 8 directions (N, S, W, E, NW, NE, SW, SE)

### Verb Mapping (from replay_writer.nim)
| Verb | Name | Description |
|------|------|-------------|
| 0 | noop | No operation |
| 1 | move | Move in direction |
| 2 | attack | Attack in direction |
| 3 | use | Interact with terrain/building |
| 4 | swap | Swap position with teammate |
| 5 | put | Give items to adjacent agent |
| 6 | plant_lantern | Plant lantern in direction |
| 7 | plant_resource | Plant wheat/tree on fertile tile |
| 8 | build | Build structure from BuildChoices |
| 9 | orient | Change orientation without moving |
| 10 | set_rally_point | Set building rally point in direction |

---

## All actionInvalid Increment Locations

### 1. Move Action (verb 1) - 6 Locations

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 141 | `invalidAndBreak` template | Generic invalid break (used by multiple checks) | N/A |
| 154 | `not isValidPos(step1)` | Moving outside map bounds | Yes |
| 157 | Border check | Moving into map border zone | Yes |
| 159 | `not env.canTraverseElevation(agent.pos, step1)` | Elevation difference > 1 without ramp | Yes |
| 161 | `env.isWaterBlockedForAgent(agent, step1)` | Non-boat entering water without dock | Yes |
| 163 | `not env.canAgentPassDoor(agent, step1)` | Enemy door blocking path | Yes |
| 261 | Blocker check fail | Cell occupied by non-teammate, non-tree | **EXPECTED HIGH** |

**Analysis for Line 261:**
This is the most likely source of many invalid actions. When an agent tries to move into an occupied cell:
- If teammate: swap positions (valid)
- If tree (non-frozen): harvest it (valid as USE)
- Otherwise: **INVALID**

This includes:
- Moving into walls
- Moving into enemy agents
- Moving into any building
- Moving into frozen objects

### 2. Attack Action (verb 2) - 11 Locations

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 299 | `argument > 7` | Invalid direction argument | **BUG** if AI chooses this |
| 385 | Monk conversion: invalid team ID | Team ID out of bounds | Yes |
| 398 | Monk conversion: pop cap exceeded | Target team at population limit | Yes |
| 427 | Monk: target not an agent | Monk attack on empty/non-agent | **EXPECTED HIGH** |
| 445 | Mangonel: no hits | AoE attack hit nothing | **EXPECTED MEDIUM** |
| 459 | Archer: no ranged hits | Arrow hit nothing in range | **EXPECTED HIGH** |
| 499 | Spear attack: no hits | Spear sweep hit nothing | **EXPECTED MEDIUM** |
| 513 | Scout/Ram: no hits | 2-tile attack hit nothing | **EXPECTED MEDIUM** |
| 528 | Boat: no hits | Boat attack hit nothing | **EXPECTED LOW** |
| 546 | Melee: no hits | Standard attack hit nothing | **EXPECTED HIGHEST** |

**Analysis:**
Attack failures when hitting nothing are **expected game mechanics**. An agent attacking an empty direction is using the action incorrectly. However, the frequency (~114/step) suggests:
- Agents may be attacking randomly without target awareness
- Observation data may not properly indicate attackable targets

### 3. Use Action (verb 3) - 5 Locations

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 551 | `argument > 7` | Invalid direction argument | **BUG** if AI chooses |
| 559 | `not isValidPos(targetPos)` | Using tile outside map | Yes |
| 564 | `isTileFrozen(targetPos, env)` | Target tile is frozen | Yes |
| 628 | Terrain use: no valid interaction | Can't interact with terrain type | **EXPECTED MEDIUM** |
| 633 | `isThingFrozen(thing, env)` | Target building/object frozen | Yes |
| 942 | Building use: no interaction possible | Building doesn't support action | **EXPECTED MEDIUM** |

### 4. Swap Action (verb 4) - 1 Location

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 947 | `argument > 7` | Invalid direction argument | **BUG** |
| 954 | Target check | No agent, not an agent, or frozen | **EXPECTED MEDIUM** |

### 5. Put/Give Action (verb 5) - 4 Locations

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 971 | `argument > 7` | Invalid direction | **BUG** |
| 978 | `not isValidPos(targetPos)` | Position invalid | Yes |
| 982 | `isNil(target)` | No target at position | **EXPECTED MEDIUM** |
| 985 | `target.kind != Agent or isThingFrozen` | Target not valid agent | **EXPECTED** |
| 1039 | No transfer possible | Nothing to give or target full | **EXPECTED MEDIUM** |

### 6. Plant Lantern Action (verb 6) - 2 Locations

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 1044 | `argument > 7` | Invalid direction | **BUG** |
| 1054 | Position check | Not empty, has door, blocked terrain, or frozen | **EXPECTED** |
| 1079 | `agent.inventoryLantern <= 0` | No lantern to plant | **EXPECTED** |

### 7. Plant Resource Action (verb 7) - 5 Locations

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 1094 | `dirIndex < 0 or dirIndex > 7` | Bad direction calc | Yes |
| 1105 | Occupancy check | Tile not empty or blocked | **EXPECTED** |
| 1108 | `terrain != Fertile` | Not fertile terrain | **EXPECTED** |
| 1113 | `inventoryWood <= 0` (tree) | No wood for tree | **EXPECTED** |
| 1123 | `inventoryWheat <= 0` (wheat) | No wheat for crop | **EXPECTED** |

### 8. Build Action (verb 8) - 3 Locations

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 1161 | `targetPos.x < 0` | No valid adjacent build spot | **EXPECTED** |
| 1166 | `costs.len == 0` | Invalid build key | **BUG** |
| 1169 | `payment == PayNone` | Can't afford building | **EXPECTED** |
| 1268 | `not placedOk` | Placement failed | **EXPECTED** |

### 9. Orient Action (verb 9) - 1 Location

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 1273 | `argument < 0 or argument > 7` | Invalid orientation | **BUG** |

### 10. Set Rally Point (verb 10) - See action_space.md

### 11. Unknown Verb - 1 Location

| Line | Condition | Failure Reason | Expected? |
|------|-----------|----------------|-----------|
| 1280 | `else` case | Verb >= 11 | **BUG** |

---

## Categorized Failure Analysis

### Category 1: BUGS (should never happen with valid RL policy)
- Arguments > 7 for directional actions (lines 299, 551, 947, 971, 1044, 1273)
- Unknown verb >= 11 (line 1280)
- Invalid build key with no costs (line 1166)

**Recommendation:** Add action masking to prevent invalid action indices.

### Category 2: EXPECTED - Attack Misses (~70% of invalids estimated)
These represent strategic failures, not bugs:
- Line 427: Monk healing/converting empty tile
- Line 445: Mangonel hitting nothing
- Line 459: Archer missing
- Line 499: Spear missing
- Line 513: Scout/Ram missing
- Line 528: Boat missing
- Line 546: Melee missing

**Recommendation:**
1. Improve observation layer to show attackable targets
2. Add reward shaping to penalize attacks with no valid targets
3. Consider attack action masking based on nearby targets

### Category 3: EXPECTED - Movement Blocked (~20% estimated)
- Line 261: Moving into occupied tiles
- Elevation, water, door checks

**Recommendation:**
1. Movement masking based on local observations
2. The observation system should already encode blocked tiles

### Category 4: EXPECTED - Resource/Precondition Failures (~10% estimated)
- Plant without seeds/wood
- Build without resources
- Use on frozen tiles

**Recommendation:**
1. Inventory-aware action masking
2. Frozen tile observations

---

## Most Likely High-Frequency Failure Points

Based on code structure and game mechanics:

1. **Line 546 (Melee attack miss)** - Every attack in an empty direction
2. **Line 261 (Move blocked)** - Every move attempt into occupied tile
3. **Line 459 (Ranged miss)** - Archer attacks with no target in range
4. **Line 628/942 (Use failures)** - Using terrain/buildings incorrectly

---

## Recommended Fixes (Priority Order)

### P0 - Critical (Prevent Invalid Actions)
1. **Add action masking** for directional actions to only allow valid arguments (0-7)
2. **Clamp action values** at the action execution boundary

### P1 - High Impact (Reduce Invalid Attack Count)
1. **Attack target observation layer** - Show which directions have valid attack targets
2. **Movement mask observation** - Show traversable directions

### P2 - Medium Impact
1. **Inventory-conditional action masking** - Disable plant/build when resources unavailable
2. **Frozen tile observation** - Already exists (ObscuredLayer) but verify AI uses it

### P3 - Design Consideration
1. **Consider making attack-nothing a NOOP** instead of invalid (still counts action but no penalty)
2. **Log which specific failure modes dominate** for targeted optimization

---

## File References

- Action processing: `/home/relh/Code/tribal-village/src/step.nim` (lines 133-1280)
- Action encoding: `/home/relh/Code/tribal-village/src/common.nim` (lines 117-122)
- Stats type: `/home/relh/Code/tribal-village/src/types.nim` (lines 403-415)
- Movement helpers: `/home/relh/Code/tribal-village/src/environment.nim` (lines 350-400)
- Frozen checks: `/home/relh/Code/tribal-village/src/colors.nim` (lines 42-52)
