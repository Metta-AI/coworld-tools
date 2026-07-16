# player_sdk.simulation — reference physics oracles for offline testing

Stdlib-only, opt-in. Today: `inertia.py`, an integer fixed-point,
momentum-carrying 2D movement engine (`Engine` / `Body` / `InertiaParams`).

## What "byte-faithful reference profile" means

`InertiaParams()`'s defaults (`motion_scale=256, accel=76,
friction=144/256, max_speed=704, stop_threshold=8, slide_max_scan=3`,
1×1 collision) reproduce the origin engine's movement **bit-for-bit** — the
port was validated against the live CrewRift engine (`sim.nim`), including
the truncate-toward-zero friction divide (`_tdiv`) that Python's floor
division gets wrong on negative velocities. The ported physics tests pin
exact integers (terminal 2.75 px/tick, +41% diagonal, one-tick accel of
exactly 76), so any drift in the math fails loudly.

Two emergent properties worth knowing:

- **Independent per-axis clamp**: holding a diagonal reaches
  `terminal_px * sqrt(2)` (~+41% ground speed) — the fact the whole
  `nav_mesh` routing/following stack is built to exploit.
- **Steep friction with a snap-to-zero**: released controls decay velocity
  by ~0.5625/tick and stop below `stop_threshold` — this is what makes the
  follower's release-and-coast arrival land *on* the goal.

## How to use it

- **Closed-loop follower tests** (no game server):
  `validation/players-tests/test_nav_mesh_end_to_end.py` drives
  `nav_mesh.NavState` through `Engine` from plan to arrival — copy that
  shape to regression-test your own policy's movement.
- **Nav-parameter benchmarking**: step two `Body`s under different
  `NavParams` variants over the same course and compare tick counts (the
  origin project ran paired A/B ablations exactly this way).
- **Movement regression pinning**: assert exact positions/velocities after
  a scripted input sequence.
- **Other engines**: pass a custom `InertiaParams` to approximate a
  different accel/friction/clamp model (no longer byte-faithful — by
  design), and any grid with `is_walkable(x, y) -> bool` (duck-typed
  `Walkability`; `nav_mesh.NavGrid` qualifies).

## Origin

Extracted from Ron Dahlgren's (swgy) agent libraries (swgy-crewrift,
`swgy_tools.navbench.enginesim`). Changes in the port: constants →
`InertiaParams` fields, `Player` → `Body`, the game-specific
`vent_cooldown` counter dropped, grid duck-typed so this package imports
nothing from `nav_mesh`.
