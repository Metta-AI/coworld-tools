# Combat System Notes

Date: 2026-01-28
Owner: Design / Systems
Status: Active

## Overview
We introduced AoE-style class counters using explicit bonus damage by unit class, plus per-unit combat overlays and distinct bonus-hit flashes. This improves readability and makes the counter system visible while also emitting richer action tint observation codes for agents.

## Counter Bonuses (Class vs Class)
The counter system lives in `src/combat.nim` as a lookup table:
- `BonusDamageByClass[attacker][target]`

Current bonuses:
- **Archer > Infantry** (UnitArcher gets +1 vs UnitManAtArms/LongSwordsman/Champion)
- **Infantry > Cavalry** (UnitManAtArms gets +1 vs UnitScout/Knight/LightCavalry/Hussar)
- **Cavalry > Archer** (UnitScout/Knight get +1 vs UnitArcher/Crossbowman/Arbalester)

Upgrade tiers inherit and strengthen counter relationships:
- LongSwordsman/Champion get +1/+2 vs cavalry
- Crossbowman/Arbalester get +1/+2 vs infantry
- LightCavalry/Hussar get +1/+2 vs archers

Castle unique units have specialized counters:
- Samurai +1 vs infantry (ManAtArms, LongSwordsman)
- Cataphract +1 vs infantry (ManAtArms, LongSwordsman)
- Huskarl +2 vs archers (Archer, Crossbowman, Arbalester, Longbowman)
- Fire Ship +2 vs water units (Boat, TradeCog, Galley), +1 vs other Fire Ships
- Scorpion +2 vs infantry (ManAtArms, LongSwordsman, Champion, Samurai, WoadRaider, TeutonicKnight, Huskarl)

Villagers, monks, and non-specialized siege have no class bonus.

To tune counters:
- Adjust values in `BonusDamageByClass`.
- Keep bonuses small but decisive (e.g., +1 or +2) to preserve readable outcomes without making fights one-sided.

## Structure Bonus (Siege vs Buildings)
Structure bonus damage is handled in `applyStructureDamage` using `SiegeStructureMultiplier`.
- Only siege units receive the multiplier.
- The bonus uses the same critical-hit overlay as class counters.

## Critical-Hit Overlay
When a bonus applies (class counters or siege-vs-structure), the target tile receives a distinct action tint:
- `BonusDamageTintByClass` in `src/combat.nim` defines per-attacker colors
- `BonusTintCodeByClass` maps attackers to class-specific observation codes
- Applied via `env.applyActionTint` when bonus damage > 0

This makes counter hits visually identifiable in the renderer (a "critical hit" signal) and emits **per-unit `TintLayer` codes** for bonus hits:
- `ActionTintBonusArcher` (14) - archer counter hits on infantry
- `ActionTintBonusInfantry` (15) - man-at-arms counter hits on cavalry
- `ActionTintBonusScout` (16) - scout counter hits on archers
- `ActionTintBonusKnight` (17) - knight counter hits on archers
- `ActionTintBonusBatteringRam` (18) - battering ram siege hits on structures
- `ActionTintBonusMangonel` (19) - mangonel siege hits on structures
- `ActionTintBonusTrebuchet` (20) - trebuchet siege hits on structures

Bonus flashes use **per‑attacker colors** so you can tell which unit type scored the critical hit. Siege units (battering ram, mangonel, trebuchet) have stronger intensity (1.40-1.45 vs 1.18-1.20) for more visible feedback against structures.

## Action Tint Observation Codes
The action tint layer now exposes more detail so agents can tell what kind of event occurred:
- Per-unit attack codes (villager, man-at-arms, archer, scout, knight, monk, battering ram, mangonel, boat)
- Tower and castle attack codes
- Heal codes (monk heal vs bread heal)
- Shield code for armor band flashes
- Class-specific bonus/critical hit codes (archer, infantry, cavalry, siege)
- Mixed code when multiple events overlap on the same tile

See `docs/observation_space.md` for the full list of tint codes.

## Tank Auras (Defensive)
- **Man-at-Arms**: 3x3 defensive aura (gold tint).
- **Knight**: 5x5 defensive aura (gold tint).
- Allies standing inside the aura take **half damage** (rounded up, minimum 1 before armor).
- Overlapping tank auras do not stack; the strongest defensive aura applies.

## Monk Healing Aura
- If any ally within a monk’s 5x5 area is injured, the monk emits a green healing aura.
- Allies in the 5x5 heal **1 HP per step** (no stacking across multiple monks).
- The aura is visible as a 5x5 green tint; healing occurs only when needed.

## DPS Attack Patterns (Visual + Damage)
- **Archer**: line shot to range (stops on first hit).
- **Scout**: short jab (2-tile line, stops on first hit).
- **Battering Ram**: 2-tile line strike (stops on first hit).
- **Mangonel**: widened area strike (3-wide prong extending 5 tiles forward).
- **Boat**: 3-wide forward band (broadside).

## Trebuchet Pack/Unpack
- **Trebuchets** have two modes: packed (mobile) and unpacked (stationary, can attack).
- Unpacking and packing takes a short delay before the trebuchet can act.
- Unpacked trebuchets have long-range siege attacks but cannot move.

## Monk Conversion
- Monks can **convert** enemy units instead of attacking.
- Conversion is blocked if the target's team is already at population cap.
- Converted units switch team ownership and retain their current stats.

## Cliff Fall Damage
- Units that move off a cliff edge (any elevation drop) take **1 fall damage** per tile dropped.
- Ramps and roads at elevation boundaries allow safe traversal without damage.

## Attack-Move and Patrol
- **Attack-move**: Units move toward a destination and automatically engage any enemy encountered en route.
- **Patrol**: Units cycle between patrol waypoints, engaging enemies within their aggro range.

## Unit Stances
Combat behavior modes that control engagement rules:
- Stances determine whether units pursue fleeing enemies, hold position, or auto-engage.

## Cavalry Movement
- **Scouts** and **Knights** attempt to move 2 tiles per step; if blocked, they stop before the obstacle.

## Why This Change
- AoE-like gameplay relies on clear, readable counters.
- Bonus damage makes the counter loop deterministic and consistent across combat scales.
- The overlay provides immediate feedback without adding new UI systems.

## Future Improvements (Optional)
- ~~Class-specific overlays (different tint per counter type).~~ (Done: tv-ch8)
- ~~Stronger feedback on siege vs buildings.~~ (Done: tv-ch8, intensity 1.40)
- Particle/sound hooks in the renderer for critical hits.
- Balance pass once training costs and resource scarcity are tuned.
