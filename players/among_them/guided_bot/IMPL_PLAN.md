# guided_bot — Implementation Plan (Phase 6+)

> **Living document.** Tracks forward-looking implementation work beyond
> the phase 1–5 foundation. Based on a full mode audit conducted
> 2026-05-01. Update this file as items are completed or priorities
> shift.
>
> Last reviewed: 2026-05-01

---

## Context

Phases 1–5 built the full perception pipeline, action layer, 6 mode
handlers + 4 reflexes, LLM guidance loop, trace writer, and fallback
playability. The bot navigates to a task station and holds A — but
never detects completion and never moves on.

A deep audit of all 11 mode handlers revealed that several are
incomplete or stubs. This plan organises the remaining work by
gameplay impact.

---

## Phase 6 — Mode completeness

The core deliverable: make every mode that's on a default or reflex
path produce correct behavior end-to-end.

### 6.1 `task_completing` — hold lifecycle + completion detection (P0)

The single biggest gameplay improvement. The bot currently spends 75%
of a match holding A at one station.

**What exists:** target selection (icon-based + nearest fallback),
A\* navigation to station, enter `DisciplineTaskHold` on arrival.

**What's missing:** The mode has no lifecycle after arriving at the
station. It holds A forever — no hold-duration cap, no
icon-disappearance detection, no target unlock/re-selection.

**Proposed fix — 3-phase lifecycle (from modulabot's proven pattern):**

| Sub-phase | Duration | Behavior | Exit condition |
|---|---|---|---|
| Navigate | Variable | A\* to target station | `isInsideTaskRect` true |
| Hold | `TaskHoldTicks` (84) | Press A, no movement | Timer expires |
| Confirm | Up to `ConfirmWindowTicks` (48) | Stay still, watch icon | Icon absent 24 consecutive frames, OR timeout |

On confirmation: mark task resolved, clear `tcLockedTaskIndex`, re-run
selection. On confirm timeout: clear lock, re-run selection (task might
not be ours).

New scratch fields:
- `tcPhase: enum {Navigate, Hold, Confirm}`
- `tcHoldRemaining: int`
- `tcConfirmDeadlineTick: int`
- `tcConfirmMissCount: int`

New tuning constants:
- `TaskHoldTicks = 84`
- `TaskConfirmWindowTicks = 48`
- `TaskIconMissCompleteTicks = 24`

**Selection quality improvements (same change):**
- Only lock targets where icon or radar evidence exists.
- Add radar-dot → task station mapping as second-tier selection
  between icon-visible and pure-nearest fallback.
- Hold timeout as backstop for unassigned stations.

**Diagnostic note:** See `FIX_PLAN.md` § "Task-completion detection
missing" for the full root-cause analysis and hypothesis set.

### 6.2 `reporting` — success detection + retry (P1)

**What exists:** steers toward body location via `DisciplineReport`;
action layer presses A within `ReportRange = 20` px.

**What's missing:**
- No success check — the mode can't detect whether the report
  triggered a meeting. It steers at a stale `repBodyLocation`
  until the reflex TTL expires (480 ticks / ~20 s).
- No retry — `DisciplineReport` presses A once when entering range,
  then keeps steering past the body. If the first press misses,
  there's no second attempt.

**Fix:**
- Check `belief.self.phase == PhaseVoting` after pressing A. If a
  meeting starts, the voting reflex will handle the mode switch, but
  the mode should at least stop steering.
- Re-press A every N ticks while inside report range (the action
  layer currently does this once; either loop in the mode or adjust
  the discipline).
- If body count drops to 0 (body despawned or we moved away), clear
  the target and fall back to the default directive.

### 6.3 `meeting` — chat emission + cursor tracking (P1)

**What exists:** LLM-driven action queue (speak, vote, confirm,
unvote, wait). Safety-net fallback forces SKIP near timer expiry.

**What's missing (3 gaps):**

1. **Chat is dead.** `MeetingActSpeak` sets `intent.chat` but
   `action.nim:emitChat` is a stub (always returns false). Chat text
   from the LLM is silently dropped. Fix: implement chat emission in
   the action layer — the FFI needs to expose chat packets to the
   game protocol, or the chat field needs to be wired through the
   button-mask output in a way the Python harness can forward.

2. **Cursor is blind.** `cursorDirectionForTarget` always returns
   `CursorRight`. The mode has no cursor-position tracking. Fix: use
   the voting-screen parse (`belief.percep` via `mergeVotingPercept`)
   to read the current cursor position and compute the shortest path
   to the target slot. The voting parser already detects the cursor
   position (phase 1.6).

3. **Meeting timer is estimated.** Uses `typicalMeetingDuration =
   1200` minus ticks-in-meeting. Fix: parse the vote timer from the
   voting screen if the server renders one, or at minimum make the
   constant configurable via tuning.

### 6.4 `hunting` — cover rotation + target memory (P2)

**What exists:** preferred-target pursuit, opportunistic lone-crew
kill, `DisciplineKillStrike`.

**What's missing:**
- Cover behavior always walks to the nearest task station and stands
  there (no rotation, no loiter, no fake A-press). Visually
  suspicious.
- `hunLastSightingTick` is set but never read — no "last seen at X,
  go check" behavior. Once a target leaves the screen, pursuit drops
  immediately.
- No kill confirmation after pressing A.

**Fix:**
- Delegate cover behavior to `pretending`'s station-rotation logic
  (or inline a similar pattern with loiter + rotation).
- Add short-term target memory: if the preferred target was visible
  N ticks ago, steer toward its last-known position before dropping
  to cover.
- After a kill-strike attempt, check whether visible crewmate count
  decreased (kill landed) or whether kill cooldown reset. If missed,
  re-attempt if still in range.

### 6.5 `pretending` — fake A-press + witness swap (P2)

**What exists:** Station-to-station rotation with loiter timer.

**What's missing:**
- Never presses A during loiter — a crewmate would be visibly
  interacting with the station. Behavioral tell.
- `preMaySwapOnWitness` param exists but is never checked.

**Fix:**
- During loiter, emit `DisciplineTaskHold` (or a raw `pressA: true`)
  for a portion of the loiter duration to fake a task-hold animation.
- Check `visibleCrewmates.len` during loiter. If a new crewmate
  appears and `preMaySwapOnWitness` is true, pick a new station
  (re-roll to look less suspicious).

### 6.6 `fleeing` — minor cleanup (P3)

**What exists:** Steers away from body for duration/distance.

**Issues:**
- Returns `noOpIntent()` when done (stands still until TTL expires).
- Flee target can land in a wall.

**Fix:**
- When flee timer expires, switch to cover behavior (walk to a
  nearby task station) instead of going idle.
- Clamp the flee target to the nearest passable tile.

### 6.7 Reflex scope — widen body reflexes (P3)

Body→reporting (reflex 1) only fires from `ModeTaskCompleting`.
Body→fleeing (reflex 2) only fires from `ModeHunting`. Both should
fire from any applicable crew/imposter mode.

**Fix:** Change the mode guard in `reflex.nim` from
`mode == ModeTaskCompleting` to
`belief.self.role == RoleCrewmate and belief.self.alive and not
belief.self.isGhost` (and equivalently for the imposter flee reflex).

---

## Phase 7 — Stub modes (LLM-only, not on critical path)

These modes are only reachable if the LLM explicitly selects them.
They're no-ops today, which means the LLM selecting them causes the
bot to stand still. Lower priority than phase 6 because the fallback
path never enters them.

### 7.1 `fear` — group-following behavior

Navigate toward visible crewmates, avoid being alone. Use
`visibleCrewmates` to find the nearest group and steer toward them.
Fall back to task-completing if no crewmates are visible.

### 7.2 `investigating` — evidence gathering

Navigate to a target (color, location, or room) and observe. Track
whether the target is seen, log sightings to memory. Timeout after
`invTimeoutTicks` and fall back to the default.

### 7.3 `alibi_building` — companion tracking

Navigate toward a specific crewmate color and stay near them. Use
`visibleCrewmates` to find the companion and follow. Fall back if
the companion is not visible after a timeout.

### 7.4 `sabotage_watching` — season-dependent placeholder

Only relevant if the season enables sabotage mechanics. Leave as
stub until needed.

---

## Summary table

| Phase | Item | Priority | Effort | Status |
|---|---|---|---|---|
| 6.1 | `task_completing` lifecycle | P0 | Medium | **Done** |
| 6.2 | `reporting` success detection | P1 | Small | **Done** |
| 6.3 | `meeting` chat + cursor | P1 | Medium | Open |
| 6.4 | `hunting` cover + memory | P2 | Small-medium | Open |
| 6.5 | `pretending` fake A-press | P2 | Small | Open |
| 6.6 | `fleeing` cleanup | P3 | Trivial | Open |
| 6.7 | Reflex scope widening | P3 | Trivial | Open |
| 7.1 | `fear` implementation | P3 | Medium | Open |
| 7.2 | `investigating` implementation | P3 | Medium | Open |
| 7.3 | `alibi_building` implementation | P3 | Medium | Open |
| 7.4 | `sabotage_watching` | P3 | — | Deferred |
