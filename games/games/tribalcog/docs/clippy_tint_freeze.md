# Clippy Tint, Tumors, and Frozen Tiles

Date: 2026-02-06
Owner: Docs / Systems
Status: Active

## Overview
The game uses three tint layers:
1. **Base tint**: static biome color (`baseTintColors`).
2. **Computed tint**: dynamic territory overlay from agents, lanterns, and tumors
   (`computedTintColors`).
3. **Action tint**: short-lived combat/heal/shield flashes (`actionTint*`).

Only the **action tint** is currently encoded in the observation `TintLayer`.

Key files:
- `src/tint.nim` (dynamic tint accumulation and decay)
- `src/colors.nim` (tint blending + frozen logic)
- `src/step.nim` (tumor behavior, action tint decay)
- `src/environment.nim` (territory scoring)

## Dynamic Tint System (Territory)
`tint.nim` maintains two tint channels:
- **Trail tint** (`tintMods` + `tintStrength`): agents and lanterns.
- **Tumor tint** (`tumorTintMods` + `tumorStrength`): clippy spread.

Each step:
- Previous tint values decay (`TrailDecay`, `TumorDecay`).
- Agents add team tint in a Manhattan radius 2, scale 90.
- Lanterns add team tint in a Manhattan radius 2, scale 60.
- Tumors add clippy tint in a Manhattan radius 2, scale `TumorIncrementBase`.

`ensureTintColors` triggers the trail + tumor recompute into `computedTintColors`:
- Water tiles always zero out computed tint.
- Intensity is proportional to total strength (`TintStrengthScale`).
- RGB channels are normalized and clamped.

## Frozen Tiles
A tile is **frozen** when its *combined* tint (base + computed) matches the clippy tint
within tolerance:

- `isTileFrozen` compares `combinedTileTint` to `ClippyTint`.
- `isThingFrozen` is true if the thing has `frozen > 0` or is on a frozen tile.

Frozen tiles/objects are **non-interactable**:
- `use`, `build`, `plant`, and other interactions check `isTileFrozen` / `isThingFrozen`.
- Movement does **not** directly check frozen state, so agents can path over frozen tiles.

## Action Tint (Combat/Heals/Shield)
Action tints are separate from territory tint:
- Short-lived, stored in `actionTint*` arrays.
- Updated by attacks, tower shots, monk heals, tank aura shields, and bread heals.
- Decayed each step and written to the `TintLayer` observation.

Important distinction: the observation tint layer is **not** the same as the territory
(clippy/lantern/agent) tint.

## Tumors and Clippy Spread
Tumors are spawned by spawners and can branch over time:
- Spawner cooldown depends on `tumorSpawnRate`.
- Tumors branch after `TumorBranchMinAge` with `TumorBranchChance`.
- A tumor that branches becomes inert (`hasClaimedTerritory`).

Adjacency effects:
- Agents/predators adjacent to tumors can die with probability
  (`TumorAdjacencyDeathChance`).
- Shields can block tumor adjacency death if the tumor is in the shield band.

## Territory Scoring
At episode end, `scoreTerritory` counts tiles by nearest tint color:
- Team colors are compared to `computedTintColors`.
- Clippy tiles are detected by distance to `ClippyTint`.
- Low-intensity tiles are neutral.

## Common Gotchas (from recent sessions)
- “Freeze” is **tint-based**, not hunger-based. It depends on clippy tint strength.
- The action tint layer is for combat events, not territory ownership.
- Water tiles always clear computed tint; clippy does not “freeze” water.

## See Also
- `docs/combat_visuals.md`
- `docs/observation_space.md`
