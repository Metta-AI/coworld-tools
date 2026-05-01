# modulabot (Python port)

A modular scripted agent for cogames Among Them. Python port of the Nim
[modulabot][nim-design] architecture: one concern per file, state decomposed
into sub-records, pluggable perception and policy layers.

[nim-design]: file:///Users/jamesboggs/coding/bitworld/among_them/players/modulabot/DESIGN.md

**Status (2026-05-01):** scaffolding + cogames wrapper + full perception
layer + crewmate/imposter/voting policies all shipped. Perception runs
end-to-end on real pixel observations (sprite matching, camera
localization, voting parser, A\* pathfinding) at ~2.5 ms per frame with
Nim FFI. Crewmate task selection, approach, hold, and completion all
verified server-correct after the [crewmate task fix
plan](CREWMATE_TASK_FIX_PLAN.md) (Phases 0-4 + 6-7, May 2026). 236 tests,
0 expected failures. See **Perception status** and **Crewmate task
lifecycle** below.

## Reality check: cogames Among Them is pixels-only

Empirically verified via `among_them/scripts/play_local.py`:

```
Observation space: shape=(4, 128, 128) dtype=uint8 kind=pixels
Unique palette indices: [0, 2, 3, 5, 14]   # PICO-8 palette
```

The `BitWorldRunner` (`mettagrid.runner.bitworld_runner`) hardcodes
`observation_kind="pixels"` — the structured "state observation" layout in
`bitworld_pufferlib.py` only exists in the training harness, **not** in
the tournament path. Any serious Among Them bot needs:

1. **Map localization** — the frame is egocentric; we need to know where
   we are in the world to do A\* or task targeting.
2. **Sprite recognition** — find the player, other crewmates, bodies,
   task icons, radar dots, voting cursor.
3. **Task pixel logic** — recognize which task we're on top of and when
   to press A.
4. **Voting-screen OCR** — parse the cursor position and chat text.

All four are now implemented. See [Perception status](#perception-status)
for the per-capability table and perf numbers.

## Why a port

The Nim modulabot is a ~4 kLOC visual client that does pixel-perfect
localization, A\* pathfinding, OCR, and a long list of perception
gymnastics. The Python port reproduces the architecture and most of the
behaviour, with key kernels offloaded to native Nim via ctypes for
performance:

- **Modular layout** — one concern per file; nothing resembles the
  4700-line monolith the port started from.
- **Sub-record state** — `Perception`, `Motion`, `Tasks`, `Goal`,
  `Identity`, `Evidence`, `ImposterState`, `VotingState`, `ChatState`,
  `Diag`. Each module owns the sub-records it mutates.
- **Per-frame pipeline** — clear perception → update evidence/motion →
  dispatch by phase → policy writes goal + action.
- **Branch IDs** — every policy branch calls `bot.fired(branch_id)` before
  returning, so the structured JSONL trace writer can attribute
  decisions later (see [Tracing](#tracing)).

## Layout

```
among_them/modulabot/
├── __init__.py              # re-exports AmongThemPolicy
├── policy.py                # cogames MultiAgentPolicy wrapper
├── bot.py                   # BotCore: per-agent orchestrator
├── state.py                 # sub-record dataclasses + sprite match types
├── data.py                  # palette, map, sprites loader (pre-rendered from aseprite)
├── data/                    # shipped reference artefacts (PNGs + JSON)
│   ├── map.png              # 952×534 skeld2 map image (aseprite → pixie PNG)
│   ├── walk.png             # walkable-pixel mask
│   ├── wall.png             # wall-pixel mask
│   ├── map.json             # rooms, tasks, button, home rectangles
│   ├── spritesheet.png      # eight 12×12 reference sprites (palette-indexed)
│   └── tiny5.png            # tiny5 pixel font (marker-delimited variable width)
├── geometry.py              # coord math, camera↔world, task centres
├── frame.py                 # unpack, interstitial gate, ignore-pixel mask
├── sprite_match.py          # matches_sprite / maybe_matches / shadowed
├── actors.py                # scan_all: crewmates, bodies, ghosts, task icons, role HUD, radar
├── actions.py               # BitWorld 27-action helpers
├── tuning.py                # tunable constants
├── diag.py                  # intent / thoughts (no behaviour-affecting state)
├── chat.py                  # meeting-chat templates + queue
├── evidence.py              # body/witness bookkeeping
├── localize.py              # camera lock: patch-hash + local refit + spiral
├── ascii.py                 # variable-width pixel-font OCR (tiny5)
├── voting.py                # voting-screen parse: slots, cursor, chat OCR
├── path.py                  # A* on the walk mask, path-lookahead waypoint
├── trace.py                 # structured JSONL trace writer (opt-in)
├── nim_perception/          # FFI surface only (lib.nim + build.py +
│                            # ctypes loader); the kernels themselves
│                            # live in among_them/common/perception_kernels/
│                            # and are shared with guided_bot
├── perception/
│   ├── __init__.py
│   ├── common.py            # dispatcher: state_obs vs pixel pipeline
│   ├── pixel_pipeline.py    # main pixel path: scan_all + localize + voting
│   │                        # parse + adapter (incl. radar projection,
│   │                        # checkout latch, icon-miss negative-evidence
│   │                        # pruning — see CREWMATE_TASK_FIX_PLAN.md)
│   ├── state_obs.py         # structured state → Perception (legacy/test path)
│   └── pixel_obs.py         # minimal pixel fallback (used when no reference_data)
├── policies/
│   ├── __init__.py
│   ├── base.py              # Policy ABC + best_actionable_task + nav helpers
│   ├── crewmate.py          # CrewmatePolicy: tasks (select/approach/hold/
│   │                        # confirm), report bodies, patrol
│   ├── imposter.py          # ImposterPolicy: fake tasks, kill, flee
│   └── voting.py            # VotingPolicy: cursor + commit
├── tests/
│   ├── test_smoke.py        # pipeline + behaviour smoke tests
│   ├── test_perception.py   # data / geometry / frame / sprite_match / actors units
│   ├── test_perception_snapshots.py  # real captured-frame regression snapshots
│   ├── test_localize.py     # score_camera + patch index + Localizer fixture tests
│   ├── test_ascii.py        # pixel-font loader + OCR primitives
│   ├── test_voting.py       # voting parse: grid / slots / cursor / chat OCR
│   ├── test_path.py         # A* passable/heuristic/find_path + real-map perf
│   ├── test_navigation.py   # goal-setting + A* wiring into policies
│   ├── test_pixel_pipeline.py  # end-to-end: BotCore + reference_data + fixture frames
│   ├── test_motion.py       # world-coord velocity + teleport guard + deadband
│   ├── test_trace.py        # trace writer + non-perturbation invariants
│   ├── test_nim_perception.py # native↔numpy parity tests
│   ├── test_crewmate_tasks.py # selection/approach/hold/confirm coverage
│   │                          # (Phases 0-4 + 6-7 of CREWMATE_TASK_FIX_PLAN.md)
│   └── fixtures_frames.npy  # 275 frames of real gameplay (12s @ 22Hz)
├── phase0_baseline_trace/   # pre-fix decisions trace (reference)
├── phase1_trace/            # after radar-gated arrows
├── phase2_trace/            # after evidence-gated active
├── phase3_trace/            # after server-confirmed completion
└── phase7_trace/            # after Phase 6+7 (negative-evidence + icon-first)
```

## Running the smoke tests

```bash
PYTHONPATH=among_them .venv/bin/python -m unittest discover \
    -s among_them/modulabot/tests
```

Expected: **236 tests, 0 failures, 0 expected failures** with the Nim
FFI loaded. With ``MODULABOT_DISABLE_NATIVE=1`` a handful of parity
tests skip (they require the native library); everything else still
passes via the pure-Python fallback.

Per-area test counts (rough):

| Area | tests |
|---|---|
| Perception (sprite, localize, ASCII, voting parse) | ~80 |
| A\* + navigation | ~25 |
| Pixel pipeline end-to-end | ~15 |
| Snapshots (275-frame fixture) | ~30 |
| Crewmate task lifecycle (Phases 0-4 + 6-7) | 25 |
| Trace writer (incl. non-perturbation pins) | ~12 |
| Smoke / behaviour | ~15 |
| Misc (motion, ASCII, etc.) | ~30 |

## Running locally against the real server

We ship a `scripts/play_local.py` harness that:

1. Starts the pre-built Nim `among_them` server from
   `~/coding/bitworld/out/among_them` (override with
   `AMONG_THEM_BINARY=...`).
2. Fills the lobby with headless `nottoodumb` bots from the same
   directory.
3. Connects our policy as one player over the real WebSocket protocol,
   running it through the actual `mettagrid.runner.bitworld_runner` code
   path the tournament uses.
4. Logs the observation shape, action distribution, and frame count.

```bash
PYTHONPATH=among_them .venv/bin/python among_them/scripts/play_local.py \
    --duration 20
```

Expected output: ~450 frames over 20 seconds, observation shape
`(4, 128, 128)`, palette indices within `[0, 15)`. Action distribution
on a fresh game shows a healthy mix of directional movement, A-presses
(task holds), and occasional NOOPs.

## Running with cogames play

`cogames play` does **not** know about Among Them — it only supports
cogsguard-family games. Use `scripts/play_local.py` for Among Them
local runs.

## Submitting to the tournament

```bash
cogames ship \
    -p "class=modulabot.policy.AmongThemPolicy" \
    -f among_them/modulabot \
    -n "$USER-modulabot-py" \
    --season among-them \
    --dry-run          # remove once dry-run is clean
```

The `-f among_them/modulabot` flag bundles the whole package. If we
start pulling in external files (trained weights, a chat-model prompt),
add another `-f`.

### Expected dry-run outcome

The cogames 10-step validation gate checks that the policy emits at
least one non-NOOP action. The pixel pipeline will produce directional
movement (or A-press) within the first few playing frames — task
selection fires on the first non-interstitial tick that has any
assignment evidence (icon visible or radar dot). If the gate runs
entirely inside an interstitial (role-reveal splash) we emit NOOPs by
design, and `--skip-validation` is the appropriate escape hatch per
the guidance in the root `COGAMES.md`.

## Behaviour sketch

**Crewmate** (`policies/crewmate.py`). Per-tick decision priority,
high to low:

1. **Pending hold confirmation.** A task we just held is awaiting
   server-side confirmation of completion. `_check_hold_confirmation`
   runs every tick: icon-disappearance (primary, gated on Phase 6's
   `clear_area_visible` + `maybe_visible` checks) → `task_progress`
   advance (fallback, only for checkout-only holds) → deadline
   timeout (clears `checkout[idx]` so the bot moves on).
2. **Active hold.** While `hold_ticks > 0`, return `actions.A` with
   no movement — moving cancels the hold in the BitWorld sim. Timer
   expiry transitions to "confirming" (above), not to resolved.
3. **Body in view.** Queue a chat line with the sole-suspect colour
   if any, then report (press B) or navigate into report range.
4. **Pick best actionable task.** Tier ladder via
   `base.best_actionable_task`:
   - Tier 1: `active` task (rect-inside + assignment evidence).
     Closest-to-centre wins; icon-visible breaks ties over
     checkout-only.
   - Tier 2: `icon_visible` task. Walk to it.
   - Tier 3: `arrow_visible` task (radar dot matched, or checkout
     latched). Chase the arrow off-screen.
   - Tier 4: nothing → patrol or, if confirmation pending and no
     other candidates, `crew.task.await_confirm` NOOP.
   - In-flight hold/confirmation indices are filtered out of the
     candidate set so the loop doesn't re-select a task it's
     already trying to complete.
   - 48-tick commit hysteresis (`TASK_COMMIT_TICKS`) prevents
     perception-flicker-induced goal flipping. Active-task and
     icon-upgrade escape hatches preserve responsiveness.
5. **Approach.** A\* world-space path to `game_map.tasks[i].cx/cy`
   when localized; greedy fallback otherwise.
   `_maybe_press_a` opportunistically presses A every
   `ACTION_PERIOD = 24` ticks (3-tick window) during travel to pick
   up incidental icon-visible tasks.
6. **Hold start.** When rect-inside + evidence (or icon-visible &
   close), `_begin_hold` snapshots `pre_hold_progress` and sets
   `confirming_via_icon`, then presses A for `TASK_HOLD_TICKS = 84`.
7. **Patrol fallback.** Deterministic 4-quadrant rotation keyed on
   `agent_id`, so mixed-lobby bots don't all walk the same way.

The selection / approach / hold / confirm flow is documented in detail
in `CREWMATE_TASK_FIX_PLAN.md`. The ~32-of-40 not-mine tasks get
pruned out of the candidate set automatically by Phase 6's
icon-miss negative-evidence latch (see
[Crewmate task lifecycle](#crewmate-task-lifecycle) below).

**Imposter** (`policies/imposter.py`):

1. Body in view → self-report if it's our recent kill (within
   `IMPOSTER_SELF_REPORT_RECENT_TICKS` and close to the kill site), else
   flee in the opposite direction.
2. Lone visible non-teammate + kill ready + in kill range → press A.
3. Same but out of range → hunt.
4. Active fake-task timer → hold A at the fake station.
5. Followee visible → tail, roll the fake-task die on pass-by.
6. Otherwise wander on a deterministic patrol.

**Voting** (`policies/voting.py`):

1. First voting frame: pick target (accusation colour if any, else
   skip).
2. Nudge cursor RIGHT every other tick until we hit the target.
3. After `VOTE_LISTEN_TICKS` on target, press A.
4. After commit, idle until voting ends.

## Extending

Every file has one concern. Good entry points for iteration:

| Concern | File |
|---|---|
| Better task selection / re-tiering | `policies/base.py::best_actionable_task` |
| Smarter hold confirmation signals | `policies/crewmate.py::_check_hold_confirmation` |
| Smarter chat (LLM, templates) | `chat.py::format_body_report`, etc. |
| Better evidence model (quantitative scoring) | `evidence.py` |
| Add witness-kill detection | `evidence.py::record_witnessed_kill` + pixel hook |
| Tune any constant | `tuning.py` (constants are docstring-cited to Nim sources where applicable) |
| Pixel-mode perception kernel | `actors.py`, `localize.py`, `voting.py` |
| Per-agent state you need | add a field to an existing sub-record in `state.py` |
| Trace output for an outer-loop harness | `trace.py` (wired; opt in via `trace_dir` / `MODULABOT_TRACE_DIR`) |

The wrapper's `_build_core` hook in `policy.py` lets a subclass supply a
customized `BotCore` without forking the batch entrypoint.

## Crewmate task lifecycle

Reference for "how does the crewmate decide what to do about tasks":
see `CREWMATE_TASK_FIX_PLAN.md` for the full plan + per-phase results,
plus the in-line answer to "how are tasks selected, approached,
executed, and confirmed" in the design-review report referenced from
the plan. Brief:

- **Possible tasks**: 40 stations on the map (`map.json`), 8 assigned
  per player (`tasksPerPlayer` config). The bot starts the round with
  `resolved=False, checkout=False, icon_misses=0` for every task and
  uses three signals to discover which 8 are its:
  - **Strict icon match** — server-rendered icon over the rect, gives
    `TaskInfo.icon_visible`. Direct ground truth for assignment.
  - **Radar-dot match** — for off-screen tasks, a yellow dot at the
    projected screen-edge gives `arrow_visible` and latches
    `bot.tasks.checkout[i] = True` for the round (so a momentary dot
    loss doesn't drop the task).
  - **Negative evidence (Phase 6)** — when the inspection rect is
    fully on-screen with margin AND no strict match AND no fuzzy
    `maybe_matches_sprite` match for `ICON_MISS_THRESHOLD = 24`
    consecutive frames, latch `resolved=True, checkout=False`. This
    is what shrinks the candidate set from 40 to ~8 over the course
    of the round.
- **Selection**: `best_actionable_task` with tiers + commit hysteresis
  (see Behaviour sketch above).
- **Approach**: A\* on the walk mask to the canonical
  `TaskStation.cx/cy`; arrow-only tasks navigate toward the projected
  edge until on-screen, then upgrade to icon-visible.
- **Execution**: `_begin_hold` for `TASK_HOLD_TICKS = 84`, A pressed
  every tick, no movement.
- **Confirmation**: hold timer expiry transitions to "confirming"
  state. Icon-disappearance (Phase 7 primary, Phase 6 gates applied)
  → `_mark_confirmed`. `task_progress` advance (fallback for
  checkout-only holds) → `_mark_confirmed`. Deadline elapsed → drop
  `checkout[idx]` and reselect.

## Known divergence from the Nim modulabot

- **State-observation path is dead code in the tournament.** Cogames
  Among Them only serves pixels; `perception/state_obs.py` is kept only
  so training-harness driven evaluation (via `BitWorldVecEnv`) can still
  use the modular policy layers. Consider deleting if the training path
  doesn't materialize.
- **`TaskState` machine half-wired in pixel mode.** The four-state
  enum (`NOT_DOING / MAYBE / MANDATORY / COMPLETED`) defined in
  `state.py` is fully populated only by the state-obs path; pixel
  mode effectively uses two states (`NOT_DOING` + `COMPLETED` via
  `resolved[]`). Selection logic reads
  `icon_visible / arrow_visible / active / checkout` directly. Filed
  as a TODO in `CREWMATE_TASK_FIX_PLAN.md § TaskState machine
  cleanup`. Doesn't affect correctness, but the state field is
  dead weight in pixel-mode traces.
- **No HUD task-list parsing.** The on-screen task-bar (the right-side
  list of "Empty Garbage / Fix Wires / ..." text) is ground-truth
  assignment with no inference. We don't parse it. Adding it would
  obviate radar-dot inference entirely. Filed as a follow-up.
- **One RNG per agent, not four.** The Nim bot splits RNG streams per
  consumer (fake-task, follow, vote-tie, chat) for parity stability. The
  Python port has one stream per agent because Python scripted mode
  doesn't need deterministic parity across code changes. Easy to split
  if a test harness later demands it.
- **No viewer.** The Nim bot ships a three-panel diagnostic viewer.
  We use the `scripts/debug_overlay.py` static-frame renderer plus
  the JSONL trace writer instead.

<a id="perception-status"></a>
## Perception status

| Capability | Nim modulabot | Python port today | Priority |
|---|---|---|---|
| Interstitial detection (30% black heuristic) | ✅ | ✅ | — |
| Frame unpacking (4-bit → indexed) | ✅ | ✅ | — |
| Palette + sprite loading (aseprite → PNG pipeline) | ✅ | ✅ | — |
| Geometry / camera math | ✅ | ✅ | — |
| Dynamic-pixel ignore mask | ✅ | ✅ | — |
| Sprite matching primitives (`matches_sprite`, `matches_crewmate`, shadowed, actor_color_index) | ✅ | ✅ scalar + vectorised all-anchor matcher + **Nim FFI** | — |
| Actor scans (`scan_crewmates`, `scan_bodies`, `scan_ghosts`) | ✅ | ✅ vectorised; **~2.5 ms** `scan_all` on gameplay frames with Nim FFI (was ~400 ms scalar, ~8.6 ms numpy) | low (recall gap remains) |
| Role HUD detection (`update_role`) | ✅ | ✅ — settles to CREWMATE/IMPOSTER on captured frames | — |
| Radar dot scanning | ✅ | ✅ numpy (already fast) | — |
| Map patch-hash localization | ✅ | ✅ — 100% lock rate on 144 real gameplay frames; **p95 ~0.03 ms (warm) / ~0.9 ms (cold patch search) with Nim FFI** (was ~5 ms cold) | — |
| Task icon scanning at projected positions | ✅ | ✅ Nim FFI | — |
| Task icon-miss negative-evidence pruning (`taskIconClearAreaVisible`, `taskIconMaybeVisibleFor`) | ✅ | ✅ Phase 6 of CREWMATE_TASK_FIX_PLAN.md | — |
| Radar-dot → task assignment matching | ✅ | ✅ Phase 1 of CREWMATE_TASK_FIX_PLAN.md (`projectedRadarDot` ported) | — |
| Server-confirmed task completion (icon-disappearance / progress) | ✅ | ✅ Phase 3 + 7 of CREWMATE_TASK_FIX_PLAN.md | — |
| Voting screen parser (cursor, slots, chat OCR) | ✅ | ✅ — parse half shipped in `voting.py`; **~3 ms empty, ~8.6 ms chat-heavy** with Nim FFI (was ~25 ms) | — |
| ASCII glyph OCR (`best_glyph`, `text_matches`) | ✅ | ✅ Nim FFI — font packed once per process, scalar scan with early-exit | — |
| ASCII phrase search (`find_text`) | ✅ | ✅ numpy `sliding_window_view` (already <2 ms, rarely called) | — |
| A\* pathfinding on walk mask | ✅ | ✅ — `find_path` / `path_distance` / `goal_distance` / `choose_path_step`; **wired into policies** via `navigate_to_world_goal`; ~10 ms typical real-map step | — |
| Motion / momentum steering | ✅ | 8-way diagonal movement + continuous waypoint advancement + anti-stuck jiggle (12-tick threshold, 8-tick jiggle) | medium — no momentum model yet |
| HUD task-list (assignment-list) parsing | ✅ | ❌ not yet | medium — would obsolete radar-dot inference |
| Witness-kill detection (Among Us animation) | ✅ | ❌ not yet | medium — would strengthen voting evidence |

### Crewmate task pipeline (Phases 1-4 + 6-7 of CREWMATE_TASK_FIX_PLAN.md)

Five bugs in the original pixel-pipeline → crewmate flow caused the
bot to navigate to and "complete" tasks assigned to other players:

1. `arrow_visible` was set unconditionally for every off-screen task.
   Now gated on a yellow radar-dot match at the projected screen-edge
   position (Nim `projectedRadarDot` ported to
   `pixel_pipeline._projected_radar_dot`), with a `bot.tasks.checkout`
   latch so momentary dot loss doesn't drop the task.
2. `active` was pure rect-intersection. Now requires
   `active_rect AND (icon_visible OR checkout[i])`. Walking through
   another crewmate's task rect no longer starts an A-hold.
3. Hold completion was a 84-tick local timer with no server check.
   Now a two-stage state machine — hold (A pressed) → confirming
   (A released, watching for icon disappearance or `task_progress`
   advance) → resolved or timeout. Timeout un-latches `checkout` so
   the bot doesn't pathologically re-hold the same un-confirmable
   task.
4. **Negative-evidence pruning** (Phase 6). The bot now observes the
   *absence* of an icon to learn which tasks aren't assigned. When
   the inspection rect is fully on-screen with margin AND no strict
   match AND no fuzzy `maybe_matches_sprite` match for
   `ICON_MISS_THRESHOLD = 24` consecutive frames, the task is
   latched `resolved=True, checkout=False` for the round. With
   ~32 of 40 tasks not-mine, this prunes the candidate set as the
   bot moves around the map.
5. **Confirmation is icon-first** (Phase 7). `task_progress` is a
   team-wide bar that advances on any player's task, creating a
   ~22% per-hold false-positive rate from sibling completions
   during our window. Icon-disappearance is now primary;
   `task_progress` only fires for checkout-only holds (no icon
   ever visible).

Plan file with full design details + comparison traces:
[`CREWMATE_TASK_FIX_PLAN.md`](CREWMATE_TASK_FIX_PLAN.md). Per-phase
trace artefacts in the `phase{0,1,2,3,7}_trace/` directories.

### Nim FFI (`modulabot/nim_perception/`)

The hot perception kernels are native Nim loaded via `ctypes`. The
kernel sources live in `among_them/common/perception_kernels/` (shared
with guided_bot — see [`among_them/common/README.md`](../common/README.md));
`modulabot/nim_perception/lib.nim` is the modulabot-specific FFI
surface (`mb_*` exports + ABI version stamp), and `build.py` compiles
the dylib with `--path:` set to the shared kernel directory. The
library rebuilds on-demand (source-hash gated) on first policy
import. See `modulabot/PERCEPTION_PERF_PLAN.md` for the design +
per-phase perf numbers. `MODULABOT_DISABLE_NATIVE=1` forces the
pure-Python fallback — every FFI kernel has a parity-pinned numpy
implementation behind it (`tests/test_nim_perception.py` has parity
tests over the 275-frame fixture + synthetic OCR inputs).

**Bench harness**: `scripts/bench_perception.py` reports p50 / p95 /
p99 / max / mean for each kernel + end-to-end `BotCore.step`. Run
before and after any perception change to track regressions.

**Snapshot tests** (`modulabot/tests/test_perception_snapshots.py`) pin
perception output against a fixture of 275 real captured frames. Run
`python -m unittest modulabot/tests/test_perception_snapshots.py` to
catch regressions.

**Visual debug overlay** at `scripts/debug_overlay.py` renders raw frame
+ perception overlay side-by-side:

```bash
PYTHONPATH=. python scripts/debug_overlay.py /tmp/mb_frames.npy --frame 150 --save /tmp/overlay.png
```

**Known gaps as of 2026-05-01:**

- Crewmate recall is lower than Nim's — walking-pose crewmates are
  often missed. The Nim bot uses the same single player sprite, so
  the fix is probably in the stable/body-pixel thresholds rather
  than the sprite.
- `update_role` sometimes mis-fires to IMPOSTER on crewmate frames
  because the shaded kill-button match is loose. Tune
  ``KILL_ICON_MAX_MISSES`` or check for the IMPS reveal as
  ground-truth before trusting pixel inference.
- HUD task-list parsing not done (see Perception status table).
  Adding it would obsolete the radar-dot inference path entirely.

## Tracing

Modulabot ships an opt-in structured JSONL trace writer for outer-loop
self-improvement harnesses. Every policy branch calls
`bot.fired("<branch_id>", ...)` (e.g. `crew.task.continue_hold`,
`crew.task.start_hold`, `crew.task.await_confirm`,
`imp.kill.in_range`, `vote.press_a`), so a harness can follow exactly
which decision fired on every tick.

Disabled by default. Enable via environment variables:

```bash
export MODULABOT_TRACE_DIR=/tmp/modulabot_runs
export MODULABOT_TRACE_LEVEL=decisions          # or "events"
export MODULABOT_TRACE_META="experiment_id=baseline,git_sha=abc1234"
```

…or via constructor kwargs when you instantiate the policy yourself:

```python
AmongThemPolicy(
    policy_env_info,
    trace_dir="/tmp/modulabot_runs",
    trace_level="decisions",
    trace_meta={"experiment_id": "baseline"},
)
```

Output layout (one session per process):

```
<trace_dir>/modulabot/<iso8601-pid>/
    manifest.json           # counters, settings, per-agent final state
    agent_<id>/
        events.jsonl        # sparse, edge-triggered (~10–100 lines/game)
        decisions.jsonl     # one line per branch-id transition
```

**Events** fired by v1: `session_start`, `role_known`, `role_changed`,
`self_color_known`, `phase_change`, `kill_cooldown_ready`,
`kill_cooldown_used`, `kill_executed`, `body_seen_first`, `vote_cast`,
`chat_sent`.

**Decisions** carry `branch_id`, `intent`, `from`,
`duration_ticks_in_prev_branch`, `action`, `role`, `phase`, and (when
set) `goal`. See `modulabot/trace.py` for the schema.

**Phase comparison traces (in-tree).** Each phase of the crewmate
task fix archived a 20-30 second decisions trace under
`phase{0,1,2,3,7}_trace/`. Useful for regression-checking behaviour
changes; see `CREWMATE_TASK_FIX_PLAN.md` for what each shows.

**Scope vs. the Nim trace.** The Python v1 ships Phase-1 equivalent:
session-level manifest only (no per-round directories), no
`snapshots.jsonl`, no frames-dump replay. The outer-loop harness can
segment by `phase_change` events when round boundaries matter.
See `~/coding/bitworld/among_them/players/modulabot/TRACING.md` for
the fuller Nim design.

**Non-perturbation.** The writer never mutates `Bot`. Running with vs.
without a trace writer produces identical action sequences —
`test_trace.py::NonPerturbationTests` pins this invariant for both the
crewmate-task and imposter-kill paths. I/O errors disable the writer
for the rest of the session rather than taking the bot down.

## Future work

Open items, roughly priority-ordered:

- **TaskState machine cleanup.** Half-wired in pixel mode; see
  `CREWMATE_TASK_FIX_PLAN.md § TaskState machine cleanup` for design
  and recommendations. Estimated 1-2 hours.
- **HUD task-list parsing.** Ground-truth assignment with no
  inference. Would simplify `pixel_pipeline._populate_tasks_from_camera`
  by replacing the radar-dot + checkout latch + icon-miss pruning
  cascade with a direct read of the assignment list. New OCR work
  on a fixed-position HUD region.
- **Witness-kill detection.** Pixel-mode could detect the kill
  animation and stamp `Evidence.witnessed_kill_ticks`. Would make
  the voting policy meaningfully stronger for crewmates.
- **LLM chat.** The `chat.py` templates are intentionally tiny.
  Wire in an optional LLM provider (Anthropic / OpenAI / Bedrock)
  mirroring the `BitWorldAmongThemCyborgPolicy` pattern. Keep it
  behind a constructor flag; the tournament worker won't have
  outbound network access by default.
- **State/pixel hybrid.** If a season ships state observations that
  omit some field (or caps them low), the pixel path could fill in
  the gap instead of falling back entirely.

## Submission log

Append a row here on every `cogames upload` / `ship` per the repo
AGENTS.md rule. Format: date, policy name, season, dry-run result,
leaderboard score.

| Date | Policy name | Season | Dry-run | Leaderboard score |
|---|---|---|---|---|
| _none yet_ | | | | |
