# Task Completing Mode — Design Document

> **Canonical reference** for the `task_completing` mode handler. All
> task-completing design details live here; `DESIGN.md` contains only a
> brief overview and cross-reference.
>
> **Implementation:** `modes/task_completing.nim` (324 LOC)
>
> Last updated: 2026-05-05

---

## 1. Purpose and role

The `task_completing` mode is the crewmate's core gameplay loop. It is:

- **The crewmate default directive** (`mode_registry.nim:106`). When no
  LLM directive is active, an alive crewmate runs `task_completing`
  with `tcTarget: TgtNearestMandatory, tcAbandonOnNearbyBody: true`.
- **The ghost default directive** (`mode_registry.nim:102`). Ghosts
  always run `task_completing` with `tcAbandonOnNearbyBody: false`.
  The ghost override in `bot.nim:231-232` forces this mode regardless
  of LLM directives.
- **The target of the `reconcileDirective` idle→task transition.**
  When the bot starts in `ModeIdle` (unknown role) and the role is
  detected as crewmate, `reconcileDirective` immediately switches to
  the crewmate default (this mode).

The mode is **legal for** any alive crewmate or any ghost (`isLegalFor`
in `modes/task_completing.nim:32-33` checks `role == RoleCrewmate or
isGhost`). It is **not legal** for alive imposters (they use
`pretending` or `hunting` instead).

---

## 2. Mode parameters

The LLM (or default system) sets these when issuing a `task_completing`
directive:

```text
task_completing {
  tcTarget: TaskTarget     # Which station to pursue
  tcAbandonOnNearbyBody: bool  # Whether body-seen reflex applies
}
```

### 2.1 TaskTarget

```nim
TaskTargetKind = enum
  TgtIndex              # Go to a specific station index.
  TgtNearestMandatory   # Tiered selection (default path).
  TgtNearestAny         # Same as NearestMandatory (reserved for future use).
  TgtSpecificRoom       # Go to a task in a specific room (reserved).

TaskTarget = object
  kind: TaskTargetKind
  taskIndex: int         # TgtIndex: which station.
  roomId: int            # TgtSpecificRoom: which room.
```

Implementation in `types.nim:208-217`.

### 2.2 Default params

From `modes/task_completing.nim:36-40`:
- `tcTarget: TaskTarget(kind: TgtNearestMandatory, taskIndex: -1, roomId: -1)`
- `tcAbandonOnNearbyBody: not belief.self.isGhost`

Ghosts disable body-abandonment because they can't report bodies and
the reflex system already gates body→reporting on `not isGhost`.

---

## 3. Decision logic overview

`decide()` evaluates each tick:

1. **Pre-check** — if not localized or no task stations exist, emit
   `noOpIntent()`.
2. **Target validation** — if the locked target's belief state is
   `TaskCompleted` or `resolvedNotMine`, unlock immediately and fall
   through to selection.
3. **Hysteresis** — if a target is locked and `TaskCommitTicks` (48)
   haven't elapsed since locking, keep the current target (prevents
   oscillation).
4. **Target selection** — if no target is locked, run the 3-tier
   priority system (§6) to pick one.
5. **Phase dispatch** — execute the current phase (Navigate, Hold,
   or Confirm).

```text
     ┌─────────┐      isInsideTaskRect     ┌──────┐     timer=0     ┌─────────┐
     │ Navigate ├─────────────────────────► │ Hold ├───────────────► │ Confirm │
     └────┬────┘                            └──────┘                └────┬────┘
          │                                                              │
          │  ◄── on completion OR timeout ──────────────────────────────┘
          │
          ▼
   (re-select target, loop)
```

---

## 4. Hold lifecycle

The mode's three-phase state machine, tracked in scratch via
`tcPhase: TaskPhase`.

### 4.1 Navigate phase

- **Discipline:** `DisciplineNormal` (waypoint-backed pathfinding).
- **Goal:** the locked station's passable centre (`passableCX/CY`).
- **Exit condition:** bot enters the station's bounding rect
  (`isInsideTaskRect` — exact match to server's check at
  `sim.nim:2184-2185`, no margin).
- **Duration:** variable (depends on distance and path complexity).

### 4.2 Hold phase

- **Discipline:** `DisciplineTaskHold` — press A, no movement.
- **Duration:** `TaskHoldTicks` (84 ticks, ~3.5s). The server accepts
  the task within ~72 ticks; the 12-tick pad ensures the hold is never
  released prematurely.
- **Negative evidence:** Hold shields only icon-confirmed targets from
  `resolvedNotMine` pruning. If the locked station is already
  `TaskConfirmed`, icon disappearance during Hold is treated as likely
  server acceptance. Checkout-only holds (no icon ever seen) remain
  unshielded so wrong-task detection still prunes quickly.
- **Exit condition:** `tcHoldRemaining` decrements to 0.
- **On entry:** sets `tcHoldRemaining = TaskHoldTicks`,
  `tcHoldStartTick = belief.tick`.

### 4.3 Confirm phase

- **Discipline:** `DisciplineNoOp` — stand still, no buttons.
- **Purpose:** watch for the task icon to disappear (the server removes
  it on successful task completion).
- **Negative-evidence shielding:** the locked station is shielded from
  `resolvedNotMine` pruning during Confirm because icon absence is the
  success signal here, not evidence that the task is unassigned.
- **Duration:** up to `TaskConfirmWindowTicks` (48 ticks, ~2s).
- **Completion detection:** icon absent for `TaskIconMissCompleteTicks`
  (24) consecutive frames → task completed.
- **Timeout:** `tcConfirmDeadlineTick` reached without enough misses →
  task was likely not assigned to us.

### 4.4 Phase transitions

**Navigate → Hold:** `isInsideTaskRect(selfX, selfY, station)` becomes
true. On entry: `tcPhase = TpHold`, `tcHoldRemaining = TaskHoldTicks`,
`tcHoldStartTick = tick`.

**Hold → Confirm:** `tcHoldRemaining` hits 0. On entry:
`tcPhase = TpConfirm`, `tcConfirmDeadlineTick = tick +
TaskConfirmWindowTicks`, `tcConfirmMissCount = 0`.

**Confirm → Navigate (completion):** `tcConfirmMissCount >=
TaskIconMissCompleteTicks`. Actions:
- Sets `tcCompletedTaskIndex = targetIdx` (consumed by `bot.nim`
  to mark `belief.tasks.slots[idx].state = TaskCompleted`).
- Clears `tcLockedTaskIndex = -1`.
- Sets `tcPhase = TpNavigate`.
- Immediately re-runs target selection on the same tick.

**Confirm → Navigate (timeout):** `tick >= tcConfirmDeadlineTick`
without the miss count reaching threshold. Actions:
- Clears `tcLockedTaskIndex = -1`.
- Sets `tcPhase = TpNavigate`.
- Re-runs target selection.

---

## 5. Belief-layer task state

The mode operates on `belief.tasks` — a per-station state machine
populated by `updateTaskState` in the belief-merge stage (called every
frame from `bot.nim:362-370`, after `mergeTaskPercept`).

### 5.1 Per-station fields

```nim
TaskSlotState = enum
  TaskNotDoing     # No evidence this task is ours.
  TaskCheckout     # Radar dot matched — probably assigned.
  TaskConfirmed    # Icon visible at this station — definitely assigned.
  TaskCompleted    # Hold confirmed — icon disappeared after A-hold.

TaskSlot = object
  state: TaskSlotState
  checkout: bool          # Radar-dot latch (persists across frames).
  iconVisibleTick: int    # Last tick an icon was seen at this station.
  iconMissCount: int      # Consecutive icon-absent frames while on-screen.
  resolvedNotMine: bool   # Negative evidence: station inspected, no icon.
  radarExclusionCount: int # Consecutive off-screen frames with no matching dot.
```

Implementation in `types.nim:366-378`.

### 5.2 State transitions (updateTaskState)

Run every gameplay frame in `belief.nim:266-386`. For each station `i`:

1. **Icon visible?** Check whether any `visibleTaskIcons` entry matches
   the station (icon world position within 16 px margin of station rect).
   - Yes: `state = TaskConfirmed`, `iconVisibleTick = tick`,
     `iconMissCount = 0`.
   - No, AND icon area is fully on-screen (`taskIconOnScreen` with
     `TaskClearScreenMargin = 8`): increment `iconMissCount`.
   - No, AND off-screen/near edge: don't count (can't see the icon).

2. **Negative evidence.** If `iconMissCount >= TaskIconMissResolveFrames`
   (2) and the station is not currently being confirmed:
   `resolvedNotMine = true`, `checkout = false`, `state = TaskNotDoing`.
   Hold-phase targets are shielded only when already `TaskConfirmed`;
   checkout-only holds remain unshielded.

3. **Radar-dot checkout.** If a radar dot matches the station's
   projected screen-edge position (Chebyshev distance ≤
   `RadarMatchTolerance = 2`): `checkout = true`. If state was
   `TaskNotDoing`, promote to `TaskCheckout`. This also resets
   `radarExclusionCount`.

4. **Radar-ray exclusion.** If the station is off-screen and its
   projected screen-edge position is far from every detected radar dot
   for `RadarExclusionFrames` consecutive frames, mark it
   `resolvedNotMine = true`, clear checkout, and return it to
   `TaskNotDoing`.

### 5.3 Skips

- Interstitial frames: skip all updates.
- Alive imposters: skip icon checks (imposters don't have task icons).
  Radar-dot updates still run (imposter ghosts have tasks).
- Stations at `TaskCompleted` or `resolvedNotMine`: skip (terminal
  states within a round).

### 5.4 Radar-ray exclusion (negative evidence from dot absence)

In addition to icon-miss pruning (§5.2) which requires the task to be
on-screen, the belief layer proactively excludes off-screen tasks using
radar dot absence.

**Principle:** the server draws a yellow radar dot on the screen edge
for every assigned off-screen task. If a task's projected dot position
is far from ALL detected dots for multiple consecutive frames, the task
cannot be assigned to us.

**Algorithm** (runs per-frame in `updateTaskState`, after the checkout
pass):

1. Skip if: not localized, alive imposter, task on-screen, or fewer
   than `RadarExclusionMinDots` (1) dots detected.
2. Compute the task's projected dot position via `projectedRadarDot`
   (ray-clip from player screen pos to icon screen pos, clipped to
   viewport boundary).
3. Find the nearest detected dot (Chebyshev distance).
4. If nearest > `RadarExclusionDistance` (8 px): increment
   `radarExclusionCount` (saturates at `RadarExclusionFrames`).
5. If nearest ≤ threshold: reset counter to 0.
6. When counter reaches `RadarExclusionFrames` (12): the task is
   **soft-excluded** from tier-3 target selection. Unlike icon-miss,
   this does NOT set `resolvedNotMine` — the exclusion is reversible.
   The task re-enters tier-3 when the counter resets (bot moves, dot
   aligns again). Tier-1 (icon) and tier-2 (checkout) ignore the
   counter entirely.

**Shielding:** not needed — soft exclusion does not permanently latch
state; the counter naturally resets when evidence changes.

**Resets:** counter resets on: round reset, checkout latch fires (dot
matched), task comes on-screen, localization loss.

**Why soft?** Radar-ray evidence is positional: from the bot's current
location a task's direction doesn't match any dot. But as the bot moves
angles change, and a previously-excluded task may align with a dot from
a new position. Permanent exclusion causes deadlocks when the dot set
shrinks (tasks completed → fewer dots → remaining tasks falsely excluded
from earlier positions).

**Parameters** (in `tuning.nim`):
- `RadarExclusionDistance = 8` — 4× match tolerance; conservative.
- `RadarExclusionFrames = 12` — ~0.5s at 24 Hz.
- `RadarExclusionMinDots = 1` — safety: don't exclude with 0 dots.

### 5.5 Round reset

On role-reveal interstitial: `resetTaskSlots` clears all slots to
`TaskNotDoing`, clears `checkout`, `resolvedNotMine`, `iconMissCount`,
and `radarExclusionCount`.

### 5.6 Mode-belief interaction

The mode doesn't write to `belief.tasks` directly (DESIGN.md §3
invariant: belief updated only by the perceive/update stage). The mode
signals completion via `scratch.tcCompletedTaskIndex`. After `decide()`
returns, `bot.nim:530-545` reads this field and applies the state
change:

```nim
if bot.modeScratch.tcCompletedTaskIndex >= 0:
  belief.tasks.slots[ci].state = TaskCompleted
  bot.modeScratch.tcCompletedTaskIndex = -1
```

---

## 6. Target selection

Runs at the start of the Navigate phase when no target is locked
(`tcLockedTaskIndex < 0`). Implemented in `selectTarget`
(`modes/task_completing.nim:80-137`).

### 6.1 Three-tier priority system

Evaluated in order. First tier with candidates wins.

**Tier 1 — Icon-visible stations** (`TierIcon`). Stations where
`slots[i].state == TaskConfirmed` and `not resolvedNotMine`. Pick the
nearest by Manhattan distance. This is the strongest evidence: the
server is rendering the icon right now.

**Tier 2 — Checkout-latched stations** (`TierCheckout`). Stations
where `slots[i].checkout == true`, `state != TaskCompleted`, and
`not resolvedNotMine`. Pick the nearest. These have radar-dot evidence
but the icon isn't currently visible (station is off-screen).

**Tier 3 — Unresolved stations** (`TierGeometry`). Stations where
`state != TaskCompleted` and `not resolvedNotMine`. Pick the nearest.
This is the weakest tier — the station might not be assigned to us.

All tiers skip `TaskCompleted` and `resolvedNotMine` stations.

### 6.2 Target hysteresis and opportunistic switching

Once locked (`tcLockedTaskIndex >= 0`), the target is kept for at
least `TaskCommitTicks` (48 ticks, ~2s). This prevents thrashing when
icon visibility flickers or movement changes the nearest station by a
few pixels.

After the commit window expires, Navigate phase periodically
re-evaluates the best available candidate every
`TaskReEvalPeriodTicks` (24 ticks, ~1s). It switches only when the
candidate is a stronger evidence tier than the locked target
(`TierIcon` > `TierCheckout` > `TierGeometry`), or when it is the same
tier but much closer (`candidateDist < currentDist *
TaskSwitchDistanceRatio`, default 0.5). Hold and Confirm phases never
run this opportunistic re-selection.

If the locked target becomes `TaskCompleted` or `resolvedNotMine`,
the lock is broken immediately regardless of the commit window.

### 6.3 LLM-directed targets

When the LLM provides `tcTarget.kind == TgtIndex`, the mode locks
that station directly (skipping tier selection). The tier system is
the fallback path, used by the default directive
(`TgtNearestMandatory`) and when the LLM-specified target is invalid.

---

## 7. Radar-dot checkout latching

Radar dots are yellow pixels on the screen border that the server
renders to indicate off-screen task assignments. The perception
pipeline scans them every frame (`perception/tasks.nim:scanRadarDots`).

### 7.1 Matching radar dots to stations

For each station, compute its projected radar-dot position with
`projectedRadarDot(station, camX, camY, playerWx, playerWy)` in
`perception/geometry.nim`. The projection uses the player's screen
position as the ray origin and clips the ray from player to task-icon
centre against the viewport boundary, matching the server's radar-dot
algorithm for diagonal off-screen tasks.

A dot matches station `i` if any dot in `belief.percep.radarDots` is
within Chebyshev distance `RadarMatchTolerance = 2` of the projected
position.

### 7.2 Checkout semantics

- **Latching:** a single radar-dot sighting sets `checkout = true`.
  The server only renders dots for assigned tasks, so one sighting is
  high-confidence evidence.
- **Persistence:** checkout persists across frames.
- **Cleared by:** confirm timeout (task might not be ours), negative
  evidence (24 frames clear, no icon), and round reset.

---

## 8. Icon-match check (Confirm phase)

`iconVisibleAtStation` (`modes/task_completing.nim:143-158`) checks
whether any visible task icon matches the locked station each tick
during the Confirm phase.

Match criteria: the icon's screen-space top-left matches the fixed
server render offset for that station:

```nim
expectedX = station.x + station.w div 2 - SpriteSize div 2 - camX
expectedY = station.y - SpriteSize - 2 - camY
```

The icon matches when both axes are within 2 px of the expected
screen position. The tolerance covers the server bob animation and
scan-kernel jitter. Do not apply `SpriteDrawOffX/Y` here; the task-icon
scan reports raw screen-space sprite coordinates.

- Icon found: reset `tcConfirmMissCount = 0`.
- Icon not found: increment `tcConfirmMissCount`.

This debounce handles icon animation flicker. The 24-frame threshold
matches modulabot's `ICON_MISS_COMPLETE_TICKS`.

---

## 9. Ghost variant

Per DESIGN.md §5.7, ghosts use `task_completing` with
`tcAbandonOnNearbyBody: false`. The hold lifecycle applies identically:

- Ghosts still press A to complete tasks.
- The server still removes the task icon on completion.
- The action layer uses straight-line steering (no walk mask) for the
  Navigate phase — handled by `applyIntent`'s ghost check in
  `action.nim`.
- No body-reporting reflex fires (gated by `not isGhost` in
  `reflex.nim:94-95`).
- The ghost override in `reconcileDirective` (`bot.nim:231-232`) forces
  this mode regardless of any LLM directive.

---

## 10. Scratch state

All fields are reset on mode entry (`onEnter`). Preserved across
directive changes within the same mode (per `DESIGN.md` §5.6).

```nim
of ModeTaskCompleting:
  tcLockedTaskIndex*: int          # Locked target station (-1 = none).
  tcEnterTick*: int                # Tick when mode was entered.
  tcPhase*: TaskPhase              # Navigate / Hold / Confirm.
  tcHoldRemaining*: int            # Ticks left in Hold phase.
  tcHoldStartTick*: int            # Tick when Hold began (for trace).
  tcConfirmDeadlineTick*: int      # Tick when Confirm times out.
  tcConfirmMissCount*: int         # Consecutive icon-absent frames in Confirm.
  tcCompletedTaskIndex*: int       # Set on completion; bot.nim applies to belief.
  tcLockTick*: int                 # Tick when target was locked (hysteresis).
  tcLastReEvalTick*: int           # Last periodic target re-evaluation tick.
  tcLockedTier*: TaskSelectionTier # Tier recorded when the current target was locked.
  tcSelectionTier*: TaskSelectionTier  # Tier that selected the current target.
```

Initial values on `onEnter`:
- `tcLockedTaskIndex = -1` (no target)
- `tcPhase = TpNavigate`
- `tcHoldRemaining = 0`
- `tcHoldStartTick = 0`
- `tcConfirmDeadlineTick = 0`
- `tcConfirmMissCount = 0`
- `tcCompletedTaskIndex = -1`
- `tcLockTick = 0`
- `tcLastReEvalTick = 0`
- `tcLockedTier = TierGeometry`
- `tcSelectionTier = TierGeometry`

---

## 11. Tuning constants

All live in the task-completing lifecycle block in `tuning.nim`:

| Constant | Value | Meaning |
|---|---|---|
| `TaskHoldTicks` | 84 | A-hold duration. Server accepts ~72; 84 adds a 12-tick pad. |
| `TaskConfirmWindowTicks` | 48 | Post-hold observation window before timeout (~2s). |
| `TaskIconMissCompleteTicks` | 24 | Consecutive icon-absent frames to confirm completion. |
| `TaskIconMissResolveFrames` | 2 | Consecutive icon-absent frames for "not mine" pruning. |
| `TaskClearScreenMargin` | 8 | Pixel margin for "icon area fully on-screen" check. |
| `RadarMatchTolerance` | 2 | Chebyshev distance for radar-dot → station matching. |
| `RadarExclusionDistance` | 8 | Chebyshev distance above which a projected dot counts absent. |
| `RadarExclusionFrames` | 12 | Consecutive absent-dot frames before excluding a station. |
| `RadarExclusionMinDots` | 1 | Minimum detected radar dots required before exclusion can run. |
| `TaskCommitTicks` | 48 | Hysteresis: keep target for at least ~2s before reconsidering. |
| `TaskReEvalPeriodTicks` | 24 | Minimum interval between post-hysteresis Navigate re-evaluations (~1s). |
| `TaskSwitchDistanceRatio` | 0.5 | Same-tier switch threshold: candidate must be less than half the current distance. |

---

## 12. Reflex interactions

### 12.1 Outgoing reflexes (task_completing → other modes)

| Condition | Target mode | Params issued | Reflex name |
|---|---|---|---|
| `body_newly_in_view` (body count increased) AND crewmate, alive, not ghost | `reporting` | `repBodyLocation: <body_world_pos>`, TTL 480 | `body_newly_in_view_report` |

This reflex fires when a new body appears in the field of view
(`reflex.nim:91-117`). It computes the body's world position from
screen coords + camera offset and creates a reporting directive. The
mode's `tcAbandonOnNearbyBody` param doesn't gate the reflex directly
— the reflex checks `belief.self.role == RoleCrewmate and alive and
not isGhost` independently. The param exists for future LLM-level
control.

### 12.2 Incoming reflexes (other modes → task_completing)

| Source | Condition | Mechanism |
|---|---|---|
| Any mode | Ghost override | `reconcileDirective` forces default (this mode) for all ghosts |
| `ModeIdle` | Role detected as crewmate | `reconcileDirective` stale-default re-evaluation |
| Any mode | Directive TTL expires (crewmate) | `checkDirectiveTtl` → `defaultDirectiveFor` → this mode |

### 12.3 Cooldown

The body-report reflex is subject to `ReflexCooldownTicks` (96 ticks,
~4s). If a second body appears within the cooldown window, the reflex
does not re-fire.

---

## 13. Trace events

Emitted by `bot.nim:530-563` after `decide()` returns.

### 13.1 `task_started`

Emitted when the Hold phase begins (Navigate → Hold transition).
Detected by `tcHoldStartTick == belief.tick`.

```json
{ "t": <tick>, "kind": "task_started",
  "task_index": <int>,
  "station_name": "<string>",
  "selection_tier": "icon" | "checkout" | "geometry" }
```

### 13.2 `task_completed`

Emitted when `tcCompletedTaskIndex >= 0` (Confirm phase succeeded).

```json
{ "t": <tick>, "kind": "task_completed",
  "task_index": <int>,
  "station_name": "<string>",
  "hold_duration_ticks": <int> }
```

### 13.3 `task_abandoned`

Emitted when a mode switch interrupts an active Hold or Confirm phase.
Detected in `bot.nim:switchMode` (`bot.nim:107-124`).

```json
{ "t": <tick>, "kind": "task_abandoned",
  "task_index": <int>,
  "station_name": "<string>",
  "reason": "mode_switch",
  "phase_at_abandon": "hold" | "confirm",
  "hold_ticks_elapsed": <int> }
```

Note: confirm-timeout abandonment does not emit a trace event; the
mode simply re-selects a new target. A future refinement could add
a `"reason": "confirm_timeout"` event.

---

## 14. Default directive (crewmate)

When no LLM directive is active (startup, TTL expiry, LLM failure),
the crewmate's default directive is:

```text
task_completing {
  tcTarget: { kind: TgtNearestMandatory, taskIndex: -1, roomId: -1 }
  tcAbandonOnNearbyBody: true
}
```

This makes the crewmate cycle through task stations using the 3-tier
priority system. The LLM can override with a `TgtIndex` to direct the
bot to a specific station, or switch to a different mode entirely.

For ghosts, the same default with `tcAbandonOnNearbyBody: false`.

---

## 15. Action layer contract

The mode communicates with the action layer via three disciplines:

- **`DisciplineNormal`** — used during the Navigate phase. The action
  layer uses the waypoint graph and baked edge paths to reach
  `steerTo`. For ghosts, straight-line steering is used instead.
- **`DisciplineTaskHold`** — used during the Hold phase. The action
  layer emits `ButtonA` with no directional buttons
  (`action.nim:316-321`). No movement occurs.
- **`DisciplineNoOp`** — used during the Confirm phase. The action
  layer emits no buttons (the bot stands still and observes).

The mode sets `pressA: true` during Hold but does not set it during
Navigate or Confirm. The actual button press during Hold is handled
by the action layer based on `DisciplineTaskHold`.

---

## 16. LLM snapshot context

The task state is included in LLM snapshots via `snapshot.nim:184-200`:

```json
"task_state": {
  "stations": [
    { "index": 0,
      "state": "not_doing" | "checkout" | "confirmed" | "completed",
      "checkout": true | false,
      "resolved_not_mine": true | false }
  ],
  "in_progress_index": <int> | null
}
```

The LLM sees per-station evidence state but not the mode's internal
scratch (phase, hold remaining, confirm countdown). It sees:

- `current_mode: { "name": "task_completing", "source": "default" | "llm" | "reflex", "ticks_active": <int> }`
- The full perception data (visible crewmates, bodies, task icons).
- Memory (per-player summaries).

---

## 17. Station geometry

Task stations are loaded from `perception/data.nim:loadMap()` and
stored in `referenceData.map.tasks`. Each station has:

- `x, y, w, h` — bounding rect in world coordinates.
- `name` — human-readable station name (for traces and snapshots).
- `passableCX, passableCY` — the station's geometric centre snapped
  to the nearest walkable pixel at init time.

The mode always navigates to `passableCX/CY` (not the raw centre),
ensuring navigation receives a reachable goal. Arrival is detected
by `isInsideTaskRect` which checks exact rect containment (matching
the server's check — no margin).

---

## 18. Open questions

1. **Confirm-timeout trace event.** When the Confirm phase times out,
   no `task_abandoned` event is emitted (only mode-switch abandonment
   is traced). Adding a `"reason": "confirm_timeout"` event would aid
   offline analysis of false-positive task assignments.

2. **LLM-directed target implementation.** The `TgtIndex` path exists
   in the parameter schema but the mode's `selectTarget` always runs
   the tier system. A future version should check `params.tcTarget.kind`
   before falling through to tier selection.

3. **Task icon count in snapshots.** The snapshot currently renders an
   empty `task_icons_on_screen` array (the icon-to-task-index mapping
   is not carried on `IconMatch`). Enriching this would give the LLM
   direct visibility into which icons are currently on screen.

4. **Belief write for confirm timeout.** On confirm timeout, the mode
   should ideally clear the station's checkout latch (signal to the
   belief layer that the task may not be ours). Currently it only
   unlocks the target and re-selects; the belief-layer's natural
   `iconMissCount` accumulation handles this eventually but with a
   delay.
