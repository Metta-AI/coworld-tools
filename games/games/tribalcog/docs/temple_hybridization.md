# Temple Hybridization

Date: 2026-01-28
Owner: Design / Gameplay
Status: Active

## What the Temple Does
The Temple allows two adjacent villagers to "recombine" into a new villager,
creating a hybrid role from the parents' behavior priorities. The new role is
registered into the role catalog for later use.

## Asset + Placement
- Asset: `data/assets/temple.png`
- Prompt source: `data/prompts/assets.tsv`
- Placement: `spawn.nim` runs `placeTemple` during map generation.

## Hybrid Trigger (Current Runtime)
Each step, the engine checks every Temple:
1) Find two adjacent living, non-goblin agents on the same team.
2) Ensure team pop cap is not full.
3) Ensure the parents' home altar has at least one heart.
4) Consume one heart, spawn a dormant villager near the temple, and enqueue
   a `TempleHybridRequest`.

Temple spawns have a cooldown (`TempleHybridCooldown` = 25 steps, `TempleInteractionCooldown` = 12 steps) to prevent rapid chaining.

## Role Recombination (Scripted AI)
`processTempleHybridRequests` handles queued hybrids:
- Recombine parent roles via `recombineRoles`.
- Optionally mutate or inject a random behavior.
- Register the new role with `origin = "temple"`.

Hybrid roles are automatically assigned to spawned children when
`ScriptedTempleAssignEnabled` is `true` (the default). This resets the child's
initialization so it receives the hybrid role instead of a default assignment.

## Notes / Future Hooks
- `BehaviorTempleFusion` exists as an option for explicit temple use, but the
  current hybrid spawn is adjacency-based (no explicit action needed).
