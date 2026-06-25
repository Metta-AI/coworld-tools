# Entity Interaction Analysis

Date: 2026-01-28
Owner: Engineering / Analysis
Status: Active

## Overview

This document analyzes how agents interact with map entities (animals, enemies) in the tribal_village environment. Agents can interact with entities through the ATTACK action (verb 2) or through proximity-based interactions.

## Entity Definitions

### Animals

| Entity | HP | Attack Damage | Aggro Radius | Behavior |
|--------|-----|---------------|--------------|----------|
| Cow    | N/A | 0             | N/A          | Passive, herding |
| Wolf   | 3   | 1             | 7 (pack)     | Pack hunting, aggro on agents/tumors |
| Bear   | 6   | 2             | 6            | Solo hunting, aggro on agents/tumors |

### Enemies

| Entity | HP | Attack Damage | Behavior |
|--------|-----|---------------|----------|
| Goblin | 4   | 1             | AI-controlled, collects relics, flees from agents |
| Goblin Hut | N/A | N/A | Structure, goblin spawn point |
| Goblin Hive | N/A | N/A | Structure, goblin territory center |
| Goblin Totem | N/A | N/A | Structure, decorative |

## Current Interaction Matrix

| Agent Role | Cow | Wolf | Bear | Goblin | Enemy Wall |
|------------|-----|------|------|--------|------------|
| Gatherer   | Hunt for meat | Flee/Fight | Flee/Fight | Attack | Attack |
| Builder    | Hunt for meat | Flee/Fight | Flee/Fight | Attack | Attack |
| Fighter    | Hunt for meat | Fight | Fight | Attack | Attack |
| All Units  | Attack -> Meat | Attacked on adjacency | Attacked on adjacency | Normal combat | Normal combat |

## Detailed Interactions

### Agent -> Animal Interactions

#### Cows (src/step.nim:359-368)
- **Passive Resource**: Cows do not attack agents
- **Attack Result**: Agent receives `ItemMeat` and cow is removed
- **Corpse**: If `ResourceNodeInitial > 1`, a corpse with additional meat is created
- **Herd Behavior**: Cows move in herds (5-10 per herd), drifting toward map corners
- **No Threat**: Cows have no combat capability

#### Wolves (src/step.nim:1630-1652, 1668-1685)
- **Pack Hunting**: Wolves hunt in packs (3-5 members)
- **Target Acquisition**: `findNearestPredatorTarget()` scans within `WolfPackAggroRadius` (7 tiles)
- **Priority**: Tumors > Agents (destroys non-claimed tumors, then attacks agents)
- **Attack Behavior**: On adjacency, deals `WolfAttackDamage` (1) to agents
- **Pack Cohesion**: Wolves stay within `WolfPackCohesionRadius` (3 tiles) of pack center
- **Agent Counterattack**: Attacking wolf yields meat, same as cow

#### Bears (src/step.nim:1654-1666, 1668-1685)
- **Solo Hunter**: Bears hunt alone
- **Target Acquisition**: Same `findNearestPredatorTarget()` with `BearAggroRadius` (6 tiles)
- **Priority**: Tumors > Agents
- **Attack Behavior**: On adjacency, deals `BearAttackDamage` (2) to agents
- **Higher Threat**: More HP (6) and damage (2) than wolves
- **Agent Counterattack**: Attacking bear yields meat

### Agent -> Enemy Interactions

#### Goblins (src/scripted/ai_defaults.nim:764-798)
- **AI-Controlled**: Goblins have scripted behavior, not player-controlled
- **Relic Collectors**: Primary goal is to collect all relics on the map
- **Evasive**: Flee from non-goblin agents within `GoblinAvoidRadius`
- **Combat**: Can be attacked like any other agent
- **Special Ability**: Goblins can interact with relics (extract gold)
- **Team**: Assigned to `GoblinTeamId` (team 8), not part of player teams

#### Goblin Structures
- **Non-attackable**: Goblin Huts, Hives, and Totems are not in `AttackableStructures`
- **Decorative**: Serve as spawn points and territory markers
- **Neutral**: Have `teamId: -1`

### Predator Target Selection (src/step.nim:1500-1520)

```nim
proc findNearestPredatorTarget(center: IVec2, radius: int): IVec2
```
- Scans area within Chebyshev distance `radius`
- Returns position of nearest valid target
- Targets: Tumors (priority), then Agents
- Ignores: Friendly units, dead agents

### Damage Application

#### Agent Damage (src/combat.nim:119-155)
- Bonus damage table based on unit class matchups
- Armor absorption before HP damage
- Tank aura (Man-at-Arms/Knight) reduces incoming damage by 50%
- Shield countdown provides temporary protection

#### Animal Damage
- Animals deal flat damage on adjacency
- No armor penetration mechanics
- Wolves: 1 damage, Bears: 2 damage

## Missing/Weak Interactions

### 1. No Flee Behavior for Agents
- Agents have no automatic flee response to wolves/bears
- Must rely on scripted AI or player actions

### 2. No Animal Herding/Farming
- Cows cannot be corralled or farmed
- Single-use meat resource only
- No breeding or renewable livestock

### 3. Limited Wolf/Bear AI
- Only hunt within aggro radius
- No pack coordination beyond cohesion
- No ambush or flanking behavior

### 4. Goblin Interactions Limited
- Goblins only collect relics
- No raiding behavior on player structures
- No goblin combat aggression

### 5. No Structure Defense Against Animals
- Walls don't deter wolves/bears
- Guard towers don't target animals
- No pen/fence mechanics

## Proposed Enrichments

### Animal Interactions

1. **Cow Milking**: Add USE action on cows to get milk (cooldown: `CowMilkCooldown` = 25 steps)
2. **Wolf Taming**: Monks could convert wolves to friendly units
3. **Bear Deterrents**: Certain items (fire, noise) could repel bears
4. **Animal Pens**: Buildings to contain and breed livestock

### Combat Enrichments

1. **Flee Reaction**: Gatherers automatically flee from predators
2. **Fighter Aggro**: Fighters draw predator attention from other units
3. **Pack Breaking**: Killing pack leader disperses wolf pack

### Goblin Enrichments

1. **Goblin Raids**: Goblins occasionally raid nearby team structures
2. **Goblin Trading**: Goblins could trade relics for resources
3. **Goblin Totem Effects**: Totems provide buffs to nearby goblins

### Observation Enrichments

1. **Threat Overlay**: Visual indicator for nearby predators
2. **Herd Tracking**: Show cow herd movement patterns
3. **Goblin Territory**: Highlight goblin-controlled areas

## Code References

- Entity definitions: `src/types.nim:300-333`
- Combat system: `src/combat.nim:1-168`
- Animal step logic: `src/step.nim:1606-1686`
- Goblin AI: `src/scripted/ai_defaults.nim:764-798`
- Entity spawning: `src/spawn.nim:1560-1640`
