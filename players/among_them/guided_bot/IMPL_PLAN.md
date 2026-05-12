# guided_bot — Implementation Plan (Phase 6+)

> **Living document.** Tracks forward-looking implementation work beyond
> the phase 1–5 foundation. Based on a full mode audit conducted
> 2026-05-01. Update this file as items are completed or priorities
> shift.
>
> Last reviewed: 2026-05-12

---

## Deprecation note

The local `../modulabot/` tree is fully deprecated and kept only for
historical reference. Do not inspect, modify, test, run, or rely on it
while following this plan unless James explicitly asks for modulabot.
Any modulabot mentions below are historical provenance, not active
implementation guidance.

---

## Context

Phases 1–6 built the full perception pipeline, action layer, gameplay
and meeting mode handlers, reflex system, LLM guidance loop, trace
writer, task lifecycle, meeting chat/vote control, and fallback
playability.

A deep audit of all 11 mode handlers revealed that several are
incomplete or stubs. This plan organises the remaining work by
gameplay impact.

---

## Phase 6 — Mode completeness

The core deliverable: make every mode that's on a default or reflex
path produce correct behavior end-to-end.

### 6.1 `task_completing` — hold lifecycle + completion detection (P0)

**Status:** Done. See [`TASK_COMPLETING_DESIGN.md`](TASK_COMPLETING_DESIGN.md)
for the current behavior.

The mode uses a 3-phase lifecycle:

| Sub-phase | Duration | Behavior | Exit condition |
|---|---|---|---|
| Navigate | Variable | waypoint navigation to target station | `isInsideTaskRect` true |
| Hold | `TaskHoldTicks` (74) | Press A, no movement | Timer expires |
| Confirm | Up to `ConfirmWindowTicks` (48) | Stay still, watch icon | Icon absent 4 consecutive frames, OR timeout |

On confirmation: mark task resolved, clear `tcLockedTaskIndex`, re-run
selection. On confirm timeout: clear lock, re-run selection (task might
not be ours).

New scratch fields:
- `tcPhase: enum {Navigate, Hold, Confirm}`
- `tcHoldRemaining: int`
- `tcConfirmDeadlineTick: int`
- `tcConfirmMissCount: int`

New tuning constants:
- `TaskHoldTicks = 74`
- `TaskConfirmWindowTicks = 48`
- `TaskIconMissCompleteTicks = 4`

Selection uses icon evidence, checkout evidence, geometry fallback, and
LLM-directed targets (`TgtIndex`, `TgtNearestAny`, `TgtSpecificRoom`,
or default `TgtNearestMandatory`). `tcAbandonOnNearbyBody` now gates the
body-report reflex.

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

### 6.3 `meeting` — chat emission + cursor-aware voting (P1)

**What exists:** LLM-driven action queue (speak, vote, confirm,
unvote, wait). Cursor-aware vote navigation, edge-triggered cursor
pulses, self-vote prevention, 600-tick timer estimate, auto-vote
delay, chat emission through FFI/Python WebSocket plumbing, and
role-aware evidence/alibi fallback selection are implemented. LLM votes
are hard-guarded only for legality (self, dead players, invalid slots,
and known imposter teammates); symbolic evidence is exposed as a
structured `meeting.evidence_ledger` for the model to weigh instead of
being used as a hard veto.
Live verification on 2026-05-10 confirmed that living bots can vote for
specific slots in 8-agent/2-imposter meetings and ghosts do not vote.
The Bedrock prompt-tuning run on 2026-05-11 confirmed 8-agent meeting
chat/vote sequencing with zero LLM failures and no non-ASCII chat. The
follow-up evidence-ledger runs confirmed solo-survival trust is treated
as exculpatory and missing trust is not used as incriminating evidence.

**What's missing:**

1. **LLM response formatting.** The prompt now asks for bare JSON and
   ASCII chat, but Claude still often wraps valid JSON in Markdown code
   fences. The parser tolerates this; a future pass can try model/API
   settings or post-processing if raw formatting matters.

2. **Self vote memory.** Other players' vote dots are merged into
   `social.votesCast`; the bot's own confirmed target is not yet
   persisted back into social memory after confirmation.

Cursor tracking, vote confirmation, chat emission, and fallback vote
strategy are implemented; LLM-quality iteration remains.

### 6.4 `hunting` — cover rotation + target memory (P2)

**Status:** Done. See [`HUNTING_DESIGN.md`](HUNTING_DESIGN.md) for the
current behavior.

Hunting now has preferred-target pursuit, opportunistic lone-crew kills,
last-seen target memory, kill confirmation, post-kill state, and
task-station cover behavior. `cover_mode: pretending` keeps the built-in
cover patrol active; `cover_mode: idle` suppresses cover movement.

### 6.5 `pretending` — fake A-press + witness swap (P2)

**Status:** Done. See [`PRETENDING_DESIGN.md`](PRETENDING_DESIGN.md) for
the current behavior.

Pretending now supports LLM-directed fake-task targets, fake A-hold,
linger, and `preMaySwapOnWitness` witness-swap behavior.

### 6.6 `fleeing` — minor cleanup (P3)

**Status:** Done. See [`FLEEING_DESIGN.md`](FLEEING_DESIGN.md) for the
current behavior.

Fleeing snaps flee targets to passable terrain, then transitions to a
cover station after duration or distance requirements are met.

### 6.7 Reflex scope — widen body reflexes (P3)

Body→reporting (reflex 1) only fires from `ModeTaskCompleting`.
Body→fleeing (reflex 2) only fires from `ModeHunting`. Both should
fire from any applicable crew/imposter mode.

**Fix:** Change the mode guard in `reflex.nim`:

**Reflex 1 (body → reporting):** Replace:
```nim
if mode == ModeTaskCompleting and
   belief.self.role == RoleCrewmate and ...
```
With:
```nim
if belief.self.role == RoleCrewmate and
   belief.self.alive and
   not belief.self.isGhost and
   mode != ModeReporting and   # don't re-trigger while already reporting
   mode != ModeMeeting and     # don't interrupt meetings
   newBodySeen and ...
```

**Reflex 2 (body → fleeing):** Replace:
```nim
if mode == ModeHunting and
   belief.self.role == RoleImposter and ...
```
With:
```nim
if belief.self.role == RoleImposter and
   belief.self.alive and
   mode != ModeFleeing and     # don't re-trigger while already fleeing
   mode != ModeMeeting and     # don't interrupt meetings
   newBodySeen and ...
```

**Rationale:** A crewmate doing anything outside a meeting should report
a body. An imposter doing anything outside a meeting should flee a body.
The only modes excluded are the
target mode itself (prevent self-trigger) and meetings (never
interrupt voting).

**Files changed:** `reflex.nim` only. No new types or tuning.

---

## Phase 7 — LLM-only imposter alibi

Historical placeholder modes were removed instead of remaining
LLM-selectable no-ops. `alibi_building` is the one retained Phase 7 mode
because it has a concrete strategic purpose: an imposter follows a
specific non-imposter companion color, keeps that player visible, and
fake-holds nearby task stations only while the companion remains in
sight and range. If the companion is lost, fake-task behavior stops and
the mode chases the last-seen position for a short grace window.

---

## Summary table

For historical phase completion, see [`README.md`](README.md).

| Phase | Item | Priority | Effort | Status |
|---|---|---|---|---|
| 6.1 | `task_completing` lifecycle | P0 | Medium | **Done** |
| 6.2 | `reporting` success detection | P1 | Small | **Done** |
| 6.3 | `meeting` chat + cursor | P1 | Medium | **Done** (cursor parse/navigation/confirmation live-verified 2026-05-10; chat emission, evidence/alibi fallback strategy, Bedrock meeting actions, and prompt-tuned vote guards live-verified) |
| 6.4 | `hunting` cover + memory | P2 | Small-medium | **Done** (kill confirmation still affected by localization-drop bug; see TODO.md) |
| 6.5 | `pretending` fake A-press | P2 | Small | **Done** |
| 6.6 | `fleeing` cleanup | P3 | Trivial | **Done** |
| 6.7 | Reflex scope widening | P3 | Trivial | Open |
| 7.1 | `alibi_building` implementation | P3 | Medium | **Done** |

---

## Infrastructure blockers

### ~~Per-agent trace directories~~ (resolved)

The guided_bot trace writer now appends a per-instance monotonic
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
server's native slot-pinning feature. No server changes were needed.

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
