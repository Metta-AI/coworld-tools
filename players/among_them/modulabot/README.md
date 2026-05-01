# modulabot (Python port)

A modular scripted agent for cogames Among Them. Python port of the Nim
[modulabot][nim-design] architecture: one concern per file, state decomposed
into sub-records, pluggable perception and policy layers.

[nim-design]: file:///Users/jamesboggs/coding/bitworld/among_them/players/modulabot/DESIGN.md

**v0 status:** scaffolding + cogames wrapper complete and verified against
a live local Among Them server. Perception layer is a placeholder — the
bot drives via the screen-space fallback, which is not competitive. See
**Perception status** below.

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
   we are in the world to do A* or task targeting.
2. **Sprite recognition** — find the player, other crewmates, bodies,
   task icons, radar dots, voting cursor.
3. **Task pixel logic** — recognize which task we're on top of and when
   to press A.
4. **Voting-screen OCR** — parse the cursor position and chat text.

This is essentially the entire Nim modulabot perception layer. Porting it
faithfully to Python is the next real piece of work (see
[Porting status](#perception-status) below).

## Why a port

The Nim modulabot is a ~4 kLOC visual client that does pixel-perfect
localization, A* pathfinding, OCR, and a long list of perception gymnastics
the cogames BitWorld shim makes unnecessary — cogames hands us structured
state observations when available (player positions, body positions, task
flags) and still-useful 128x128 indexed pixel frames as a fallback. The
valuable thing to carry over is the *architecture*:

- **Modular layout** — one concern per file; nothing resembles the
  4700-line monolith the port started from.
- **Sub-record state** — `Perception`, `Motion`, `Tasks`, `Goal`,
  `Identity`, `Evidence`, `ImposterState`, `VotingState`, `ChatState`,
  `Diag`. Each module owns the sub-records it mutates.
- **Per-frame pipeline** — clear perception → update evidence/motion →
  dispatch by phase → policy writes goal + action.
- **Branch IDs** — every policy branch calls `bot.fired(branch_id)` before
  returning, so a trace writer can attribute decisions later (wired in
  but not yet emitting JSONL; see Future work below).

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
├── sprite_match.py          # matches_sprite / matches_crewmate / shadowed
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
├── perception/
│   ├── __init__.py
│   ├── common.py            # dispatcher: state_obs vs pixel pipeline fallback
│   ├── pixel_pipeline.py    # main pixel path: scan_all + localize + voting parse + adapter
│   ├── state_obs.py         # structured state → Perception (legacy path, kept for tests)
│   └── pixel_obs.py         # minimal pixel fallback (used when no reference_data)
├── policies/
│   ├── __init__.py
│   ├── base.py              # Policy ABC + shared movement helpers
│   ├── crewmate.py          # CrewmatePolicy: tasks, report bodies
│   ├── imposter.py          # ImposterPolicy: fake tasks, kill, flee
│   └── voting.py            # VotingPolicy: cursor + commit
└── tests/
    ├── test_smoke.py        # pipeline + behaviour smoke tests
    ├── test_perception.py   # data / geometry / frame / sprite_match / actors units
    ├── test_perception_snapshots.py  # real captured-frame regression snapshots
    ├── test_localize.py     # score_camera + patch index + Localizer fixture tests
    ├── test_ascii.py        # pixel-font loader + OCR primitives
    ├── test_voting.py       # voting parse: grid / slots / cursor / chat OCR
    ├── test_path.py         # A* passable/heuristic/find_path + real-map perf
    ├── test_navigation.py   # goal-setting + A* wiring into policies
    ├── test_pixel_pipeline.py  # end-to-end: BotCore + reference_data + fixture frames
    ├── test_motion.py       # world-coord velocity + teleport guard + deadband
    ├── test_trace.py        # trace writer + non-perturbation invariants
    └── fixtures_frames.npy  # 275 frames of real gameplay (12s @ 22Hz)
```

## Running the smoke tests

```bash
cd among_them
PYTHONPATH=. python -m unittest discover -s modulabot/tests -v
```

Expected: 211 tests, 0 failures with the Nim FFI loaded; 201 with
``MODULABOT_DISABLE_NATIVE=1`` (5 parity tests skip since they
require the native library).

## Running locally against the real server

We ship a `scripts/play_local.py` harness that:

1. Starts the pre-built Nim `among_them` server from
   `~/coding/bitworld/out/among_them`.
2. Fills the lobby with headless `nottoodumb` bots from the same
   directory.
3. Connects our policy as one player over the real WebSocket protocol,
   running it through the actual `mettagrid.runner.bitworld_runner` code
   path the tournament uses.
4. Logs the observation shape, action distribution, and frame count.

```bash
cd among_them
PYTHONPATH=. python scripts/play_local.py --duration 15
```

Expected output: ~300–350 frames received over 15 seconds, observation
shape `(4, 128, 128)`, palette indices within `[0, 15)`. Action
distribution will be a mix of NOOP and patrol directions until pixel
perception is implemented.

## Running with cogames play

`cogames play` does **not** know about Among Them — it only supports
cogsguard-family games. Use `scripts/play_local.py` for Among Them
local runs.

## Submitting to the tournament

```bash
cd among_them
cogames ship \
    -p "class=modulabot.policy.AmongThemPolicy" \
    -f modulabot \
    -n "$USER-modulabot-py" \
    --season among-them \
    --dry-run          # remove once dry-run is clean
```

The `-f modulabot` flag bundles the whole package. If we start pulling in
external files (trained weights, a chat-model prompt), add another `-f`.

### Expected dry-run outcome

The cogames 10-step validation gate checks that the policy emits at least
one non-NOOP action. Modulabot *will* emit directional actions on the very
first state-observation frame (the patrol fallback kicks in immediately),
so we should pass the gate without `--skip-validation`. If the first frame
is an interstitial (role-reveal splash) and the gate runs entirely inside
it, fall back to `--skip-validation` per the guidance in the root
`COGAMES.md`.

## Behaviour sketch

**Crewmate** (`policies/crewmate.py`):

1. Hold A if mid-task. Never mix movement into a task hold.
2. Body in view → queue a chat line with the sole-suspect colour if any,
   then report or navigate into report range.
3. Task with icon visible → walk to it. Press A on the rect.
4. Task with arrow visible → chase the arrow offscreen.
5. Otherwise patrol in a deterministic quadrant rotation.

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

1. First voting frame: pick target (accusation colour if any, else skip).
2. Nudge cursor RIGHT every other tick until we hit the target.
3. After `VOTE_LISTEN_TICKS` on target, press A.
4. After commit, idle until voting ends.

## Extending

Every file has one concern. Good entry points for iteration:

| Concern | File |
|---|---|
| Better task selection / eight-tier re-tiering | `policies/base.py::best_actionable_task` |
| Smarter chat (LLM, templates) | `chat.py::format_body_report`, etc. |
| Better evidence model (quantitative scoring) | `evidence.py` |
| Add witness-kill detection | `evidence.py::record_witnessed_kill` + pixel hook |
| Tune any constant | `tuning.py` |
| Pixel-mode localization | `perception/pixel_obs.py` (port more of the Nim layer) |
| Per-agent state you need | add a field to an existing sub-record in `state.py` |
| Trace output for an outer-loop harness | `trace.py` (wired; opt in via `trace_dir` / `MODULABOT_TRACE_DIR`) |

The wrapper's `_build_core` hook in `policy.py` lets a subclass supply a
customized `BotCore` without forking the batch entrypoint.

## Known divergence from the Nim modulabot

- **State-observation path is dead code in the tournament.** Cogames
  Among Them only serves pixels; `perception/state_obs.py` is kept only
  so training-harness driven evaluation (via `BitWorldVecEnv`) can still
  use the modular policy layers. Consider deleting if the training path
  doesn't materialize.
- **Minimal pixel perception.** Currently only interstitial detection,
  radar dot centroid, and kill-icon heuristic. No localization, no
  sprite matching, no task recognition. This is the work to do (see
  [Perception status](#perception-status)).
- **No A*.** Will be needed once localization lands.
- **One RNG per agent, not four.** The Nim bot splits RNG streams per
  consumer (fake-task, follow, vote-tie, chat) for parity stability. The
  Python port has one stream per agent because Python scripted mode
  doesn't need deterministic parity across code changes. Easy to split if
  a test harness later demands it.
- **No viewer.** The Nim bot ships a three-panel diagnostic viewer. For
  now we emit debug lines via the standard `logging` module.

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
| Voting screen parser (cursor, slots, chat OCR) | ✅ | ✅ — parse half shipped in `voting.py`; **~3 ms empty, ~8.6 ms chat-heavy** with Nim FFI (was ~25 ms) | — |
| ASCII glyph OCR (`best_glyph`, `text_matches`) | ✅ | ✅ Nim FFI — font packed once per process, scalar scan with early-exit | — |
| ASCII phrase search (`find_text`) | ✅ | ✅ numpy `sliding_window_view` (already <2 ms, rarely called) | — |
| A* pathfinding on walk mask | ✅ | ✅ — `find_path` / `path_distance` / `goal_distance` / `choose_path_step`; **wired into policies** via `navigate_to_world_goal`; ~10 ms typical real-map step | — |
| Motion / momentum steering | ✅ | minimal anti-stuck jiggle only | low |

### Nim FFI (`modulabot/nim_perception/`)

The hot perception kernels are native Nim loaded via `ctypes`. Source
lives under `modulabot/nim_perception/src/`; the library rebuilds
on-demand (source-hash gated) on first policy import. See
`modulabot/PERCEPTION_PERF_PLAN.md` for the design + per-phase perf
numbers. `MODULABOT_DISABLE_NATIVE=1` forces the pure-Python
fallback — every FFI kernel has a parity-pinned numpy implementation
behind it (`tests/test_nim_perception.py` has 15 parity tests over
the 275-frame fixture + synthetic OCR inputs).

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

**Known gaps as of 2026-04-30:**

- Crewmate recall is lower than Nim's — walking-pose crewmates are
  often missed. The Nim bot uses a single player sprite too, so the
  fix is probably in the stable/body-pixel thresholds rather than the
  sprite.
- Perception costs ~2.5 ms per in-game frame with Nim-backed sprite
  matching (down from ~8.6 ms numpy / ~400 ms scalar). Cold localize
  ~0.9 ms (down from 4.7 ms) via the bulk Nim patch-vote kernel.
  Voting-chat OCR ~8.6 ms (down from 25 ms) via the Nim best_glyph /
  text_matches kernels. All Nim paths have parity-pinned numpy
  fallbacks (`tests/test_nim_perception.py`); `MODULABOT_DISABLE_NATIVE=1`
  is a one-switch rollback.
- `update_role` sometimes mis-fires to IMPOSTER on crewmate frames
  because the shaded kill-button match is loose. Tune
  ``KILL_ICON_MAX_MISSES`` or check for the IMPS reveal as
  ground-truth before trusting pixel inference.

## Running locally against the real server

## Tracing

Modulabot ships an opt-in structured JSONL trace writer for outer-loop
self-improvement harnesses. Every policy branch calls
`bot.fired("<branch_id>", ...)` (e.g. `crew.task.continue_hold`,
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

- **LLM chat.** The `chat.py` templates are intentionally tiny. Wire in
  an optional LLM provider (Anthropic / OpenAI / Bedrock) mirroring the
  `BitWorldAmongThemCyborgPolicy` pattern. Keep it behind a constructor
  flag; the tournament worker won't have outbound network access by
  default.
- **Witness-kill detection.** Pixel-mode could detect the Among Us kill
  animation and stamp `Evidence.witnessed_kill_ticks`. This would make
  the voting policy meaningfully stronger for crewmates.
- **State/pixel hybrid.** If a season ships state observations that omit
  some field (or caps them low), the pixel path could fill in the gap
  instead of falling back entirely.
