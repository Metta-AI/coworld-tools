# Reporting Mode — Design Document

> **Canonical reference** for the `reporting` mode handler. All
> reporting-mode design details live here; `DESIGN.md` contains only a
> brief overview and cross-reference.
>
> **Implementation:** `modes/reporting.nim`
>
> Last updated: 2026-05-12

---

## 1. Purpose and role

The `reporting` mode is the crewmate's body-reporting behavior. It is:

- **The target of the `task_completing → reporting` reflex**
  (`reflex.nim:91-117`). When a crewmate in `task_completing` mode
  sees a new body appear, the reflex fires and switches to `reporting`
  with the body's world position as the target.
- **Interrupt-driven, not default.** No role uses `reporting` as its
  default directive. The mode is only entered via the body-seen reflex
  or a future LLM directive.
- **Success is detected externally.** When the report succeeds, the
  server starts a meeting → voting screen appears → reflex 4
  (`voting_screen_appeared`) fires → mode switches to `meeting`. The
  reporting mode does not need to detect its own success.

The mode is **only legal** for an alive, non-ghost crewmate
(`isLegalFor` in `modes/reporting.nim:32-33` checks role, alive, and
ghost state). Imposters cannot self-report in the default path; an
LLM directive could theoretically issue this mode to an imposter, but
the legality check would reject it.

---

## 2. Mode parameters

The reflex (or LLM) sets these when issuing a `reporting` directive:

```text
reporting {
  repBodyLocation: Point   # World-space position of the body to report.
}
```

Implementation in `types.nim:249`:
```nim
of ModeReporting:
  repBodyLocation*: Point
```

**Default params** (from `modes/reporting.nim:36-38`):
- `repBodyLocation: Point(x: 0, y: 0)` — meaningless sentinel; the
  mode is never useful without a reflex-provided body position.

**Reflex-provided params** (from `reflex.nim:106-107`):
- `repBodyLocation`: body world position computed from screen coords +
  camera offset at the moment the body was seen.
- Directive TTL: 480 ticks (~20s).

---

## 3. Decision logic overview

`decide()` evaluates a priority cascade each tick:

1. **Not localized** — emit `noOpIntent()`.
2. **Already gave up** — emit `noOpIntent()` (bot.nim will switch to
   default on the next reconciliation).
3. **Body-visibility check** — if the body has been invisible for
   `ReportBodyMissFrames` (36) consecutive frames, give up.
4. **Range tracking** — if within `ReportRange` (20 px) for the first
   time, mark `repReachedRange`.
5. **Approach timeout** — if not yet in range and
   `ReportApproachTimeoutTicks` (240) elapsed, give up.
6. **In-range timeout** — if in range for `ReportInRangeTimeoutTicks`
   (72) ticks without a meeting starting, give up.
7. **Normal behavior** — steer toward body with `DisciplineReport`.

The mode does **not** press A directly. It emits `DisciplineReport`
and lets the action layer handle the button press when within range.

---

## 4. Body-visibility check

`bodyStillVisible` (`modes/reporting.nim:58-70`) checks whether any
visible body is near the target position each tick.

**Match criteria:** any body in `belief.percep.visibleBodies` whose
world position (screen coords + camera offset via
`visibleCrewmateWorldX/Y`) is within `ReportBodyMatchRadius` (30 px)
of `repBodyLocation`.

**Debounce:** the miss counter (`repBodyMissCount`) resets to 0 on any
frame where a matching body is seen. This handles single-frame
detection failures (body sprite flicker, partial occlusion, animation
pose changes).

**Give-up:** after 36 consecutive frames with no matching body (~1.5s),
the body likely despawned (another player reported it, or the server
cleaned it up). Sets `repGaveUp = true`, `repGaveUpReason = "body_gone"`.

---

## 5. Approach timeout

If the bot has been in reporting mode for more than
`ReportApproachTimeoutTicks` (240 ticks, ~10s) and has never entered
report range (`repReachedRange` is false): give up.

This catches cases where the waypoint route cannot make progress
toward the body (stale body position, walk mask error, unreachable
target) or the body is extremely far away. The action layer can replan
from the current localized position, but 10s of fruitless navigation is
enough.

Sets `repGaveUp = true`, `repGaveUpReason = "approach_timeout"`.

---

## 6. In-range timeout

Once the bot enters report range and the action layer starts pressing
A, track how long it stays in range without a meeting starting.

If `ReportInRangeTimeoutTicks` (72 ticks, ~3s) elapse with the bot in
range and `belief.self.phase` is still gameplay (no meeting started):
give up. The report didn't register.

3 seconds is generous — the server processes the report on the
fresh-press edge (first tick in range provides this via
`DisciplineReport`), and the meeting transition should happen within
a few ticks. 72 ticks provides ample debounce for edge cases (body
barely outside the server's actual report radius, network timing).

The counter only increments while in range (`dist <= ReportRangeLocal`).
Momentary out-of-range jitter (camera movement) pauses the counter
but does not reset it.

Sets `repGaveUp = true`, `repGaveUpReason = "in_range_timeout"`.

---

## 7. Give-up mechanism

When any of the three checks fires, the mode sets
`scratch.repGaveUp = true` and returns `noOpIntent()`. The bot
pipeline in `bot.nim:578-586` detects this after `decide()`:

```nim
if bot.modeScratch.repGaveUp:
  switchMode(bot, defaultDirectiveFor(bot.belief))
```

This forces an immediate switch to the default crewmate directive
(`task_completing`), avoiding the idle wait that would occur if the
mode simply returned `noOpIntent()` until the directive TTL expired.

---

## 8. Scratch state

All fields are reset on mode entry (`onEnter`). Preserved across
directive changes within the same mode (per `DESIGN.md` §5.6).

```nim
of ModeReporting:
  repEnterTick*: int             # Tick when mode was entered.
  repBodyMissCount*: int         # Consecutive frames without body match.
  repReachedRange*: bool         # True once dist <= ReportRange.
  repInRangeTicks*: int          # Ticks spent in range without meeting.
  repGaveUp*: bool               # Set when any give-up check fires.
  repGaveUpReason*: string       # "body_gone" / "approach_timeout" / "in_range_timeout".
```

Initial values on `onEnter`:
- `repEnterTick = belief.tick`
- `repBodyMissCount = 0`
- `repReachedRange = false`
- `repInRangeTicks = 0`
- `repGaveUp = false`
- `repGaveUpReason = ""`

---

## 9. Tuning constants

All live in `tuning.nim:46-49`:

| Constant | Value | Meaning |
|---|---|---|
| `ReportBodyMatchRadius` | 30 | World-pixel radius for matching a visible body to the target. Generous for camera jitter + sprite anchor offset. |
| `ReportBodyMissFrames` | 36 | Consecutive frames without a matching body before giving up (~1.5s). |
| `ReportApproachTimeoutTicks` | 240 | Give up navigating after 10s without reaching range. |
| `ReportInRangeTimeoutTicks` | 72 | Give up pressing A after 3s in range without a meeting starting. |

Action-layer constant (local to `action.nim:40`):

| Constant | Value | Meaning |
|---|---|---|
| `ReportRange` | 20 | Threshold for the action layer to press A during `DisciplineReport`. |

The mode duplicates this as `ReportRangeLocal = 20` for its own
in-range detection. Both must stay in sync.

---

## 10. Reflex interactions

### 10.1 Incoming reflexes (other modes → reporting)

| Source mode | Condition | Params issued | Reflex name |
|---|---|---|---|
| `task_completing` | Unknown visible body AND crewmate, alive, not ghost | `repBodyLocation: <body_world_pos>`, TTL 480 | `body_newly_in_view_report` |

This reflex fires without LLM approval. `reflex.nim` keeps remembered
body positions and reports the first visible body that does not match a
known body, so a different body can still trigger reporting even when the
visible body count stays stable.

The reflex only fires from `task_completing` — if the crewmate is in
another mode (for example `meeting`), bodies don't trigger reporting.
This is intentional: meeting mode can't be interrupted, and other modes
may have higher-priority goals.

### 10.2 Outgoing reflexes (reporting → other modes)

| Condition | Target mode | Params issued | Reflex name |
|---|---|---|---|
| Voting screen appears (server starts meeting) | `meeting` | `meetWantToSpeakFirst: false`, TTL 0 | `voting_screen_appeared` |

This is the success path: the report worked, the server started a
meeting, the voting-screen reflex fires. No explicit "report succeeded"
detection is needed within the mode.

### 10.3 Give-up → default

When `repGaveUp` is set, `bot.nim` forces a switch to
`defaultDirectiveFor(belief)` — which for a crewmate is
`task_completing`. This is not a reflex but a pipeline-level override.

### 10.4 Cooldown

The body-report reflex is subject to `ReflexCooldownTicks` (96 ticks,
~4s). If another unknown body appears within the cooldown window, the
reflex does not re-fire; after the cooldown, known-body memory prevents
re-reporting the same corpse while still allowing a different corpse to
trigger reporting.

---

## 11. Trace events

Emitted by `bot.nim:566-585` after `decide()` returns.

### 11.1 `report_attempted`

Emitted once when the bot first enters report range (`repReachedRange`
transitions to true, detected by `repInRangeTicks <= 1`).

```json
{ "t": <tick>, "kind": "report_attempted",
  "body_x": <int>, "body_y": <int>,
  "self_x": <int>, "self_y": <int> }
```

### 11.2 `report_gave_up`

Emitted when the mode gives up (any of the three timeout checks fires).

```json
{ "t": <tick>, "kind": "report_gave_up",
  "reason": "body_gone" | "approach_timeout" | "in_range_timeout",
  "ticks_in_mode": <int>,
  "reached_range": <bool> }
```

---

## 12. Action layer contract

The mode communicates with the action layer via a single discipline:

- **`DisciplineReport`** — used for all normal behavior. The action
  layer steers toward `steerTo` and ORs `ButtonA` every tick while
  Manhattan distance ≤ `ReportRange` (20 px) (`action.nim:335-343`).
  The mode never sets `pressA` directly — button presses are the
  action layer's responsibility based on the discipline hint.

When the mode returns `noOpIntent()` (not localized, already gave up),
the action layer emits no buttons.

---

## 13. LLM snapshot context

Reporting exposes a compact mode summary in LLM snapshots. The LLM sees:

- `current_mode.name/source/ticks_active`.
- `current_mode.params`, including the body location.
- `current_mode.summary`, including report target, ticks in mode,
  A-press range status, miss count, give-up state, and current distance
  from the body.
- Perception data (visible bodies, crewmates).
- Memory (per-player summaries).

---

## 14. Open questions

1. **Multi-body priority.** The reflex reports the first unknown body in
   the perception order. If multiple unknown bodies are visible, it
   doesn't consider which is closest or most accessible. Low priority —
   the first unknown body is usually enough to force the meeting.

2. **Re-report after give-up.** If the bot gives up and returns to
   `task_completing`, the same body (if still visible) could trigger
   the reflex again after the cooldown expires. This is arguably
   correct behavior (retry after cooldown) but could cause looping if
   the body is permanently unreachable. The approach timeout (10s) +
   cooldown (4s) = 14s per attempt limits the cost.

3. **LLM-initiated reporting.** The mode is legal for crewmates and
   could be issued by the LLM to report a body the bot remembers but
   didn't trigger the reflex for (e.g. body seen in a non-task mode).
   The LLM would need to provide `repBodyLocation` from memory. This
   path is untested but structurally supported.
