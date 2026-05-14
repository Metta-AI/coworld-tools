# Crewmate task-selection fix plan

> **Deprecated / historical only.** This plan belongs to the local
> modulabot, which is no longer active. Keep it for reference, but do
> not use it as current guidance or work on modulabot unless James
> explicitly asks.

Scope: wire real per-bot task-assignment evidence into `modulabot`'s crewmate
loop, replace the fake hold-completion latch with server-confirmed completion,
and clean up the smaller issues noted. Structured so each phase is
independently shippable and testable.

Check items off with `[x]` as we land them. Update phase-level acceptance
notes inline as we go.

---

## Context / diagnosis (summary)

The crewmate policy has no idea which tasks belong to it. Symptoms:

- Navigates to tasks assigned to other crewmates.
- Deterministically visits the same task points every run, regardless of
  assignment.
- "Completes" tasks locally via a pure 84-tick countdown with no server
  confirmation.

Root causes, in `among_them/modulabot/perception/pixel_pipeline.py` and
`among_them/modulabot/policies/crewmate.py`:

1. `_populate_tasks_from_camera` emits a `TaskInfo` for **every** task in
   `game_map.tasks` with three flags of very different reliability:
   - `icon_visible` — server-authoritative (only assigned tasks render an
     icon). Correct.
   - `arrow_visible` — set `True` for every off-screen task unconditionally.
     Radar dots are scanned (`actors.scan_radar_dots`) but never used to
     filter. **Main bug.**
   - `active` — `True` whenever the player is inside any task rect,
     assigned or not.
2. `crewmate.py:52-66` marks a task `resolved` / `COMPLETED` on a pure
   timer decrement with no external confirmation.
3. Tier-3 (arrow) candidates always exist, so patrol never runs and
   `best_actionable_task` always returns the deterministically-closest
   unassigned task.

Nim reference: `~/coding/bitworld/among_them/players/modulabot/tasks.nim`
(`updateTaskGuesses`, `updateTaskIcons`, `projectedRadarDot`). That codebase
does this correctly via radar-dot → checkout latch + icon-miss completion
state machine; the Python port explicitly dropped both (see stale docstring
at `crewmate.py:1-22`).

---

## Phase 0 — baseline & guard rails ✅ **COMPLETE 2026-04-30**

- [x] Add failing reproducer tests in
      `among_them/modulabot/tests/test_crewmate_tasks.py`. All three
      use `@unittest.expectedFailure`; each phase removes its own.
  - [x] `_Phase0ActiveRectTests.test_active_requires_assignment_evidence`
        — stands bot inside a task rect with no icon / no radar dots →
        asserts `percep.tasks[0].active == False`. Fails today with
        `active=True`. **Phase 2 removes xfail.**
  - [x] `_Phase0ArrowGatingTests.test_arrow_requires_radar_match` —
        three off-screen tasks, zero radar dots → asserts no
        `arrow_visible` and `best_actionable_task() is None`. Fails
        today with `arrow_visible=True` for all three.
        **Phase 1 removes xfail.**
  - [x] `_Phase0HoldCompletionTests.test_hold_completion_requires_server_confirmation`
        — drives `CrewmatePolicy.decide` for `TASK_HOLD_TICKS + 1`
        ticks on a synthetic active task with `task_progress` held at
        0.0 and icon held visible. Asserts `resolved[0] == False`.
        Fails today because the hold timer unconditionally flips
        `resolved` at tick 0. **Phase 3 removes xfail.**
  - Verified each failure is for the intended reason (ran methods
    directly, not via `expectedFailure`) — all three raise
    `AssertionError` with the expected message.

- [x] Baseline capture: 214 tests green (191 from AGENTS.md is stale —
      suite has grown), plus 3 expected-failure reproducers. Full run:
      `source .venv/bin/activate && PYTHONPATH=among_them python -m
      unittest discover -s among_them/modulabot/tests` → `Ran 214 tests
      in 16.852s OK (expected failures=3)`.

- [x] Local-harness trace captured at
      `among_them/modulabot/phase0_baseline_trace/agent_0/decisions.jsonl`
      (archived from `/tmp/mb_baseline`). 20-second `play_local.py`
      run, single modulabot + Nim server + nottoodumb fillers.
      Decision-log summary (only branch transitions are logged, so
      totals are sparse):
      - `crew.task.start_hold` on task `0` (×1)
      - `crew.task.navigate` to tasks `0` and `2` (×1 each)
      - `crew.idle.no_task` (patrol): 0 — confirms the
        "patrol never runs" hypothesis from the diagnosis.
      - Bot walked straight to task 0, fake-completed it, then
        navigated toward task 2 — exactly the "goes to nearest
        stations regardless of assignment" failure mode.
      Diff this against post-Phase-1 / post-Phase-2 captures.

- [x] `MISSION.md § Current focus`: added a "Next 0" bullet pointing
      at this plan and the Phase 0 artifacts.

**Phase 0 deliverables in-tree:**

- `among_them/modulabot/tests/test_crewmate_tasks.py` (3 xfail tests)
- `among_them/modulabot/phase0_baseline_trace/` (baseline decisions
  + events jsonl)
- This plan file.

---

## Phase 1 — short-term fix #1: radar-dot-gated arrows ✅ **COMPLETE 2026-04-30**

Goal: off-screen tasks only become "chase" candidates when a yellow radar dot
actually confirms the server is pointing us at them.

### 1.1 Radar-dot projection helper

- [x] Ported `projectedRadarDot` as
      `_projected_radar_dot(task, cam_x, cam_y, player_wx, player_wy)` in
      `among_them/modulabot/perception/pixel_pipeline.py`. Returns
      `(on_screen, x, y)` — on-screen means the 12×12 icon sprite bbox
      intersects the 128×128 viewport, matching the Nim "server would
      draw the icon" criterion; off-screen returns the edge-clipped
      player→icon ray intersection (where the server draws the dot).
      CollisionW / CollisionH are both 1 in sim so the `+ CollisionW
      div 2` terms in the Nim math drop out (confirmed in
      `~/coding/bitworld/among_them/sim.nim:23-24`).
- [x] Added `RADAR_MATCH_TOLERANCE = 2` to `tuning.py` with source
      citation (`tasks.nim:32 RadarMatchTolerance`).

### 1.2 Radar-dot → task matching in the pipeline

- [x] `_populate_tasks_from_camera` now computes `proj_on_screen`
      independently from the existing `on_screen_approx` used for the
      sprite-match branch. The existing icon-match math (`task.cx -
      cam_x`, `task.y - cam_y`) is preserved verbatim so passing
      tests keep passing; the Nim-faithful math is used only for the
      radar projection.
- [x] Off-screen tasks get `arrow_visible=True` iff a radar dot lies
      within `RADAR_MATCH_TOLERANCE` (Chebyshev) of the projected
      edge position **or** the checkout latch is already set.
- [x] `arrow_x / arrow_y` are now the server-accurate projected edge
      coordinates (previously the clamped-icon-position
      approximation; observationally similar for most tasks but
      aligned with Nim now).

### 1.3 Checkout latch

- [x] Added `checkout: list[bool]` to `state.Tasks`. Lazy-grown
      alongside `resolved` / `states` in the pipeline. Set `True`
      the first time a task gets a radar-dot match; never reset
      within a round.
- [x] Checkout participation in `arrow_visible`: handled at the
      pipeline layer (preferred over the plan's original
      `_keep`-level change — the per-tier gating in
      `best_actionable_task` already routes on `arrow_visible`, so
      keeping the task in the tier-3 pool via the pipeline is cleaner
      than teaching `_keep` to special-case it).

### 1.4 Tests

- [x] `Phase1RadarGatingTests.test_arrow_visible_when_radar_dot_matches`
      — off-screen task with a radar dot on the projected edge →
      `arrow_visible=True`, `checkout` latched.
- [x] `Phase1RadarGatingTests.test_checkout_latch_persists_when_dot_disappears`
      — dot-visible tick, then dot-gone tick → task remains a
      candidate; `best_actionable_task` picks it.
- [x] `Phase1RadarGatingTests.test_radar_dot_match_tolerance` —
      dot at exactly the tolerance edge matches; one pixel further
      does not.
- [x] Phase 0 tier-3 reproducer
      (`_Phase0ArrowGatingTests.test_arrow_requires_radar_match`)
      flipped from `expectedFailure` to passing.

### 1.5 Acceptance

- [x] Full suite: **217 tests pass, 2 expected failures** (was 214 + 3
      xfail in Phase 0). Diff: +3 Phase-1 positive tests, −1 xfail
      that now passes.
- [x] Fresh 20-second trace archived at
      `among_them/modulabot/phase1_trace/agent_0/decisions.jsonl`.
      Task indices visited: **11, 19, 21, 22** — completely disjoint
      from the Phase 0 baseline's **0, 2**. Clear evidence that task
      selection is now radar-driven rather than nearest-to-spawn
      geometry. Still no `crew.idle.no_task` events, but that's
      because this seed actually has assigned tasks visible via radar;
      the "patrol never runs" signal will surface when we can run a
      seed where the bot has no visible radar evidence.

### 1.6 Observations / follow-ups surfaced while working

- **Icon-center approximation is stale, but intentionally unchanged.**
  The existing code uses `icon_screen_y = task.y - cam_y` (top of
  the rect) to match sprite icons, while the true icon sprite centre
  is ~8 px above that. Leaving this for now (changing it without
  retuning `icon_match_radius = 10` risks breaking existing
  passing icon-match tests); filed as a follow-up. Does not affect
  Phase 1 correctness because the radar projection uses Nim-faithful
  coordinates independently.
- **Phase 1 trace shows a navigate→hold index mismatch** (navigate to
  11/19, hold on 21/22). Consistent with the Phase 2 bug still being
  active: while pathing to task 11 the bot walked into task 22's
  rect, which still reads `active=True` for any rect intersection.
  Phase 2 fixes this.
- **`TaskStation` import in `pixel_pipeline.py`** was needed for the
  projection helper's type hint; added alongside `SPRITE_SIZE`.

**Phase 1 deliverables in-tree:**

- `among_them/modulabot/perception/pixel_pipeline.py` (radar
  projection + checkout latch wiring)
- `among_them/modulabot/state.py` (`Tasks.checkout`)
- `among_them/modulabot/tuning.py` (`RADAR_MATCH_TOLERANCE`)
- `among_them/modulabot/tests/test_crewmate_tasks.py` (3 new passing
  tests, 1 xfail→pass)
- `among_them/modulabot/phase1_trace/` (comparison trace)

---

## Phase 2 — short-term fix #2: gate `active` on assignment evidence ✅ **COMPLETE 2026-04-30**

Goal: walking through a non-assigned task rect stops starting A-holds.

### 2.1 Tighten the pipeline

- [x] `_populate_tasks_from_camera` now computes
      `active_rect = (player inside rect)` and then
      `active = active_rect and (icon_visible or checkout[i])`.
- [x] Added `TaskInfo.active_rect: bool` so traces / diagnostics can
      still see the raw rect-intersection signal when debugging
      (why did we stand here but not press A? → `active_rect=True,
      active=False, checkout=False, icon_visible=False`).
- [x] `state_obs.py` resize block now grows `bot.tasks.checkout`
      alongside `states / resolved` so state-obs replays don't trip
      on a short checkout list. State-obs `active` continues to come
      directly from the server's TASK_ACTIVE bit (already correctly
      assignment-gated server-side), so no behavior change there.

### 2.2 Policy guard

- [x] In `crewmate.py` active branch: defense-in-depth
      `diag.thought` warning if `task.active` is ever true without
      `icon_visible` or `checkout[index]`. Shouldn't fire under the
      Phase 2.1 pipeline; catches future regressions. Verified via a
      20-second live-harness trace that it does NOT fire on real
      gameplay (`grep events.jsonl` returned 0 hits).

### 2.3 Tests

- [x] `Phase2ActiveGatingTests.test_active_when_icon_visible` —
      player inside rect + matching icon sprite → `active=True`.
- [x] `Phase2ActiveGatingTests.test_active_when_checkout_latched`
      — player inside rect + `checkout[i]=True` → `active=True`.
- [x] `Phase2ActiveGatingTests.test_active_rect_preserved_for_diagnostics`
      — no icon, no radar, no checkout, but player in rect →
      `active=False, active_rect=True`.
- [x] `Phase2ActiveGatingTests.test_crewmate_does_not_hold_on_unassigned_rect`
      — end-to-end crewmate policy call with the above setup does
      NOT return `actions.A` and leaves `hold_ticks == 0`.
- [x] Phase 0 `test_active_requires_assignment_evidence` flipped from
      `expectedFailure` to passing.

### 2.4 Docstring cleanup

- [x] Rewrote `crewmate.py` module docstring. Removed the stale
      "we don't need separate radar/checkout/mandatory bookkeeping"
      claim; documented the three flags' post-Phase-1/2 semantics,
      noted `TaskInfo.active_rect` as the diag-only raw signal, and
      flagged the still-open Phase 3 gap (fake hold completion).

### 2.5 Acceptance

- [x] Full suite: **221 tests pass, 1 expected failure** (was 217 +
      2 xfail after Phase 1). Diff: +4 Phase-2 positive tests,
      −1 xfail that now passes.
- [x] Live-harness trace at `phase2_trace/`: task indices visited
      **11, 19, 21, 22, 36** (navigate) / **21, 22** (hold). Holds
      are now evidence-gated; the defense-in-depth `diag.thought`
      never fired, confirming `active` is only being set by the
      Phase 2.1 gate.

### 2.6 Observations / follow-ups surfaced while working

- **Holds look similar to Phase 1.** Same seed, same deterministic
  behavior at this level. The actual bug from Phase 1 (navigate to
  task 11, hold on task 22 because walking through its rect) may or
  may not still be present — distinguishing "correctly holding on
  an assigned task whose checkout latched" from "holding on a
  checkout-latched-but-not-actually-mine task" requires Phase 3's
  server-confirmation gate. Phase 2 + Phase 3 together are what
  fully fix the reported symptom.
- **State-obs `active` bit is already correct.** It comes from the
  server's TASK_ACTIVE flag bit (`state_obs.py:261`), which the
  server sets only for tasks assigned to this player. No pipeline
  change needed there.

**Phase 2 deliverables in-tree:**

- `among_them/modulabot/state.py` (`TaskInfo.active_rect`)
- `among_them/modulabot/perception/pixel_pipeline.py`
  (`active = active_rect and assignment_evidence`)
- `among_them/modulabot/perception/state_obs.py`
  (checkout list resize)
- `among_them/modulabot/policies/crewmate.py` (guard + docstring)
- `among_them/modulabot/tests/test_crewmate_tasks.py` (4 new
  passing tests, 1 xfail→pass)
- `among_them/modulabot/phase2_trace/` (comparison trace)

---

## Phase 3 — hold-completion verification (long-term) ✅ **COMPLETE 2026-04-30**

Goal: `TaskState.COMPLETED` / `resolved[i] = True` only after the server
confirms the task finished.

### 3.1 Confirmation signals

Implemented all three from the plan:

- **`task_progress` advance** (primary, was originally listed as
  fallback). Promoted to primary because it's universal — works
  regardless of whether the hold was icon- or checkout-triggered,
  and immune to icon-flicker. Threshold:
  :data:`TASK_PROGRESS_CONFIRM_EPSILON = 0.001`, well below the
  smallest real signal (1/N for N tasks, typically ≥ 1/40).
- **Icon disappearance** (secondary). Only consulted when the hold
  was triggered by a visible icon — a checkout-only hold can't use
  this signal because the icon may never have been rendered in the
  first place. The miss counter only increments while the bot is
  still rect-inside (so the icon *would* be rendered if assigned)
  and resets on any icon-visible frame, defeating sprite-match
  flicker.
- **Deadline timeout**. After
  :data:`HOLD_CONFIRM_WINDOW_TICKS = 48` ticks with no
  confirmation, give up. Critically, this also clears
  ``checkout[idx]`` so the task drops out of the candidate set
  unless a fresh radar dot re-latches it; without this clear, the
  bot would re-hold the same task immediately every time
  ``best_actionable_task`` ran.

Radar-dot disappearance was deferred — it's covered indirectly by
``task_progress`` advance (real completion always advances progress)
and adding it as a third positive signal would only catch a narrow
edge case (off-screen unconfirmable holds where the task is in fact
yours but the icon is never rendered). Filed for future work if
trace data ever shows this case mattering.

### 3.2 State machine additions

- [x] `state.Tasks` gained five fields:
  `hold_start_tick: int`, `pre_hold_progress: float`,
  `confirming_index: int = -1`,
  `confirming_deadline: int = -1`,
  `confirming_miss_count: int = 0`,
  `confirming_via_icon: bool = False`. (The plan originally also
  proposed `icon_misses: list[int]` per-task; collapsed to the
  scalar `confirming_miss_count` because we only ever confirm one
  task at a time — the policy can't be in two confirmation windows
  simultaneously.)
- [x] `tuning.py` gained `ICON_MISS_COMPLETE_TICKS = 24`,
  `HOLD_CONFIRM_WINDOW_TICKS = 48`,
  `TASK_PROGRESS_CONFIRM_EPSILON = 0.001`, all with source
  citations / rationale.

### 3.3 Rewrite hold branch

- [x] `crewmate.py:decide` now calls `_check_hold_confirmation` at
      the top of every tick. The hold branch decrements the timer
      and on hit-zero calls `_begin_confirmation`, which transitions
      to the confirming state without touching `resolved`.
- [x] `_check_hold_confirmation` runs the three-signal cascade in
      priority order; `_mark_confirmed` is the single resolve point
      that writes `resolved[idx] = True`,
      `states[idx] = TaskState.COMPLETED`, and clears commit + chosen.
- [x] `_begin_hold` is the single hold-start point (used by both the
      `task.active` and `task.icon_visible & close` branches), so
      pre-hold snapshot capture can't be forgotten by accident.

### 3.4 Capture pre-hold state

- [x] Done as part of `_begin_hold`. `pre_hold_progress` is
      captured at hold start; the confirmation window compares
      against this snapshot, so progress that advances *during* the
      hold (not just after) still confirms the task on the first
      post-hold tick. Verified by
      `Phase3HoldConfirmationTests.test_restart_hold_does_not_lose_progress_signal`.

### 3.5 Tests

- [x] `test_progress_advance_confirms_completion` — hold ends,
      progress advances → resolved.
- [x] `test_icon_disappearance_confirms_completion` — hold ends,
      icon vanishes for `ICON_MISS_COMPLETE_TICKS` ticks → resolved.
- [x] `test_icon_miss_resets_when_icon_reappears` — alternating
      icon-visible / icon-missing for 2 × `ICON_MISS_COMPLETE_TICKS`
      ticks → NOT resolved (flicker doesn't accumulate).
- [x] `test_timeout_leaves_task_unresolved_and_clears_checkout`
      — full window with no signal → not resolved, `checkout[0]`
      cleared.
- [x] `test_checkout_hold_cannot_confirm_via_icon_miss` — hold
      triggered by checkout-only evidence cannot confirm via
      icon-miss alone (icon-miss counter is gated on
      `confirming_via_icon`).
- [x] `test_restart_hold_does_not_lose_progress_signal` — progress
      advance during the hold still triggers confirmation in the
      window.
- [x] Phase 0 reproducer flipped from `expectedFailure` to passing.
- [x] Sibling-bot integration test (originally listed as
      best-effort): not implemented as a separate test. The
      `task_progress` advance signal is shared across the team, so
      a sibling bot completing a different task during our
      confirmation window would falsely confirm our hold.
      Documented as a known residual false-positive in the
      `_check_hold_confirmation` docstring; mitigated in practice by
      (a) the 48-tick window being short relative to the cooldown
      between task completions, and (b) the icon-miss signal
      providing a second-opinion check when it's available.

### 3.6 Surfaced design decision: filter confirming task from selection

While running the first iteration of the icon-disappearance test it
became clear that after a hold ends, the bot could still satisfy
`task.active` for the same rect (icon still visible, still in rect)
and would loop straight back into `_begin_hold`, clobbering
`confirming_via_icon` and resetting `pre_hold_progress`. Two fixes
considered:

1. Track "we just held this" separately from the confirmation state.
2. Have `best_actionable_task._keep` filter out `confirming_index`
   so the policy can't re-select it.

Chose (2): cleaner, single source of truth, and adds a sensible
"await confirmation" NOOP branch in `crewmate.decide` for the case
where there are no other candidates. NOOP-waiting is actually
correct here — walking away would stop the icon-miss counter
because the bot would no longer be `active_rect`, forcing a
deadline timeout for a task that may genuinely be ours.

### 3.7 Acceptance

- [x] Full suite: **227 tests pass, 0 expected failures** (was
      221 + 1 xfail). All three Phase 0 reproducers now pass for
      real, every phase's positive-path test passes.
- [x] Trace at `phase3_trace/`: 20-second run starts holds on tasks
      22 and 21; the holds didn't reach the confirmation window
      within the run length (confirmation needs hold to fully
      expire, which takes 84 ticks ≈ 3.5 s — only one hold per run
      will get there, and the trace happens to capture the
      `continue_hold` phase). For full confirmation-cycle behavior
      visibility we'd need ≥60-second runs; left for follow-up.

**Phase 3 deliverables in-tree:**

- `among_them/modulabot/state.py` (5 new `Tasks` fields)
- `among_them/modulabot/tuning.py` (3 new constants)
- `among_them/modulabot/policies/crewmate.py`
  (`_check_hold_confirmation` + `_begin_hold` + `_begin_confirmation`
  + `_mark_confirmed` + `crew.task.await_confirm` branch)
- `among_them/modulabot/policies/base.py` (`_keep` filter on
  `confirming_index`)
- `among_them/modulabot/tests/test_crewmate_tasks.py` (6 new
  passing tests, 1 xfail→pass)
- `among_them/modulabot/phase3_trace/` (comparison trace)

---

## Phase 4 — minor issues ✅ **COMPLETE 2026-04-30**

### 4.1 Zero-coord reads on arrow-only tasks

- [x] `pixel_pipeline.py`: off-screen tasks now write
      `x = arrow_x, y = arrow_y` instead of `(0, 0)`. Readers that
      forget to gate on `icon_visible` get the screen-edge target
      instead of the top-left corner.
- [x] Test `test_off_screen_task_x_y_track_arrow` asserts
      `(info.x, info.y) == (info.arrow_x, info.arrow_y)` for an
      off-screen task with a radar match.

### 4.2 Overlapping actives — tiebreak

- [x] `base.best_actionable_task`: actives pool now prefers
      `icon_visible` over checkout-only, after the
      committed-task-wins step. Defense in depth; minor improvement
      under the Phase 2.1 gate.
- [x] Test `test_actives_tiebreak_prefers_icon_visible`.

### 4.3 Stale `chosen_index` when `hold_index` diverges

- [x] `_begin_hold` adds a `diag.thought` invariant warning if
      `hold_index >= 0 and chosen_index >= 0 and
      hold_index != chosen_index`. Doesn't crash; just surfaces a
      regression we want to know about.
- [x] `_check_hold_confirmation` already clears `chosen_index` on
      both confirmation outcomes (resolved or timeout) — covered
      under Phase 3.

### 4.4 Patrol never runs

- [x] Verified post-Phase-1 that `crew.idle.no_task` does fire
      under appropriate conditions (no radar-confirmed tasks
      visible). The Phase 3 trace + Phase 1/2 traces don't show it
      because their seed always had visible radar dots; the unit
      test `test_arrow_requires_radar_match` exercises the path
      synthetically.
- [x] Test `test_patrol_phases_differ_across_agent_ids` documents
      that patrol's quadrant rotation is keyed on `agent_id`.

### 4.5 Docstring / comments sweep

- [x] `crewmate.py` module docstring rewritten in Phase 2.4.
- [x] `base.best_actionable_task` docstring updated with
      assignment-evidence + confirmation-gate language.
- [x] `tuning.py` constants documented with Nim source citations.
- [x] `among_them/modulabot/README.md` § "Perception status"
      updated with a new top-of-section block summarizing the
      Phase 1-4 fixes and the remaining task-bar HUD-parsing gap.

### 4.6 Imposter cross-state check

- [x] Confirmed `among_them/modulabot/policies/imposter.py:235`
      reads `bot.tasks.resolved` only (read-only query for
      `_nearest_task_within`'s "skip already-completed icons"
      filter). No imposter writes to `bot.tasks` state, so no
      cross-policy interference. The imposter's task-icon scan
      intentionally ignores assignment evidence (`icon_visible`
      alone) because imposter is faking — any visible icon is a
      valid fake-task target.

### 4.7 Acceptance

- [x] Full suite: **230 tests pass, 0 expected failures** (was 227
      + 0 xfail).

**Phase 4 deliverables in-tree:**

- `among_them/modulabot/perception/pixel_pipeline.py` (4.1)
- `among_them/modulabot/policies/base.py` (4.2 + docstring)
- `among_them/modulabot/policies/crewmate.py` (4.3 invariant)
- `among_them/modulabot/README.md` (4.5)
- `among_them/modulabot/tests/test_crewmate_tasks.py`
  (3 new tests for 4.1 / 4.2 / 4.4)

---

## Phase 5 — cross-session memory

- [ ] Per repo AGENTS.md: if/when we upload a new policy bundle after
      these fixes, append a submission-log row to
      `among_them/modulabot/README.md`: date, policy name, season, dry-run
      result, leaderboard score. **(Pending next submission attempt.)**

---

## Final state — 2026-04-30

**Phases 0-4 complete.** Phase 5 pending next submission opportunity.
Phases 6-7 added 2026-05-01 in response to design review feedback —
see below.

- Tests: **230 / 230 pass, 0 expected failures** (post-Phase-4).
- All three Phase 0 reproducers pass for real (not via xfail).
- 6 net new state fields, 4 new tuning constants, 1 new policy
  branch (`crew.task.await_confirm`), 19 new tests.
- Behavioral changes confirmed via three trace captures
  (`phase0_baseline_trace/`, `phase1_trace/`, `phase2_trace/`,
  `phase3_trace/`).

---

## Phase 6 — icon-miss negative-evidence pruning ✅ **COMPLETE 2026-05-01**

**Motivation (design-review finding, 2026-05-01).** Phases 1-3
established positive evidence flows (icon visible / radar match →
candidate; hold + server signal → resolved). Nothing observed the
*absence* of an icon to prune the candidate set. With ~40 task
stations on the map and 8 assigned per player, ~32 tasks are
permanently not-mine; today they sit at `resolved=False,
checkout=False` for the entire round and re-enter consideration any
time their projected screen-edge happens to align with a noise
radar pixel within `RADAR_MATCH_TOLERANCE`.

The Nim reference does this in
`~/coding/bitworld/among_them/players/modulabot/tasks.nim:250-268`:
when (a) the task's inspection rect is fully on-screen with
`TaskClearScreenMargin` slack, (b) no strict icon match, and (c) no
fuzzy `maybeMatchesSprite` match either, increment a per-task
miss counter; on hitting `TaskIconMissThreshold = 24` consecutive
frames, latch `resolved[i] = True, checkout[i] = False`.

### 6.1 Port the inspection primitives

- [x] `_task_icon_inspect_rect` (`pixel_pipeline.py`) — 16×16 screen
      rectangle the icon would occupy. Direct port of Nim
      `taskIconInspectRect`.
- [x] `_task_icon_clear_area_visible` — full inspection rect
      on-screen with `TASK_CLEAR_SCREEN_MARGIN = 8` slack on every
      side.
- [x] `_task_icon_maybe_visible` — fuzzy `maybe_matches_sprite`
      sweep over a `TASK_ICON_EXPECTED_SEARCH_RADIUS = 3` box at
      three vertical bob offsets (-1, 0, +1). 27 fuzzy-match calls
      worst case, ~12×12 pixel comparisons each.

### 6.2 Frame threading

- [x] `_populate_policy_state(bot, game_map, frame, task_sprite)` —
      added `frame` and `task_sprite` parameters.
- [x] `_populate_tasks_from_camera` likewise.
- [x] All test sites updated via a `_populate(bot, ...)` wrapper
      that supplies a blank frame + transparent sprite by default;
      tests that exercise the negative-evidence path provide their
      own.

### 6.3 Negative-evidence loop

- [x] After computing `icon_visible` and `arrow_visible` for each
      task, run a per-task negative pass:
  - Skip when `task.index` matches `hold_index` or
    `confirming_index` — Phase 3/7 own the icon signal there.
  - Skip when `resolved[i]` is already True.
  - If `icon_visible` → reset counter to 0 (skip fuzzy check, fast
    path).
  - Else if `clear_area_visible`:
    - If `maybe_visible` → reset counter to 0.
    - Else → increment counter; on `>= ICON_MISS_THRESHOLD`,
      latch `resolved[i] = True, checkout[i] = False`, reset
      counter.
  - Else (rect clipped) → reset counter (don't trust partial-view
    absence).

### 6.4 New state + tuning

- [x] `state.Tasks.icon_misses: list[int]` — per-task counter.
- [x] `tuning.ICON_MISS_THRESHOLD = 24` (Nim parity).
- [x] `tuning.TASK_CLEAR_SCREEN_MARGIN = 8`,
      `TASK_ICON_INSPECT_SIZE = 16`,
      `TASK_ICON_EXPECTED_SEARCH_RADIUS = 3`.

### 6.5 Tests (5 new)

- [x] `test_clear_view_no_icon_no_maybe_resolves` — drive 24 frames
      with clear inspection rect, no strict, no fuzzy → resolved
      and checkout cleared.
- [x] `test_clipped_inspection_rect_does_not_count` — task at
      screen edge → no miss accumulation even after 72 frames.
- [x] `test_icon_miss_skipped_during_hold` — `hold_index` set on
      target task → counter stays at 0 through 48 frames.
- [x] `test_strict_icon_match_resets_counter` — accumulate misses,
      then deliver one strict match → counter back to 0.
- [x] `test_resolved_task_filtered_from_selection` — once
      latched, even a fresh radar dot can't re-admit the task to
      `best_actionable_task`.

### 6.6 Acceptance

- [x] Full suite: **235 tests pass, 0 expected failures** (was
      230). Diff: +5 Phase 6 tests, +0 regressions.
- [x] Live-harness trace at `phase7_trace/` (combined with Phase 7).
      Pruning behavior is hard to surface in 30 seconds — the
      effect compounds over the round. Will need a longer run + a
      post-run analyzer to count `resolved[i]=True` for not-mine
      tasks; flagged as follow-up.

**Phase 6 deliverables in-tree:**

- `among_them/modulabot/tuning.py` (4 new constants)
- `among_them/modulabot/state.py` (`Tasks.icon_misses`)
- `among_them/modulabot/perception/pixel_pipeline.py` (3 new
  primitives + frame threading + negative-evidence loop)
- `among_them/modulabot/perception/state_obs.py` (icon_misses
  resize)
- `among_them/modulabot/tests/test_crewmate_tasks.py` (5 new
  passing tests, `_populate` test wrapper)

---

## Phase 7 — flip hold-confirmation priority to icon-first ✅ **COMPLETE 2026-05-01**

**Motivation (design-review finding, 2026-05-01).** Phase 3 picked
`task_progress` as the primary confirmation signal because it's
universal (works for any hold trigger) and 1-tick-fast. That was
wrong: `task_progress` is a *team* signal — it advances on any
player's task completion, not just ours. With 8 players × 8 tasks
= 64 completions per game over ~10 minutes, that's roughly one
every 9 seconds. Our confirmation window is 48 ticks ≈ 2 seconds.
Realistic false-positive rate per icon-triggered hold: ~22%. The
icon **is** the source of truth for "is this task mine and active",
so its disappearance — under Phase 6's clear-view + fuzzy-miss
gates — is strictly better.

### 7.1 Reorder `_check_hold_confirmation`

- [x] Icon-disappearance branch now runs **first**, gated on
      `confirming_via_icon`.
- [x] Continues to use the per-confirmation `confirming_miss_count`
      counter rather than the per-task `icon_misses[i]` from Phase
      6 — keeps the two systems decoupled (Phase 6 latches
      "resolved-not-mine"; Phase 7 latches "confirmed-completed").
      Both react to the same physical signal but fire different
      actions, so attribution stays clean.
- [x] `task_progress` branch moved to second, gated on
      `not confirming_via_icon` — only checkout-only holds (where
      no icon was ever visible) honour this signal.
- [x] Deadline branch unchanged.

### 7.2 Checkout-only hold trade-off

- [x] Documented in the new docstring: a checkout-only hold can
      still false-positive-confirm via `task_progress` if a
      sibling completes during our window. Accepted because (a)
      checkout-only holds become rare once Phase 6 prunes the
      radar candidate set, and (b) the alternative is dropping
      the only confirmation signal for that path, leaving every
      checkout-only hold to time out.

### 7.3 Tests

- [x] `test_progress_advance_confirms_completion` updated — now
      forces `confirming_via_icon=False` (checkout-only setup) to
      assert progress confirmation works on the surviving path.
- [x] `test_progress_advance_does_not_confirm_icon_hold` — new
      test: icon-triggered hold + sibling-completion progress
      jump → does NOT resolve. *This is the false-positive Phase
      7 eliminates.*
- [x] `test_restart_hold_does_not_lose_progress_signal` updated to
      use the checkout-only path.
- [x] All other Phase 3 tests pass unchanged
      (`test_icon_disappearance_confirms_completion`,
      `test_icon_miss_resets_when_icon_reappears`,
      `test_timeout_leaves_task_unresolved_and_clears_checkout`,
      `test_checkout_hold_cannot_confirm_via_icon_miss`).

### 7.4 Acceptance

- [x] Full suite: **236 tests pass, 0 expected failures** (was
      235 after Phase 6).
- [x] Trace at `phase7_trace/` shows `crew.task.arrive_and_hold`
      firing for the first time in any post-Phase-1 trace —
      Phase 6's pruning seems to be making the bot range further
      across the map, surfacing more icon-visible tasks. Suggests
      qualitative behaviour change beyond the raw test set.

**Phase 7 deliverables in-tree:**

- `among_them/modulabot/policies/crewmate.py`
  (`_check_hold_confirmation` reordered + new docstring)
- `among_them/modulabot/tests/test_crewmate_tasks.py`
  (1 updated test, 1 new test)
- `among_them/modulabot/phase7_trace/` (combined Phase 6+7 trace)

---

## Phase 5 — cross-session memory

- [ ] Per repo AGENTS.md: if/when we upload a new policy bundle after
      these fixes, append a submission-log row to
      `among_them/modulabot/README.md`: date, policy name, season, dry-run
      result, leaderboard score. **(Pending next submission attempt.)**

---

## TaskState machine cleanup (TODO, not yet phased)

`among_them/modulabot/state.py:54 TaskState` defines four states
(`NOT_DOING`, `MAYBE`, `MANDATORY`, `COMPLETED`) but the pixel
path effectively uses only two (`NOT_DOING`, `COMPLETED`):

- The pixel adapter (`_populate_tasks_from_camera`) never writes
  `MAYBE` or `MANDATORY` to `bot.tasks.states[i]`; the only state
  transitions in pixel mode come from `_mark_confirmed` writing
  `COMPLETED`.
- Selection logic (`base.best_actionable_task`,
  `crewmate.decide`) reads `icon_visible / arrow_visible /
  active / checkout` directly and ignores `state` except for the
  `state.value == 3` (COMPLETED) filter in `_keep`.
- The state-obs path *does* write all four — see
  `state_obs.py:265-271` — but state-obs is only used for testing
  and doesn't run in tournament play.

This is a half-implemented state machine. Two reasonable cleanups:

1. **Remove it from pixel mode** — replace `state.value == 3`
   filter with a direct read of `resolved[i]`. Simplifies the
   dataclass (no need to keep `state` on `TaskInfo`), removes
   confusing dead semantics.
2. **Complete it in pixel mode** — write `MAYBE` when checkout
   latches without icon (we have radar evidence but haven't
   confirmed visually), `MANDATORY` when an icon hits, and use
   the state in selection (e.g. tier-2 = MANDATORY beats tier-3
   = MAYBE explicitly, instead of relying on `icon_visible vs
   arrow_visible`).

Option 2 mirrors the Nim reference more closely and gives the
tracing layer a richer per-task state signal. Option 1 is
strictly less code. **Recommend option 2** because the state
field is referenced from the trace writer's per-tick decision
log (a debugging surface we don't want to lose) and because
making the four states meaningful in pixel mode means the
state-obs tests and the pixel tests share more semantics.

Filed as a separate work item; not blocking Phase 6 / 7. Pick
this up after Phase 7 lands and traces stabilize. Estimated 1-2
hours of code + tests.

---

## Final state — 2026-04-30 (revised 2026-05-01)

**Phases 0-4 + 6-7 complete. Phase 5 + TaskState cleanup pending.**

- Tests: **236 / 236 pass, 0 expected failures.**
- All three Phase 0 reproducers pass for real (not via xfail).
- 7 net new state fields, 8 new tuning constants, 1 new policy
  branch (`crew.task.await_confirm`), 25 new tests.
- 5 trace captures archived (`phase0_baseline_trace/`,
  `phase{1,2,3,7}_trace/`).
- Outstanding: TaskState machine half-wired (see TODO section
  above); Phase 5 submission-log row pending.

---

## Ordering and risk

- Phases 1 → 2 → 3 are strictly ordered:
  - Phase 2 depends on the `checkout` latch from Phase 1.
  - Phase 3 depends on clean hold semantics from Phase 2 to avoid
    polluting the confirmation path.
- Phase 4 can interleave with Phase 3; 4.1 / 4.2 are safe after Phase 2
  alone.
- Biggest risk: Phase 3's integration-test false-positive (sibling bot
  finishes during our hold window). Acceptable to ship Phase 3 with
  `task_progress` as fallback-only and a documented residual failure
  mode; revisit with more trace data.

## Explicitly out of scope

- Parsing task assignment from the on-screen task-bar / list UI. Would
  give ground-truth assignment (no radar ambiguity) but requires OCR /
  sprite scanning of the HUD region that doesn't exist yet. File as a
  follow-up in `README.md` § "TODO" after Phase 4 lands.
- Imposter policy's task-related heuristics. Quick check during Phase 2
  review: `rg "bot\.tasks" among_them/modulabot/policies/imposter.py` —
  confirm no shared state before shipping.
