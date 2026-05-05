# guided_bot — Implementation Plan (Phase 6+)

> **Living document.** Tracks forward-looking implementation work beyond
> the phase 1–5 foundation. Based on a full mode audit conducted
> 2026-05-01. Update this file as items are completed or priorities
> shift.
>
> Last reviewed: 2026-05-04

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

**Diagnostic note:** The original root-cause analysis and hypothesis
set was in the former `FIX_PLAN.md` (removed). The task-completion
detection issue is now resolved (phase 6.1).

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
- Clamp the flee target to the nearest passable tile. (`snapToPassable`
  in `action.nim` is available for this; see the A\* noop-lock fix.)

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
| 6.3 | `meeting` chat + cursor | P1 | Medium | **Partial** (cursor + timer done; chat deferred; live verification now possible via `--force-role imposter` — run a match and confirm meetings trigger) |
| 6.4 | `hunting` cover + memory | P2 | Small-medium | **Done** — kills land (A fires at ≤20px), confirmation blocked by localization-drop bug (see TODO.md). Use `--seed 100 --force-role imposter` with `imposterCooldownTicks=48` to test. |
| 6.5 | `pretending` fake A-press | P2 | Small | Open |
| 6.6 | `fleeing` cleanup | P3 | Trivial | Open |
| 6.7 | Reflex scope widening | P3 | Trivial | Open |
| 7.1 | `fear` implementation | P3 | Medium | Open |
| 7.2 | `investigating` implementation | P3 | Medium | Open |
| 7.3 | `alibi_building` implementation | P3 | Medium | Open |
| 7.4 | `sabotage_watching` | P3 | — | Deferred |

---

## Infrastructure blockers

### ~~Per-agent trace directories~~ (resolved)

The modulabot trace writer now appends a per-instance monotonic
counter to session IDs (`trace.py:_session_id`), so multiple writers
in the same process get unique session directories. `play_match.py`
traces no longer collide.

**Note:** `play_match.py` still constructs each policy with
`num_agents=1`, so each writer creates `agent_0/` inside its unique
session dir. The traces are fully separated — the agent index is just
always 0 within each session.

### ~~Role control in local matches~~ (resolved)

All server-starting scripts (`play_local.py`, `play_match.py`,
`play_debug.py`, `capture.py`, `server.py`) now support
`--force-role {crewmate,imposter}`. This injects
`"slots": [{"role": "<value>"}]` into the server config, using the
server's native slot-pinning feature (`sim.nim:1016-1051`). No
server changes were needed.

**Background:** The server assigns roles via a Fisher-Yates shuffle
seeded by `--seed` (default 42). With seed 42 and 8 players, the
policy agent's slot happens to get crewmate. This is an artifact of
the specific seed, not a structural constraint — but for reproducible
testing, `--force-role` is preferable to seed-hunting.

### Repeated task-hold pattern

Observed in live traces (seeds 2, 13): some task stations cycle
Hold→Confirm timeout→re-select→Hold indefinitely without ever
completing. The icon remains visible through the hold, so the confirm
phase sees the icon on every frame and the miss count never reaches
24. After the confirm window expires, the station is re-selected
(it's the nearest icon-visible station) and the cycle repeats.

**Likely cause:** Some task stations may require multiple A-holds
to complete (multi-step tasks), or the server's interaction rect
doesn't overlap the bot's estimated position despite
`isInsideTaskRect` returning true.

**Impact:** The bot wastes time cycling at one station instead of
moving on. The confirm timeout (48 ticks) limits the damage, but
the station gets re-selected immediately.

**Potential fix:** Track how many hold cycles have been attempted at
a given station. After N failed cycles (e.g. 3), mark it as
`resolvedNotMine` and move on.
