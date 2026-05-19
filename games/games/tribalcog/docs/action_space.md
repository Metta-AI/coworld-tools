# Action Space Reference

Date: 2026-01-28
Owner: Engineering / Systems
Status: Active

## Overview

The Tribal Village action space uses a discrete encoding scheme where each action is represented as a single integer from 0 to 307.

### Action Encoding Formula

```
action = verb * 28 + argument
```

Where:
- **verb**: The action type (0-10)
- **argument**: The action parameter (0-27)

### Total Action Space

- **11 verbs** x **28 arguments** = **308 total actions**

---

## Verb Reference

| Verb | Name | Description | Valid Arguments |
|------|------|-------------|-----------------|
| 0 | noop | No operation | Any (ignored) |
| 1 | move | Move in direction | 0-7 (directions) |
| 2 | attack | Attack in direction | 0-7 (directions) |
| 3 | use | Interact with terrain/building | 0-7 (directions) |
| 4 | swap | Swap position with teammate | 0-7 (directions) |
| 5 | put | Give items to adjacent agent | 0-7 (directions) |
| 6 | plant_lantern | Plant lantern in direction | 0-7 (directions) |
| 7 | plant_resource | Plant wheat/tree on fertile tile | 0-3 wheat, 4-7 tree (cardinal dirs) |
| 8 | build | Build structure | 0-27 (BuildChoices index) |
| 9 | orient | Change orientation without moving | 0-7 (directions) |
| 10 | set_rally_point | Set building rally point | 0-7 (directions) |

---

## Direction Arguments (0-7)

For verbs that use directional arguments (move, attack, use, swap, put, plant_lantern, plant_resource, orient):

| Arg | Direction | Delta (x, y) |
|-----|-----------|--------------|
| 0 | N (North) | (0, -1) |
| 1 | S (South) | (0, +1) |
| 2 | W (West) | (-1, 0) |
| 3 | E (East) | (+1, 0) |
| 4 | NW (Northwest) | (-1, -1) |
| 5 | NE (Northeast) | (+1, -1) |
| 6 | SW (Southwest) | (-1, +1) |
| 7 | SE (Southeast) | (+1, +1) |

Note: The coordinate system uses standard screen coordinates where Y increases downward.

---

## Build Choices (Verb 8)

When verb = 8 (build), the argument selects from the following building types:

| Arg | Building | Build Cost | Cooldown |
|-----|----------|------------|----------|
| 0 | House | 1 Wood | 10 |
| 1 | Town Center | 14 Wood | 16 |
| 2 | Mill | 5 Wood | 12 |
| 3 | Lumber Camp | 5 Wood | 10 |
| 4 | Quarry | 5 Wood | 12 |
| 5 | Granary | 5 Wood | 12 |
| 6 | Dock | 8 Wood | 12 |
| 7 | Market | 9 Wood | 12 |
| 8 | Barracks | 9 Wood | 12 |
| 9 | Archery Range | 9 Wood | 12 |
| 10 | Stable | 9 Wood | 12 |
| 11 | Siege Workshop | 10 Wood | 14 |
| 12 | Castle | 33 Stone | 20 |
| 13 | Outpost | 1 Wood | 8 |
| 14 | Wall | (terrain conversion) | - |
| 15 | Road | (terrain conversion) | - |
| 16 | Blacksmith | 8 Wood | 12 |
| 17 | Monastery | 9 Wood | 12 |
| 18 | University | 10 Wood | 14 |
| 19 | Door | 1 Wood | 6 |
| 20 | Clay Oven | 4 Wood | 12 |
| 21 | Weaving Loom | 3 Wood | 12 |
| 22 | Barrel | 2 Wood | 10 |
| 23 | Guard Tower | 5 Wood | 12 |
| 24 | Mangonel Workshop | 10 Wood, 4 Stone | 14 |
| 25 | Trebuchet Workshop | 12 Wood, 6 Stone | 16 |
| 26 | Wonder | 50 Wood, 50 Stone, 50 Gold | 50 |
| 27 | Mining Camp | 5 Wood | 12 |

---

## Plant Resource Arguments (Verb 7)

When verb = 7 (plant_resource), arguments encode both direction and resource type:

| Arg | Resource | Direction |
|-----|----------|-----------|
| 0 | Wheat | N (North) |
| 1 | Wheat | S (South) |
| 2 | Wheat | W (West) |
| 3 | Wheat | E (East) |
| 4 | Tree | N (North) |
| 5 | Tree | S (South) |
| 6 | Tree | W (West) |
| 7 | Tree | E (East) |

Note: Plant resource only uses cardinal directions (0-3 for the 4 cardinal directions), not all 8 directions.

The target tile must be **Fertile** terrain.

---

## Invalid Action Conditions

Actions become invalid (incrementing `actionInvalid` stat) under specific conditions. Understanding these helps reduce wasted actions.

### Verb 0: Noop
- Never invalid (always succeeds)

### Verb 1: Move
Invalid when:
- Target position outside map bounds
- Target position in map border zone
- Elevation difference > 1 without ramp
- Non-boat entering water without dock access
- Enemy door blocking path
- Target cell occupied by non-teammate, non-harvestable entity (wall, enemy, building, frozen object)

### Verb 2: Attack
Invalid when:
- Argument > 7 (invalid direction)
- Attack hits no valid target:
  - Melee attack hits nothing at target cell
  - Ranged attack (Archer) hits nothing in trajectory
  - AoE attack (Mangonel) hits nothing in blast area
  - Spear sweep hits nothing
  - Scout/Ram 2-tile attack hits nothing
  - Boat attack hits nothing
- Monk conversion: target team at population cap
- Monk conversion: target is not an agent

### Verb 3: Use
Invalid when:
- Argument > 7 (invalid direction)
- Target position outside map bounds
- Target tile is frozen
- No valid terrain interaction at target
- Target building/object is frozen
- Building does not support the interaction

### Verb 4: Swap
Invalid when:
- Argument > 7 (invalid direction)
- No agent at target position
- Target is not an agent
- Target agent is frozen

### Verb 5: Put (Give Items)
Invalid when:
- Argument > 7 (invalid direction)
- Target position outside map bounds
- No entity at target position
- Target is not an agent or is frozen
- No transferable items (nothing to give or target full)

### Verb 6: Plant Lantern
Invalid when:
- Argument > 7 (invalid direction)
- Target cell not empty, has door, blocked terrain, or frozen
- Agent has no lantern in inventory

### Verb 7: Plant Resource
Invalid when:
- Direction index out of range
- Target tile not empty or blocked
- Target terrain is not Fertile
- Planting tree without wood in inventory
- Planting wheat without wheat in inventory

### Verb 8: Build
Invalid when:
- No valid adjacent build spot found
- Invalid build key (costs.len == 0)
- Cannot afford building (insufficient resources)
- Placement failed

### Verb 9: Orient
Invalid when:
- Argument < 0 or > 7 (invalid direction)

### Verb 10: Set Rally Point
Invalid when:
- Agent is not adjacent to a production building (Barracks, Archery Range, etc.)
- Target building does not belong to agent's team
- Argument > 7 (invalid direction)

### Unknown Verbs (>= 11)
- Always invalid

---

## Computed Action Values

Quick reference for common actions:

| Action | Verb | Arg | Encoded Value |
|--------|------|-----|---------------|
| Noop | 0 | 0 | 0 |
| Move North | 1 | 0 | 28 |
| Move South | 1 | 1 | 29 |
| Move West | 1 | 2 | 30 |
| Move East | 1 | 3 | 31 |
| Attack North | 2 | 0 | 56 |
| Attack South | 2 | 1 | 57 |
| Use North | 3 | 0 | 84 |
| Swap North | 4 | 0 | 112 |
| Put North | 5 | 0 | 140 |
| Plant Lantern North | 6 | 0 | 168 |
| Plant Wheat North | 7 | 0 | 196 |
| Plant Tree North | 7 | 4 | 200 |
| Build House | 8 | 0 | 224 |
| Build Town Center | 8 | 1 | 225 |
| Orient North | 9 | 0 | 252 |
| Set Rally Point North | 10 | 0 | 280 |

---

## Source Code References

- **Action encoding**: `src/common_types.nim` (`encodeAction` proc, `ActionVerbCount`, `ActionArgumentCount` constants)
- **Action processing**: `src/step.nim` and `src/actions.nim` (included by step.nim)
- **Verb names**: `src/replay_writer.nim`
- **BuildChoices array**: `src/environment.nim`
- **Building registry**: `src/registry.nim`
