# Guided Bot Fix Log

Historical record of bug fixes. Newest first.

## Orbit bug — A\* path-following oscillation (2026-05-01, FIXED)

**Symptom:** Bot orbits ±5 px around a point ~80 px from the goal for
the entire match. Action mix shows all four diagonal directions in
roughly equal proportions despite A\* computing a clear rightward path.
Zero tasks attempted.

**Root cause:** `PathLookahead=18` selected a waypoint 18 single-pixel
A\* steps ahead. Combined with ~2 px camera-localization jitter, the
path trimming (drop steps within Manhattan distance ≤ 2) consumed steps
unpredictably, placing the waypoint past corridor turns or behind walls.
`steerButtons` aimed straight at the off-axis waypoint, hit walls, and
reversed — creating a stable orbit.

**Fix (action.nim):**
- `PathLookahead` 18 → 4
- Periodic path recomputation every `ReplanIntervalTicks=24` (~1 s)
- Stall detector: force replan when distance hasn't decreased in
  `StallProgressTicks=48` (~2 s)
- New `ActionState` fields: `lastReplanTick`, `bestGoalDist`,
  `bestGoalDistTick`

**Trace enhancement (trace.nim, bot.nim):**
- `logDecision` now includes `mask`, `self_x`, `self_y`, `localized`
- Log call moved to after `applyIntent` so the mask is available

**Verified:** 30 s local match, seed 42 — bot reaches task station at
t=277, holds A for remaining 400 ticks. Distance to goal decreases
monotonically (with minor jitter) from 126 px to 7 px.

## Action-table ordering (2026-05-01, FIXED)

- [x] `ffi/lib.nim:TrainableMasks` reordered to match
  `mettagrid.bitworld.BITWORLD_ACTION_MASKS`
- [x] Compile-time assertion (`CanonicalMasks` + `static:` block)
- [x] Python-side guard (`test/test_action_table.py`)

## Idle wander (2026-05-01, FIXED)

- [x] `DisciplineWander` added to `types.nim`, `action.nim`
- [x] `modes/idle.nim` emits directional movement on non-interstitial frames
- [x] Passes cogames 10-step validation gate

## Localization in live matches (RESOLVED)

The localization-never-locks issue noted in earlier sessions appears to
have been resolved by the baked-asset refresh and/or the actor-exclusion
ignore-mask improvements. A 30 s 8-agent match (seed 42, 2026-05-01)
showed 100% camera lock rate after the initial interstitial window
(~140 frames). The spiral fallback was not needed (all locks were
tier-1 local refit after the initial tier-2 patch-hash lock).
