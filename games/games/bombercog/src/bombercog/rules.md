# Bombercog - Rules

## Overview

Bombercog is a Bomberman-style deathmatch on a small fixed grid. Agents move around the map, switch into "bomb" vibe to
drop bombs on their next move, then flee before the fuse expires. Blasts destroy crates and damage opponents. The
objective is to survive while reducing the opponent's HP.

## Game Mode

Base game is a **2-player deathmatch** on an 11x9 map. Episodes run to `max_steps` (default 500). There is no early
termination or elimination — when an agent's HP reaches zero, it simply stops accumulating the survival reward.

## Map

The base map is an 11 x 9 ASCII grid with:

- `#` — indestructible outer wall and interior pillars (block movement and block rays)
- `C` — destructible crates (1 HP, block movement and block rays)
- `.` — empty tile
- `@` — agent spawn, one in each opposite corner

At least one crate is placed within blast range (2 cells) of each spawn so the first bomb has
something to destroy.

## Agent Actions

- **move** — standard 4-directional movement. In bomb vibe, moving spawns a bomb at the target cell instead of walking
  into it.
- **noop** — wait one tick.
- **change_vibe** — toggle between `default` (walking) and `bomb` (placement).

## Vibes

Only two vibes are available:

- 😐 `default` — normal movement
- 💣 `bomb` — next move spawns a bomb at the target cell (agent stays in place)

## Resources

| Resource | Owner | Base | Max | Description |
| --- | --- | --- | --- | --- |
| `bomb_count` | agent | 1 | 3 | Placement budget. Regenerates over time. |
| `bomb_range` | agent | 2 | 5 | Blast length in cells along each arm. |
| `hp` | agent | 3 | 3 | Agent health. |
| `fuse` | bomb | 5 | 5 | Ticks until explosion. |
| `crate_hp` | crate | 1 | 1 | Crate health (one-shot). |
| `life` | explosion | 2 | 2 | Lifetime of the explosion marker. |

## Bombs

An agent in bomb vibe that moves into an empty cell spawns a bomb instead of walking. The agent's `bomb_count` is
decremented by 1. The bomb appears at the target cell with `fuse=5` and blocks movement.

Each tick, the world-update phase (events, which run after agent actions) decrements the fuse by 1. When the fuse
reaches 0, the blast pipeline fires in a single tick:

1. Explosion markers are spawned along the cross-shaped blast (N/S/E/W) up to `bomb_range` cells.
2. Crates along the blast path lose 1 `crate_hp` and are removed from the grid.
3. Alive agents along the blast path lose 1 `hp`.
4. The bomb itself is removed from the grid.
5. Explosion markers block movement for 1 tick, then are cleaned up.

Blasts are purely cardinal (no diagonals) and stop at the first wall or crate they encounter.

## Bomb Regeneration

Every 10 ticks (`BOMB_REGEN_PERIOD`), every agent's `bomb_count` is incremented by 1, capped at `BOMB_MAX=3`. This means
an agent that burns its bomb budget will recover a bomb roughly every 10 ticks regardless of outcome — no owner
attribution is needed.

## Scoring

Agents receive a per-tick survival reward proportional to their current HP:

```
reward_per_tick = 0.1 * hp
```

- At full HP (3): +0.3 per tick.
- At HP 0: +0 per tick.

This creates a strong implicit incentive to (a) stay alive and (b) damage the opponent. Crate-destruction reward
attribution is deferred — events carry bomb-as-actor context with no owner-agent to credit. A follow-up variant can add
ownership tags for per-agent credit.

## Observations

Default `ObsConfig` auto-exposes all inventory resources and tags. Global obs adds `local_position` and
`last_action_move` so agents can reason about movement history and spatial context.

## Variant Table

Only the base game ships in the first PR. Variants are documented here as the future build plan:

| Variant | Depends on | Adds |
| --- | --- | --- |
| base *(default, shipped)* | — | 2-player, 11x9 fixed map, fuse=5, blast=2, HP=3, regen=10 |
| powerups | base | Destroyed crates drop `bomb_count+` / `bomb_range+` pickups; walking onto pickup gives a resource bonus. |
| chain_reaction | base | Bombs gain a `bomb_hp` resource. Blast rays damage other bombs, and a bomb whose `bomb_hp` reaches 0 explodes on the next tick via the same logic as a fuse-expiry bomb. |
| four_player | base | 4 agents on a 13x11 map, otherwise identical mechanics. |
| kickable_bombs | base | Walking into a bomb pushes it one cell in the move direction (may require a new mutation primitive). |
| procedural_map | base | Replaces the fixed ASCII map with a compound/mapgen procedural layout for training diversity. |

## Engine Notes

Key constraints from the mettagrid engine that shaped the design:

- **No early episode termination** — episodes always run to `max_steps`. "Death" is modelled as loss of the per-tick
  survival reward, not elimination.
- **Tick ordering: actions then world update** — each tick runs agent actions first (immediately after the policy
  decision), then all world-update phases: events, agent on_tick, AOE, game on_tick. This means a bomb placed via a
  move action is immediately visible to the fuse_tick event in the same tick.
- **Blast pipeline via events** — the entire blast pipeline (fuse countdown, marker spawn, crate/agent damage, bomb
  removal, explosion cleanup) runs as ordered events. The pipeline is defined as a Python list that auto-numbers the
  dict keys for alphabetical execution. Only `bomb_regen` uses `game.on_tick` (timing-insensitive).
- **Directional blast** uses `RaycastQuery` / `RaycastSpawnMutation` with `blocker=[isA("wall"), isA("crate")]`. The
  engine's default `isNear` cannot distinguish cardinal from diagonal, so raycasting is the only correct primitive.
- **`targetHas` is `>=` semantics.** "Fuse is exactly 0" is written as `isNot(targetHas({"fuse": 1}))`.
- **Object removal** happens via `withdraw({"X": 0}, remove_when_empty=True)`. After an event decrements a resource
  to 0, the inventory entry is erased and a zero-amount self-withdraw triggers the `is_empty()` check and removes
  the object.
