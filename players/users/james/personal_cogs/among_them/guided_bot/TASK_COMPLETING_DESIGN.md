# Task Completing Mode — Design Document

> **Canonical reference** for the `task_completing` mode handler. All
> task-completing design details live here; `DESIGN.md` contains only a
> brief overview and cross-reference.
>
> **Implementation:** `modes/task_completing.nim` (324 LOC)
>
> Last updated: 2026-05-10

---

## 1. Purpose and role

The `task_completing` mode is the crewmate's core gameplay loop. It is:

- **The crewmate default directive** (`mode_registry.nim`). When no
  LLM directive is active, an alive crewmate runs `task_completing`
  with `tcTarget: TgtNearestMandatory, tcAbandonOnNearbyBody: true`.
- **The ghost default directive** (`mode_registry.nim`). Ghosts
  always run `task_completing` with `tcAbandonOnNearbyBody: false`.
  The ghost override in `bot.nim` forces this mode regardless
  of LLM directives.
- **The target of the `reconcileDirective` idle→task transition.**
  When the bot starts in `ModeIdle` (unknown role) and the role is
  detected as crewmate, `reconcileDirective` immediately switches to
  the crewmate default (this mode).

The mode is **legal for** any alive crewmate or any ghost (`isLegalFor`
checks `role == RoleCrewmate or isGhost`). It is **not legal** for alive imposters (they use
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
  TgtNearestAny         # Nearest available unfinished station.
  TgtSpecificRoom       # Nearest available unfinished station in a room.

TaskTarget = object
  kind: TaskTargetKind
  taskIndex: int         # TgtIndex: which station.
  roomId: int            # TgtSpecificRoom: which room.
```

Implementation in `types.nim`.

### 2.2 Default params

From `modes/task_completing.nim`:
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
3. **Post-task crew behavior** — alive crewmates that have confirmed
   `CrewPostTaskCompleteCount` (8) tasks and currently see no task
   icons/radar evidence stop weak geometry fallback wandering. They
   shadow a visible crewmate, move to the cafeteria button if alone,
   and press the button only when existing memory evidence reaches
   `CrewButtonEvidenceThreshold`.
4. **Hysteresis** — if a target is locked and `TaskCommitTicks` (48)
   haven't elapsed since locking, keep the current target (prevents
   oscillation).
5. **Target selection** — if no target is locked, run the 3-tier
   priority system (§6) to pick one.
6. **Phase dispatch** — execute the current phase (Navigate, Hold,
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
  (`isInsideTaskRect` — exact match to the server's no-margin check).
- **Duration:** variable (depends on distance and path complexity).

### 4.2 Hold phase

- **Discipline:** `DisciplineTaskHold` — press A, no movement.
- **Duration:** `TaskHoldTicks` (74 ticks, ~3.1s). The server accepts
  the task within ~72 ticks; the 2-tick pad keeps the hold close to
  server acceptance without releasing prematurely.
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
  (4) consecutive frames → task completed.
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
frame by the bot pipeline after `mergeTaskPercept`).

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
  radarRayExcluded: bool  # Per-frame off-screen soft exclusion from pip rays.
```

Implementation in `types.nim`.

### 5.2 State transitions (updateTaskState)

Run every gameplay frame in `belief.nim`. For each station `i`:

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

3. **Per-frame radar-ray exclusion.** If the station is off-screen and
   at least `RadarRayMinPips` pips are detected, cast rays from the
   player's world position through each pip. If no ray intersects the
   padded task-icon AABB, set `radarRayExcluded = true` for this frame.
   On-screen tasks, zero-pip frames, localization loss, and alive
   imposters set it to `false`.

4. **Radar-dot checkout.** If a radar dot matches the station's
   projected screen-edge position (Chebyshev distance <=
   `RadarMatchTolerance = 2`) and `radarRayExcluded == false`:
   `checkout = true`. If state was `TaskNotDoing`, promote to
   `TaskCheckout`. For on-screen tasks, `radarRayExcluded` is always
   false because icon visibility is the hard signal.

### 5.3 Skips

- Interstitial frames: skip all updates.
- Alive imposters: skip icon checks (imposters don't have task icons).
  Radar-dot updates still run (imposter ghosts have tasks).
- Stations at `TaskCompleted` or `resolvedNotMine`: clear the transient
  `radarRayExcluded` flag, then skip (terminal states within a round).

### 5.4 Radar-ray exclusion (negative evidence from dot absence)

In addition to icon-miss pruning (§5.2) which requires the task to be
on-screen, the belief layer can exclude off-screen tasks using radar-ray
evidence.

**Principle:** the server draws a yellow radar dot on the screen edge for
every assigned off-screen task. From the player's position, each detected
dot defines a ray into the world. If no detected ray intersects a task's
padded icon AABB, that off-screen task is not consistent with the current
radar evidence.

**Algorithm** (runs per-frame in `updateTaskState`, before checkout):

1. Skip if: not localized, alive imposter, task on-screen, or fewer than
   `RadarRayMinPips` (1) dots detected.
2. For each detected dot, cast a ray from the player's world position
   through the dot direction.
3. If no ray intersects the task's padded icon AABB
   (`RadarRayIconPadding = 14`), set `radarRayExcluded = true` for this
   frame.
4. Tier-3 geometry selection skips tasks where `radarRayExcluded == true`.
   Tier 1 icon evidence and tier 2 checkout latches ignore the flag.

**Why per-frame?** Radar-ray evidence is positional and reversible. As the
bot moves, a task that did not align with any dot from the previous
position may align from the next one. The flag is therefore not a durable
negative belief; only `resolvedNotMine` is durable.

### 5.5 Round reset

On role-reveal interstitial: `resetTaskSlots` clears all slots to
`TaskNotDoing`, clears `checkout`, `resolvedNotMine`, `iconMissCount`,
and radar-ray transient state.

### 5.6 Mode-belief interaction

The mode doesn't write to `belief.tasks` directly (DESIGN.md §3
invariant: belief updated only by the perceive/update stage). The mode
signals completion via `scratch.tcCompletedTaskIndex`. After `decide()`
returns, `bot.nim` reads this field and applies the state
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
(`modes/task_completing.nim`).

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
`state != TaskCompleted`, `not resolvedNotMine`, and
`not radarRayExcluded`. Pick the nearest. This is the weakest tier —
the station might not be assigned to us.

All tiers skip `TaskCompleted` and `resolvedNotMine` stations.

### 6.2 Post-task crew behavior

The map has 40 task stations, but a crewmate receives a smaller assigned
set. Once the bot has confirmed `CrewPostTaskCompleteCount` (8) tasks,
has no visible task icons, has no radar dots, and has no latched
`TaskConfirmed`/`TaskCheckout` station, it suppresses the tier-3 geometry
fallback. This keeps a finished alive crewmate from roaming to arbitrary
unassigned stations and dying in low-traffic rooms.

In this post-task state:

- If any live non-self player has actionable memory evidence at or above
  `CrewButtonEvidenceThreshold`, the bot navigates to the cafeteria
  emergency button and presses A only within `CrewButtonRange`.
- Otherwise, it shadows the closest visible non-self crewmate.
- If no other crewmate is visible, it returns to the cafeteria button
  without pressing A.

Ghosts never use this branch; they keep completing tasks.

### 6.3 Target hysteresis and opportunistic switching

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

### 6.4 LLM-directed targets

When the LLM provides `tcTarget.kind == TgtIndex`, the mode locks that
station directly (skipping tier selection) if the station is available.
`TgtNearestAny` chooses the nearest available unfinished station.
`TgtSpecificRoom` chooses the nearest available unfinished station whose
passable centre is inside the requested room. The tier system is the
fallback path, used by the default directive (`TgtNearestMandatory`) and
when the LLM-specified target is invalid.

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

`iconVisibleAtStation` (`modes/task_completing.nim`) checks
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

This short debounce handles icon animation flicker while keeping local
completion traces close to the server's 72-tick task acceptance point.

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
  `reflex.nim`).
- The ghost override in `reconcileDirective` (`bot.nim`) forces
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
| `TaskHoldTicks` | 74 | A-hold duration. Server accepts ~72; 74 adds a 2-tick pad. |
| `TaskConfirmWindowTicks` | 48 | Post-hold observation window before timeout (~2s). |
| `TaskIconMissCompleteTicks` | 4 | Consecutive icon-absent frames to confirm completion. |
| `TaskIconMissResolveFrames` | 6 | Consecutive icon-absent frames for "not mine" pruning. |
| `TaskClearScreenMargin` | 8 | Pixel margin for "icon area fully on-screen" check. |
| `RadarMatchTolerance` | 2 | Chebyshev distance for radar-dot → station matching. |
| `RadarRayIconPadding` | 14 | Half-extent of the padded task-icon AABB used by radar-ray exclusion. |
| `RadarRayMinPips` | 1 | Minimum detected radar dots required before radar-ray exclusion can run. |
| `PipDisappearGraceTicks` | 5 | Suppresses icon-miss counting briefly after radar pips disappear. |
| `TaskCommitTicks` | 48 | Hysteresis: keep target for at least ~2s before reconsidering. |
| `TaskReEvalPeriodTicks` | 24 | Minimum interval between post-hysteresis Navigate re-evaluations (~1s). |
| `TaskSwitchDistanceRatio` | 0.5 | Same-tier switch threshold: candidate must be less than half the current distance. |
| `CrewPostTaskCompleteCount` | 8 | Confirmed own-task count after which an alive crewmate stops weak geometry fallback wandering when task evidence is quiet. |
| `CrewButtonEvidenceThreshold` | 8 | Suspicion score needed before a post-task crewmate calls an emergency meeting. |
| `CrewButtonRange` | 20 | World-pixel range for pressing A on the cafeteria emergency button. |

---

## 12. Reflex interactions

### 12.1 Outgoing reflexes (task_completing → other modes)

| Condition | Target mode | Params issued | Reflex name |
|---|---|---|---|
| Unknown visible body AND crewmate, alive, not ghost | `reporting` | `repBodyLocation: <body_world_pos>`, TTL 480 | `body_newly_in_view_report` |

This reflex fires when `reflex.nim` sees a visible body whose world
position does not match remembered body positions. It computes that
body's world position from screen coords + camera offset and creates a
reporting directive. This is position-based rather than only count-based,
so a different body can still be reported if it replaces another visible
body without increasing the visible body count. The mode's
`tcAbandonOnNearbyBody` param gates this reflex, alongside the structural
checks that the bot is a living non-ghost crewmate.

### 12.2 Incoming reflexes (other modes → task_completing)

| Source | Condition | Mechanism |
|---|---|---|
| Any mode | Ghost override | `reconcileDirective` forces default (this mode) for all ghosts |
| `ModeIdle` | Role detected as crewmate | `reconcileDirective` stale-default re-evaluation |
| Any mode | Directive TTL expires (crewmate) | `checkDirectiveTtl` → `defaultDirectiveFor` → this mode |

### 12.3 Cooldown

The body-report reflex is subject to `ReflexCooldownTicks` (96 ticks,
~4s). If another unknown body appears within the cooldown window, the
reflex does not re-fire; after the cooldown, known-body memory prevents
re-reporting the same corpse while still allowing a different corpse to
trigger reporting.

---

## 13. Trace events

Emitted by `bot.nim` after `decide()` returns.

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
Detected in `bot.nim:switchMode`.

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
priority system while task evidence remains live. After eight confirmed
task completions and no remaining icon/radar evidence, the same mode
switches to the post-task crew behavior in §6.2. The LLM can override
with a `TgtIndex` to direct the bot to a specific station, or switch to a
different mode entirely.

For ghosts, the same default with `tcAbandonOnNearbyBody: false`.

---

## 15. Action layer contract

The mode communicates with the action layer via three disciplines:

- **`DisciplineNormal`** — used during the Navigate phase and post-task
  crew movement. The action
  layer uses the waypoint graph and baked edge paths to reach
  `steerTo`. For ghosts, straight-line steering is used instead.
- **`DisciplineTaskHold`** — used during the Hold phase. The action
  layer emits `ButtonA` with no directional buttons (`action.nim`).
  No movement occurs.
- **`DisciplineNoOp`** — used during the Confirm phase. The action
  layer emits no buttons (the bot stands still and observes).

The mode sets `pressA: true` during Hold via `DisciplineTaskHold`. It can
also set `pressA: true` during post-task emergency-button behavior when
the bot is in button range and has enough memory evidence. It does not
set `pressA` during ordinary Navigate or Confirm.

---

## 16. LLM snapshot context

The task state is included in LLM snapshots via `snapshot.nim`:

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

The LLM sees per-station evidence state plus the active mode params and
summary. For `task_completing`, `current_mode.summary` includes phase,
directed target kind/index or room, locked task, selection tier, completed
task count, live-task-evidence status, post-task-crew-behavior status,
best emergency-button evidence score, hold remaining, and confirm
countdown where applicable. It also sees:

- `current_mode: { "name": "task_completing", "params": {...}, "summary": {...}, "source": "default" | "llm" | "reflex", "ticks_active": <int> }`
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

2. **Task icon count in snapshots.** The snapshot currently renders an
   empty `task_icons_on_screen` array (the icon-to-task-index mapping
   is not carried on `IconMatch`). Enriching this would give the LLM
   direct visibility into which icons are currently on screen.

4. **Belief write for confirm timeout.** On confirm timeout, the mode
   should ideally clear the station's checkout latch (signal to the
   belief layer that the task may not be ours). Currently it only
   unlocks the target and re-selects; the belief-layer's natural
   `iconMissCount` accumulation handles this eventually but with a
   delay.
