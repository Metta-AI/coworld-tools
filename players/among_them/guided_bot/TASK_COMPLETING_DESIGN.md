# Phase 6.1 — `task_completing` Lifecycle Design

> **Scope:** Complete the `task_completing` mode with hold lifecycle,
> completion detection, belief-layer task state, radar-dot checkout
> latching, and trace events. This is the P0 item from `IMPL_PLAN.md`.
>
> **Parent doc:** `DESIGN.md`. This document refines §3 layer 4
> (belief.tasks), §5.3 (`task_completing` params), §5.7 (ghosts), §6
> (action intent / `DisciplineTaskHold`), and §11.2 (trace events).
> It does not contradict the parent; it fills gaps.
>
> **Reference implementation:** modulabot's crewmate policy
> (`among_them/modulabot/policies/crewmate.py`). We take inspiration
> per DESIGN.md §12.2 — "implement task_completing fresh, informed by
> modulabot's code but not copied."
>
> Last updated: 2026-05-01

---

## 1. Problem statement

The `task_completing` mode navigates to a task station and enters
`DisciplineTaskHold`, then holds A indefinitely. It never detects
completion, never selects a new target, and never releases the hold.
The bot spends 75% of a 30 s match pressing A at one station.

Three things are missing:

1. A hold-duration cap (the server accepts the task within ~72 ticks).
2. Completion confirmation (the task icon disappears when the server
   accepts the task — this is the authoritative signal).
3. Target re-selection after completion or timeout.

Additionally, target selection is weak: when no task icons are visible,
the mode falls back to `nearestTaskStation` (pure geometry), which can
pick unassigned stations. Radar dots — which the perception pipeline
scans every frame — are never used for selection.

---

## 2. Design overview

The fix has four parts:

1. **Hold lifecycle** in `task_completing.decide()` — navigate, hold,
   confirm, re-select.
2. **Belief-layer task state** in `belief.tasks` — a per-station state
   machine populated in the belief-merge stage, readable by any mode
   and by the LLM via snapshots.
3. **Radar-dot checkout latching** — a second-tier selection signal
   confirming task assignment even when the station is off-screen.
4. **Trace events** — `task_started`, `task_completed`, `task_abandoned`
   wired through `bot.nim`.

---

## 3. Hold lifecycle

The mode's `decide()` function gains a three-phase state machine,
tracked in `ModeScratch`.

### 3.1 Phases

```
     ┌─────────┐      isInsideTaskRect     ┌──────┐     timer=0     ┌─────────┐
     │ Navigate ├─────────────────────────► │ Hold ├───────────────► │ Confirm │
     └────┬────┘                            └──────┘                └────┬────┘
          │                                                              │
          │  ◄── on completion OR timeout ──────────────────────────────┘
          │
          ▼
   (re-select target, loop)
```

| Phase | Discipline | Duration | Behavior | Exit |
|---|---|---|---|---|
| **Navigate** | `DisciplineNormal` | Variable | A\* to station passable centre (`passableCX/CY`) | Bot enters task rect (4 px margin) |
| **Hold** | `DisciplineTaskHold` | `TaskHoldTicks` (84) | Press A, no movement | Timer expires → Confirm |
| **Confirm** | `DisciplineNoOp` | Up to `TaskConfirmWindowTicks` (48) | Stay still, watch icon | Icon absent `TaskIconMissCompleteTicks` (24) consecutive frames → complete. OR deadline tick reached → timeout. |

### 3.2 Phase transitions

**Navigate → Hold:** When `isInsideTaskRect(selfX, selfY, station)`
becomes true. On entry: set `tcPhase = Hold`, `tcHoldRemaining =
TaskHoldTicks`, record `tcHoldStartTick` for the `task_started` trace
event.

**Hold → Confirm:** When `tcHoldRemaining` decrements to 0. On entry:
set `tcPhase = Confirm`, `tcConfirmDeadlineTick = tick +
TaskConfirmWindowTicks`, `tcConfirmMissCount = 0`.

**Confirm → Navigate (completion):** When `tcConfirmMissCount >=
TaskIconMissCompleteTicks` while the bot remains inside the station
rect. The icon has been absent for 24 consecutive frames — the server
accepted the task. Actions:
- Mark `belief.tasks.slots[idx].state = TaskCompleted` (via a helper
  the mode calls; see §4.5).
- Clear `scratch.tcLockedTaskIndex = -1`.
- Set `tcPhase = Navigate`.
- Emit `task_completed` trace event.
- Re-run target selection on the same tick (the Navigate phase's
  first action is target selection).

**Confirm → Navigate (timeout):** When `tick >= tcConfirmDeadlineTick`
without the miss count reaching the threshold. The task may not be
assigned to us, or the icon matched intermittently. Actions:
- Clear `scratch.tcLockedTaskIndex = -1`.
- Clear `belief.tasks.slots[idx].checkout = false` if it was latched
  via radar (un-latch so the station isn't re-selected immediately).
- Set `tcPhase = Navigate`.
- Emit `task_abandoned` trace event with reason `confirm_timeout`.
- Re-run target selection.

### 3.3 Icon miss counting during Confirm

Each tick in the Confirm phase:

1. Check whether any `belief.percep.visibleTaskIcons` entry matches
   the currently-locked station. A match means: the icon's world
   position (screen pos + camera offset) falls within the station
   rect (16 px margin, matching `findTaskForIcon`).
2. If a matching icon is found: reset `tcConfirmMissCount = 0`.
3. If no matching icon is found: increment `tcConfirmMissCount`.

This debounce handles icon animation flicker. Modulabot uses the
same 24-frame threshold (`ICON_MISS_COMPLETE_TICKS`).

### 3.4 Hold phase behavior

During Hold, the mode emits:
```nim
ActionIntent(
  steerTo: station centre,
  steerValid: true,
  pressA: true,
  discipline: DisciplineTaskHold
)
```

The action layer translates `DisciplineTaskHold` into `ButtonA` with
no directional buttons (already implemented in `action.nim:312-318`).

Note: `station centre` in all three phases refers to the precomputed
passable centre (`passableCX/CY`), not the raw geometric centre of
the task rect. The raw centre `(ts.x + ts.w div 2, ts.y + ts.h div
2)` may fall on an impassable walk-mask pixel, which causes `findPath`
to return an empty path. `passableCX/CY` is snapped to the nearest
walkable pixel at init time in `data.nim:loadMap()`. See DESIGN.md
§6.3 for the action-layer fallback that also defends against this.

### 3.5 Confirm phase behavior

During Confirm, the mode emits:
```nim
ActionIntent(
  steerTo: station centre,
  steerValid: true,
  pressA: false,
  discipline: DisciplineNoOp
)
```

No buttons pressed. The bot stands still and watches for the icon to
disappear.

### 3.6 Ghost variant

Per DESIGN.md §5.7, ghosts use `task_completing` with
`tcAbandonOnNearbyBody: false`. The hold lifecycle applies identically
to ghosts — ghosts still press A to complete tasks, and the server
still removes the task icon on completion. The only difference is:
- The action layer uses straight-line steering (no walk mask) for the
  Navigate phase — this is already handled by `applyIntent`'s ghost
  check.
- No body-reporting reflex fires (already gated by `not isGhost` in
  `reflex.nim`).

### 3.7 Interruptions

If a mode switch occurs during Hold or Confirm (reflex fires, LLM
directive arrives, TTL expires), the standard `onExit` runs and
scratch resets. When the bot re-enters `task_completing` later, it
starts fresh in Navigate with no locked target. This is correct:
the interrupted hold may or may not have succeeded, and the belief's
task-state machine (§4) tracks the ground truth independently.

---

## 4. Belief-layer task state

Per DESIGN.md §3 layer 4, `belief.tasks` tracks per-task state.
Currently `TaskState` is declared but never populated. This section
specifies the population logic.

### 4.1 Per-task fields

```nim
TaskSlotState = enum
  TaskNotDoing     ## No evidence this task is ours.
  TaskCheckout     ## Radar dot matched — probably assigned, not yet confirmed.
  TaskConfirmed    ## Icon visible at this station — definitely assigned.
  TaskCompleted    ## Hold confirmed — icon disappeared after A-hold.

TaskSlot = object
  state: TaskSlotState
  checkout: bool          ## Radar-dot latch (persists across frames).
  iconVisibleTick: int    ## Last tick an icon was seen at this station.
  iconMissCount: int      ## Consecutive frames with no icon while on-screen.
  resolvedNotMine: bool   ## Negative evidence: station inspected, no icon.
```

`belief.tasks.slots` is a `seq[TaskSlot]` of length
`referenceData.map.tasks.len`, initialized once (lazily on first
gameplay frame, or in `initTaskState`).

### 4.2 State transitions (in belief-merge stage)

These run every frame in a new `updateTaskState` proc called from
`bot.nim` after `mergeTaskPercept`, before `reconcileDirective`.

**For each task station `i`:**

1. **Icon visible?** Check whether any `belief.percep.visibleTaskIcons`
   entry matches station `i` (same `findTaskForIcon` logic, reused).
   - If yes: `slots[i].state = TaskConfirmed`,
     `slots[i].iconVisibleTick = tick`, `slots[i].iconMissCount = 0`.
   - If no, AND the station's expected icon position is fully
     on-screen (the "clear area" check — the icon rect must be
     within the screen bounds with `TaskClearScreenMargin = 8` px
     margin so we're confident the icon *would* be visible if it
     existed): increment `slots[i].iconMissCount`.
   - If no, AND the station is off-screen or occluded: leave
     `iconMissCount` unchanged (don't count frames where we
     *can't* see the icon).

2. **Negative evidence (not mine).** If `iconMissCount >=
   TaskIconMissResolveFrames` (24) and the task is not currently
   being held or confirmed by `task_completing`:
   `slots[i].resolvedNotMine = true`, `slots[i].checkout = false`.
   This means we visited the station, the icon area was clearly
   visible for 24 frames, and no icon appeared — the server didn't
   assign this task to us.

3. **Radar-dot checkout.** (See §5 below.) If a radar dot matches
   station `i`'s projected screen position: `slots[i].checkout =
   true`. If the slot was `TaskNotDoing`, promote to `TaskCheckout`.

4. **Completion.** Only `task_completing.decide()` marks
   `TaskCompleted` (via a proc call during the Confirm → Navigate
   transition). The belief-merge stage does not autonomously mark
   completion — that's a policy decision, not a perception truth.
   The belief layer tracks the *evidence*; the mode acts on it.

### 4.3 Skips

- Interstitial frames: skip all task-state updates.
- Alive imposters: skip icon updates (imposters don't have task
  icons). Radar-dot updates still run (imposter ghosts have tasks).
- Stations marked `TaskCompleted` or `resolvedNotMine`: skip further
  updates (terminal states within a round).

### 4.4 Round reset

On role-reveal interstitial (new round): reset all slots to
`TaskNotDoing`, clear `checkout`, `resolvedNotMine`,
`iconMissCount`. This happens in the existing `mergePercept` path
where the belief resets for a new round.

### 4.5 Mode-belief interaction

The mode doesn't write to `belief.tasks` directly (DESIGN.md §3
invariant: belief updated only by the perceive/update stage). Instead
the mode communicates completion via a flag:

```nim
# In ModeScratch:
tcCompletedTaskIndex: int   ## Set by Confirm→Navigate; -1 otherwise.

# In bot.nim, after decide():
if scratch.tcCompletedTaskIndex >= 0:
  belief.tasks.slots[scratch.tcCompletedTaskIndex].state = TaskCompleted
  scratch.tcCompletedTaskIndex = -1
```

This preserves the invariant: the mode signals its conclusion, and
the bot pipeline applies it to the belief in the update stage.

---

## 5. Radar-dot checkout latching

Radar dots are yellow pixels on the screen border that the server
renders to indicate off-screen task assignments. The perception
pipeline scans them every frame (`perception/tasks.nim:scanRadarDots`)
and stores them in `belief.percep.radarDots`.

### 5.1 Matching radar dots to task stations

For each task station, compute its **projected radar-dot position**:
the point on the screen border closest to the station's world
position, as seen from the current camera.

```nim
proc projectedRadarDot(station: TaskStation,
                       camX, camY: int): (int, int) =
  ## Where the server would draw a radar dot for this station.
  ## The dot is clamped to the screen border (0..127 x 0..127).
  let wx = station.x + station.w div 2
  let wy = station.y + station.h div 2
  let sx = wx - camX - SpriteDrawOffX
  let sy = wy - camY - SpriteDrawOffY
  # Clamp to screen edges.
  let cx = clamp(sx, 0, ScreenWidth - 1)
  let cy = clamp(sy, 0, ScreenHeight - 1)
  (cx, cy)
```

A radar dot matches station `i` if any dot in
`belief.percep.radarDots` is within Chebyshev distance
`RadarMatchTolerance = 2` of the projected position.

### 5.2 Checkout latch semantics

- When a radar dot matches station `i`:
  `slots[i].checkout = true`.
- Checkout **persists** across frames (latched). A single radar dot
  sighting is sufficient — the server only renders dots for assigned
  tasks, so this is high-confidence evidence.
- Checkout is **cleared** on:
  - Confirm timeout (§3.2) — the hold didn't confirm; maybe the
    assignment is stale.
  - Negative evidence (§4.2) — 24 frames of clear icon area with
    no icon; the task isn't ours.
  - Round reset (§4.4).

### 5.3 Where checkout runs

In `updateTaskState` (§4.2, step 3), every frame, after icon checks.
Only when `localized` is true (need camera for projection).

---

## 6. Target selection

Target selection runs at the start of the Navigate phase (when
`tcLockedTaskIndex < 0`). It replaces the current two-path logic
(icon or nearest) with a three-tier priority system.

### 6.1 Selection tiers

Evaluated in order. First tier with candidates wins.

**Tier 1 — Icon-visible stations.** Stations where
`slots[i].state == TaskConfirmed` (icon is currently visible on
screen). Pick the nearest by Manhattan distance from self. This is
the strongest evidence: the server is rendering the icon right now.

**Tier 2 — Checkout-latched stations.** Stations where
`slots[i].checkout == true` and `state != TaskCompleted` and
`!resolvedNotMine`. These have been confirmed by radar dots but the
icon isn't currently visible (station is off-screen or icon is
temporarily not matching). Pick the nearest.

**Tier 3 — Unresolved stations (geometry fallback).** Stations where
`state == TaskNotDoing` and `!resolvedNotMine`. We have no evidence
for or against. Pick the nearest. This is the weakest tier — the
station might not be assigned to us, but we have nothing better.

Skip stations where `state == TaskCompleted` or `resolvedNotMine ==
true` in all tiers.

### 6.2 Target hysteresis

Once a target is locked (`scratch.tcLockedTaskIndex >= 0`), keep it
for at least `TaskCommitTicks = 48` (~2 s) before reconsidering.
This prevents thrashing between stations when icon visibility
flickers.

If the locked target becomes `TaskCompleted` or `resolvedNotMine`,
break the lock immediately regardless of the commit window.

### 6.3 LLM-directed targets

The `task_completing` params include `tcTarget: TaskTarget` with
kinds `TgtIndex`, `TgtNearestMandatory`, `TgtNearestAny`,
`TgtSpecificRoom`. When the LLM provides a `TgtIndex`, the mode
locks that station directly (skipping the tier selection). The tier
system is the *fallback* path, used by the default directive
(`TgtNearestMandatory`) and when the LLM-specified target is
completed or invalid.

---

## 7. Scratch state changes

The `ModeScratch` variant for `ModeTaskCompleting` gains new fields:

```nim
of ModeTaskCompleting:
  tcLockedTaskIndex: int          ## -1 if no target. (exists)
  tcEnterTick: int                ## Tick when mode was entered. (exists)
  tcPhase: TaskPhase              ## Navigate / Hold / Confirm. (new)
  tcHoldRemaining: int            ## Ticks left in Hold phase. (new)
  tcHoldStartTick: int            ## Tick when Hold began. (new, for trace)
  tcConfirmDeadlineTick: int      ## Tick when Confirm times out. (new)
  tcConfirmMissCount: int         ## Consecutive icon-absent frames. (new)
  tcCompletedTaskIndex: int       ## Set on completion for bot.nim to apply. (new)
  tcLockTick: int                 ## Tick when target was locked. (new, for hysteresis)

TaskPhase = enum
  TpNavigate
  TpHold
  TpConfirm
```

`onEnter` initialises all new fields to their zero/sentinel values.
`tcPhase = TpNavigate`, `tcLockedTaskIndex = -1`,
`tcCompletedTaskIndex = -1`.

---

## 8. Tuning constants

All new constants live in `tuning.nim`.

| Constant | Value | Rationale |
|---|---|---|
| `TaskHoldTicks` | 84 | Server task completion window is ~72 ticks. 84 adds a 12-tick pad to ensure we don't release early. Matches modulabot. |
| `TaskConfirmWindowTicks` | 48 | Post-hold observation window. If neither icon disappearance nor timeout fires in 48 ticks, the task wasn't ours. Matches modulabot. |
| `TaskIconMissCompleteTicks` | 24 | Consecutive frames without the icon before declaring completion. Debounces sprite-match flicker. Matches modulabot. |
| `TaskIconMissResolveFrames` | 24 | Consecutive frames without the icon while on-screen before declaring "not mine" (negative evidence in the belief-layer). Same threshold, different purpose. |
| `TaskClearScreenMargin` | 8 | Pixel margin for the "icon area is fully on-screen" check. If the expected icon position is within 8 px of the screen edge, we can't be confident the icon area is fully visible, so we don't count an icon miss. Matches modulabot. |
| `RadarMatchTolerance` | 2 | Chebyshev distance for radar-dot → projected-position matching. Matches modulabot. |
| `TaskCommitTicks` | 48 | Hysteresis: keep the current target for at least 48 ticks before reconsidering. Prevents flicker between stations. Matches modulabot. |

---

## 9. Trace events

Three new event kinds, wired in `bot.nim` after `decide()` returns.

### 9.1 `task_started`

Emitted when the Hold phase begins (Navigate → Hold transition).

```json
{ "t": <tick>, "kind": "task_started",
  "task_index": <int>, "station_name": "<string>",
  "selection_tier": "icon" | "checkout" | "geometry" }
```

### 9.2 `task_completed`

Emitted when the Confirm phase succeeds (icon absent for 24 frames).

```json
{ "t": <tick>, "kind": "task_completed",
  "task_index": <int>, "station_name": "<string>",
  "hold_duration_ticks": <int>,
  "confirm_duration_ticks": <int> }
```

### 9.3 `task_abandoned`

Emitted when the Confirm phase times out, or when a mode switch
interrupts an active Hold/Confirm.

```json
{ "t": <tick>, "kind": "task_abandoned",
  "task_index": <int>, "station_name": "<string>",
  "reason": "confirm_timeout" | "mode_switch" | "target_invalid",
  "phase_at_abandon": "hold" | "confirm",
  "hold_ticks_elapsed": <int> }
```

For mode-switch abandonment, the `onExit` handler checks whether
the bot was in Hold or Confirm and emits the event. This requires
`onExit` to receive the trace writer — either passed via a module-
level reference or via the bot pipeline emitting the event after
`onExit` returns (preferred, to keep modes trace-unaware).

**Implementation choice:** `bot.nim:switchMode` already runs after
`onExit`. It can check whether the exiting mode was
`ModeTaskCompleting` and the scratch phase was `TpHold` or
`TpConfirm`, and emit `task_abandoned` with reason `mode_switch`.
This keeps modes decoupled from the trace system.

---

## 10. Snapshot impact

`belief.tasks` is now populated, so `snapshot.nim:renderSnapshot`
should include it. The LLM sees:

```json
"task_state": {
  "stations": [
    { "index": 0, "name": "reactor",
      "state": "not_doing" | "checkout" | "confirmed" | "completed",
      "checkout": true | false,
      "resolved_not_mine": true | false }
  ],
  "in_progress_index": <int> | null
}
```

This replaces the placeholder `task_state` block in DESIGN.md §8.3.
`in_progress_index` is the `tcLockedTaskIndex` from scratch (exposed
via a helper, not by reading scratch directly).

---

## 11. Files changed

| File | Change |
|---|---|
| `types.nim` | Add `TaskPhase` enum, `TaskSlotState` enum, expand `TaskSlot` fields, expand `ModeScratch.ModeTaskCompleting` variant |
| `tuning.nim` | Add 7 new constants (§8) |
| `belief.nim` | Add `initTaskSlots`, `updateTaskState` proc, call from pipeline |
| `bot.nim` | Call `updateTaskState` after `mergeTaskPercept`; handle `tcCompletedTaskIndex` after decide; emit trace events (§9); emit `task_abandoned` on mode switch |
| `modes/task_completing.nim` | Rewrite `decide()` with 3-phase state machine (§3); update `onEnter` for new scratch fields |
| `perception/geometry.nim` | Add `projectedRadarDot` helper (§5.1), `taskIconOnScreen` helper for clear-area check |
| `snapshot.nim` | Include `belief.tasks` in the LLM snapshot (§10) |
| `trace.nim` | Add `logTaskStarted`, `logTaskCompleted`, `logTaskAbandoned` procs |
| `DESIGN.md` | Backfill §3 layer 4, §5.3 `task_completing` params, §11.2 new event kinds |

---

## 12. Implementation plan

Ordered steps. Each step should compile and pass existing tests
before proceeding.

### Step 1 — Type foundations

- Add `TaskPhase` enum (`TpNavigate`, `TpHold`, `TpConfirm`) to
  `types.nim`.
- Add `TaskSlotState` enum (`TaskNotDoing`, `TaskCheckout`,
  `TaskConfirmed`, `TaskCompleted`) to `types.nim`.
- Expand `TaskSlot` with new fields: `state: TaskSlotState`,
  `checkout: bool`, `iconVisibleTick: int`, `iconMissCount: int`,
  `resolvedNotMine: bool`.
- Expand `ModeScratch.ModeTaskCompleting` with new fields (§7).
- Add tuning constants to `tuning.nim` (§8).
- **Verify:** existing tests compile and pass (no behavioral change).

### Step 2 — Belief-layer task state

- Add `initTaskSlots` to `belief.nim`: allocates `slots` seq to
  `referenceData.map.tasks.len`, all `TaskNotDoing`.
- Add `updateTaskState(belief, tick)` to `belief.nim`:
  implements §4.2 (icon matching, miss counting, negative evidence).
  Does NOT include radar checkout yet (step 3).
- Wire `updateTaskState` into `bot.nim` after `mergeTaskPercept`.
- Add `projectedRadarDot` and `taskIconOnScreen` helpers to
  `perception/geometry.nim`.
- **Verify:** existing tests compile and pass. Add a unit test in
  a new or existing test file that constructs a belief with known
  icon positions and verifies state transitions.

### Step 3 — Radar-dot checkout latching

- Extend `updateTaskState` to include the radar-dot checkout logic
  (§5).
- Uses `projectedRadarDot` from step 2.
- **Verify:** unit test with synthetic radar dots at known positions
  verifies checkout latching and clearing.

### Step 4 — Hold lifecycle in `task_completing.decide()`

- Rewrite `decide()` with the 3-phase state machine (§3).
- Navigate phase: tier-based target selection (§6) reading from
  `belief.tasks.slots`.
- Hold phase: emit `DisciplineTaskHold` for `tcHoldRemaining` ticks.
- Confirm phase: icon-miss counting, completion, timeout.
- On completion: set `scratch.tcCompletedTaskIndex`.
- Update `onEnter` to initialize new scratch fields.
- Wire `tcCompletedTaskIndex` handling in `bot.nim` after `decide()`
  (§4.5).
- **Verify:** fallback test still passes (the mode now has richer
  behavior but should still produce non-NOOP actions). Add a
  dedicated test that replays fixture frames through the full bot
  pipeline and verifies: (a) the bot enters Hold within N frames of
  reaching a station, (b) the bot exits Hold after TaskHoldTicks,
  (c) if the icon disappears, the bot marks completion and
  re-selects.

### Step 5 — Trace events

- Add `logTaskStarted`, `logTaskCompleted`, `logTaskAbandoned` to
  `trace.nim`.
- Wire `task_started` emission in `bot.nim` when scratch transitions
  to `TpHold`.
- Wire `task_completed` emission in `bot.nim` when
  `tcCompletedTaskIndex >= 0`.
- Wire `task_abandoned` emission in `bot.nim:switchMode` when the
  exiting mode is `ModeTaskCompleting` and scratch phase is
  `TpHold` or `TpConfirm`.
- **Verify:** run a traced local match and confirm events appear
  in `events.jsonl`.

### Step 6 — Snapshot update

- Update `snapshot.nim:renderSnapshot` to include `belief.tasks`
  (§10).
- **Verify:** run a traced match at `full` level and confirm
  `snapshots.jsonl` includes `task_state`.

### Step 7 — DESIGN.md backfill

- Update DESIGN.md §3 layer 4 to reflect the populated task state.
- Update §5.3 `task_completing` params to note the hold lifecycle.
- Update §11.2 with the three new event kinds.
- Update the phase table in README.md.
- Mark 6.1 as done in IMPL_PLAN.md.

### Step 8 — Full test pass + local match validation

- Run all 8 existing test suites + the new task-lifecycle tests.
- Run a 30 s local match with tracing and verify:
  - Bot reaches a task station within ~140 ticks.
  - Holds A for ~84 ticks.
  - Either confirms completion (icon disappears) or times out and
    moves to the next station.
  - Multiple tasks attempted in a single match.
- Library build succeeds.
- Compare behavior to the pre-fix baseline (held A at one station
  for 75% of the match).
