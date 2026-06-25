# Combat Visuals and Auras (Design Notes)

Date: 2026-01-28
Owner: Design / UI
Status: Active

This is a design reference for combat readability and VFX cues. It is not
guaranteed to be fully implemented yet.

## Defensive Auras (Tanks)
- Man-at-Arms: 3x3 defensive grid (adjacent tiles) that halves damage.
- Knights: 5x5 defensive grid (bigger aura) that halves damage.
- Suggested color: gold aura tint to read as defense.

## DPS Attack Patterns
Each DPS class should have a distinct attack pattern or animation (similar to
the old spear 3-prong attack). The goal is immediate visual differentiation.

## Monks (Healing Zone)
- Monks emit a 5x5 healing square.
- Suggested color: soft green or teal, distinct from defense gold.

## Critical/Counter Hits
- Use a dedicated highlight color for critical or counter-type damage.
- Ensure the highlight is distinct from the aura palette so it reads on top.

## Color Palette Goals
- Keep a coherent, readable palette across auras and hit effects.
- Prioritize contrast on busy tiles and when stacked with terrain overlays.
