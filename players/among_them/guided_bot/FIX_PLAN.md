# Guided Bot Fix Log

Historical record of bug investigations and fixes. Newest first.
Implementation plans live in [`IMPL_PLAN.md`](IMPL_PLAN.md).

---

## Task-completion detection missing (2026-05-01, OPEN)

**Symptom:** Bot navigates to a task station, enters `DisciplineTaskHold`,
and holds A indefinitely. It never detects completion, never selects a
new target. 75% of a 30 s match is spent holding A at one station.

**Root cause:** Not a bug — missing functionality. `modes/task_completing.nim:149-161`
returns `DisciplineTaskHold` with `pressA: true` every tick once inside
the task rect. Three things are absent:

1. **No hold duration cap.** `ActionState.taskHoldTicks` increments
   (`action.nim:291`) but nothing reads it. Modulabot uses
   `TASK_HOLD_TICKS = 84` (~3.5 s).
2. **No completion confirmation.** The perception pipeline scans task
   icons every frame and populates `belief.percep.visibleTaskIcons`,
   but the mode never checks whether the icon at the current station
   has disappeared (the server-authoritative completion signal).
3. **No target unlock / re-selection.** `scratch.tcLockedTaskIndex` is
   set on first arrival and never cleared.

### Hypotheses (ranked by likelihood)

**H1 — Task completes but bot doesn't notice (most likely).** The server
accepts the A-hold within ~72 ticks, the task icon vanishes, but the
bot never checks. Diagnostic: run a traced match, compare
`visibleTaskIcons` count against `taskHoldTicks` progression.

**H4 — Unassigned station targeted via geometry fallback (likely,
compounds H1).** When no icons are visible, `nearestTaskStation` picks
by geometry alone. The player might not have a task there; the server
won't complete it; the bot holds A forever at an unassigned station.
Diagnostic: check whether `visibleTaskIcons` was non-empty before lock.

**H5 — Radar dots unused for selection (confirmed by code).** The
perception pipeline scans radar dots and stores them in
`belief.percep.radarDots`, but `task_completing.nim` never references
them. This means the bot has no off-screen assignment evidence.

**H3 — Icon flicker during hold requires debounce (moderate).** Task
icons may animate during interaction, causing intermittent sprite
matches. A naive "icon gone = done" check would false-positive.
Modulabot uses `ICON_MISS_COMPLETE_TICKS = 24` consecutive miss
frames as debounce.

**H2 — Position too imprecise for server interaction (unlikely).** The
4 px margin in `isInsideTaskRect` plus the server's own interaction
radius should be sufficient. Camera jitter during hold (no movement
buttons) wouldn't cause drift in the server's actual player position.

**Implementation plan:** See `IMPL_PLAN.md` § 6.1.

---

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
