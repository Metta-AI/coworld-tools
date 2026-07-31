# player_sdk.nav_grid — grid navigation for 4-way movement worlds

A self-contained, pure-stdlib navigation toolkit for discrete grid games
under partial observability. Opt-in: not re-exported from
`players.player_sdk` — import explicitly, e.g.
`from players.player_sdk.nav_grid import GridNavConfig, next_move`.

## What's in the box

Six modules, with this dependency graph (arrows = "imports"):

```
distance.py   (leaf — no deps)
tabu.py       (leaf — no deps)
deadlock.py   (leaf — no deps)
core.py       ──> distance
explore.py    ──> core, distance
stuck.py      ──> tabu
```

| Module | Role |
|--------|------|
| `core.py` | **The core.** Cost-shaped A* / Dijkstra pathfinding with potential fields (repulsors/attractors), configurable spacing buffers for teammates/strangers/obstacles, a decaying "tabu trail" to discourage backtracking, teammate-trajectory collision prediction, path caching with opportunistic detours, sidestep/bump handling, and manual position tracking. ~50 knobs on `GridNavConfig`. |
| `distance.py` | Canonical distance metrics (`manhattan`, `chebyshev`, `euclidean`, `euclidean_sq`) so call sites name the metric explicitly. Hard dependency of `core` and `explore`. |
| `explore.py` | Exploration *target selection* strategies — frontier BFS, sector assignment, spiral, POI patrol, biased wander. Each is a pure function returning a target coordinate that you then hand to `core.next_move`. It decides *where*, not *how*. |
| `stuck.py` | Stuck/no-progress detection for navigation pursuits: position-stuck, axial-stuck (insufficient forward projection onto the start→goal vector), and pacing-stuck (confined to too few unique cells), plus `check_and_resolve` bundling detection with a tabu write. |
| `tabu.py` | A reusable TTL'd blacklist keyed by any hashable (coordinate, `(coord, resource)`, ...), with a failure-strike→promote pattern. Dependency of `stuck`; also useful standalone for "stop retrying this target for a while." |
| `deadlock.py` | Generic convergence-resource deadlock recovery: detect agents piling up adjacent to a central resource (hub/depot/station) that can't currently serve them, and arm a temporary backoff target with deterministic, comms-free scatter. |

## Coordinate model (read this first)

Everything is `(row, col)` integer tuples, type-aliased as `Coordinate`.

The library operates entirely in the **caller's local frame**: the agent's
spawn cell is `(0, 0)`, and its position advances *only* through move-success
accounting — there is no global map oracle. This mirrors the original
environment, where each agent sees only a local observation window and gets no
shared global coordinates. If you bring this into a context that *does* have
absolute coordinates, you can simply feed those in as the local frame and skip
the dead-reckoning — but then you must keep `update_position` consistent with
your ground truth.

## The per-tick caller contract (`core`)

Per agent, per tick, **in this order**:

1. `update_position(nav_state, last_dir, succeeded, ...)` — fold the previous
   move attempt into `position` / `blocked`. **Skipping this silently desyncs
   `position` from the world; the module cannot detect it.**
2. `view = observe(nav_state, frozen_tags, obs_center)` — fold visible walls
   into `blocked`, classify visible entities (teammates / strangers / blockers
   / hostile-AOE cells) into a per-tick `GridNavView`. `frozen_tags` is your
   `{observation-window-coord: frozenset[int tag ids]}` for the current frame.
3. `direction = next_move(nav_state, view, target_local, ...)` — returns a
   direction name (`"north"`/`"south"`/`"east"`/`"west"`) or `None`. `None`
   means "no path within budget — you decide whether to noop, wander, or pick a
   new goal." Wander policy is intentionally *not* in this module.
   Use `next_move_cached(...)` instead when you want opportunistic POI detours
   and a plan cached/replayed across ticks.
4. `record_step(nav_state)` after issuing the move — pushes the new position
   onto the tabu trail.

You own one persistent `GridNavState` per agent for the episode; `GridNavView`
is per-tick and must never be persisted.

The caller is responsible for turning the returned direction string into
whatever action your engine expects — e.g. `Action(name=f"move_{direction}")`
for MettaGrid games, or a `"north" → "up"` remap for paintarena-style
protocols. See also `players.player_sdk.action_names.ActionTable`.

All game semantics enter through the tag-id frozensets on `GridNavConfig`
(`wall_tag_ids`, `teammate_tag_ids`, `stranger_tag_ids`,
`extra_blocker_tag_ids`, `enemy_aoe_tag_ids`, `bump_target_tag_ids`) —
nothing in this package imports a game engine.

## Cost model (how the pathfinder is shaped)

Edge cost into a cell `C`:

```
cost(C) = clamp(cost_floor, max_repulsion_per_step,
                base_terrain_weight + repulsion(C) - attraction(C))
```

Repulsion (teammates, strangers, soft wall buffers, the tabu trail, and any
caller-supplied repulsors) *adds* cost; attraction *subtracts*. A cost floor
and per-step caps keep A* well-behaved. The heuristic auto-selects between
Manhattan (admissible when no attractors are active) and zero/Dijkstra
(admissible always). See the module docstring in `core.py` for the full
treatment of admissibility trade-offs.

## API at a glance

- **`core`**: `GridNavConfig`, `GridNavState`, `GridNavView`,
  `update_position`, `observe`, `record_team_observations`, `next_move`,
  `next_move_cached`, `plan_path`, `record_step`, `try_sidestep`, `arrived`,
  `is_bump_target`.
- **`distance`**: `manhattan`, `chebyshev`, `euclidean`, `euclidean_sq`.
- **`explore`**: `ExploreConfig`, `ExploreState`, `note_observed`,
  `frontier_bfs`, `sector_assignment`, `spiral`, `poi_patrol`, `biased_wander`,
  `is_stuck`.
- **`stuck`**: `StuckConfig`, `StuckState`, `position_stuck`, `axial_stuck`,
  `pacing_stuck`, `check_and_resolve`, `reset`.
- **`tabu`**: `TabuConfig`, `TabuState`, `is_tabu`, `add_tabu`,
  `record_failure`, `record_success`, `gc`.
- **`deadlock`**: `DeadlockConfig`, `DeadlockState`, `update_deadlock_state`,
  `pick_backoff_cell`.

All configuration is via plain frozen-ish dataclasses (`*Config`); construct
one with overridden fields and pass it in. Read the dataclass field docstrings
for the knob-level documentation. The configs compose with
`players.player_sdk.tuning` (string-kwarg coercion, GA genome vectors).

## Tests

The original modules shipped embedded smoke tests (190 scenario checks in
total). They are ported 1:1 to
`players/validation/players-tests/test_nav_grid_*.py`, preserving the numbered
scenario comments and assertion labels, plus a pure-Manhattan reference A*
(`_ref_manhattan_astar`) used as an identity oracle for the cost-shaped A*.

## Origin

Extracted from Ron Dahlgren's (swgy) agent libraries — the sm-policies
Cogs-vs-Clips scripted-policy stack, via its standalone `SWGY-Nav` bundle.
Original module names were `swgy_nav.py`, `swgy_distance.py`,
`swgy_explore.py`, `swgy_stuck.py`, `swgy_tabu.py`, `swgy_deadlock.py`;
`SWGYNav{Config,State,View}` became `GridNav{Config,State,View}` and the other
`SWGY*` prefixes were dropped. Docstrings retain "lineage" references to files
of that original stack (e.g. `policy_base.py`, `mas_weighted_astar.py`) as
historical record — those files are not part of this repository.

Provenance honesty note, carried over from the original bundle: much of this
code and its documentation was AI-generated within a larger project and was
not line-by-line audited at extraction time. It is, however, battle-tested
(it drove multiple tournament policy stacks) and the ported scenario tests
above are the regression net.

### Supersedes (candidates for future migration — not changed here)

This package generalizes patterns that today exist as per-policy copies:

- `players/players/cogsguard/_shared/pathfinding.py` (BFS shortest-path)
- `players/players/cogsguard/buggy/navigator.py` and its `cranky/` duplicate
- `players/users/james/personal_cogs/persephone/orpheus/pathfinding.py`
