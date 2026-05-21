# among-them-coborg — Implementation Plan

Status: P0 scaffold landed; P1 (perception port) is next.
Created: 2026-05-13.
Owner: James (jmsboggs@gmail.com).
Author of this plan: prior Claude Code session; record carried over for a fresh
session to pick up cold.

> **Current status (2026-05-19):** P0 deliverables in §6 are largely landed.
> The idle/noop runtime, action resolver, stderr trace sinks, `bitscreen_v1`
> WebSocket bridge, Dockerfile, `build.sh`, and `scripts/play_local.sh` are
> all in place; `pytest players/among_them/coborg/tests` is green
> (17 tests including an in-process Coworld bridge smoke). R1 toolchain
> flake (§10) was root-caused and resolved 2026-05-13. §11 items 1–2 are
> done; pick up from item 3 (capture parity fixtures) when starting P1.
> See [`README.md`](./README.md) for the runnable surface today and
> [`DESIGN.md`](./DESIGN.md) for the durable architecture notes.

---

## 1. Mission

Build a new BitWorld Among Them agent named **`among-them-coborg`** that:

1. Lives in this repo at `players/among_them/coborg/`
   — a **sibling** of the existing scripted `among_them/` package, not
   nested inside it. Nesting was tried briefly during P0 scaffolding and
   abandoned because importing any submodule transitively loaded
   `among_them/__init__.py`, which eagerly imports `mettagrid` (heavy
   Bazel + Nim build). Sibling placement keeps this parallel experiment
   decoupled from the production scripted policy.
2. Is the **first concrete in-repo user** of the `players.player_sdk`
   Cyborg two-loop runtime (`AgentRuntime` + modes + strategy runner). The
   existing `players/among_them/scripted/__init__.py` is a
   `mettagrid.policy.policy.AgentPolicy` screen-space scripted policy, NOT a
   coborg runtime client.
3. Runs **completely in Python** — no Nim toolchain in the runtime image, no
   `.so` produced from Nim. The Nim perception modules in
   `users/james/personal_cogs/among_them/{common,guided_bot}/perception*/`
   (in this repo) must be **ported to Python** with high efficiency.
4. Perception is **pixel-first**: parse the BitWorld 128×128 4-bit packed frame,
   not just the structured state vector. Hybrid (using the state vector for
   things that are lossy from pixels, e.g. task progress) is acceptable and
   documented in `DESIGN.md`.
5. Logs/traces go to **stderr** so Coworld hosted runners capture them. Stdout
   stays reserved for protocol traffic.
6. Is exercised end-to-end locally with `uv run coworld play` against the
   downloaded Among Them manifest (one Docker image fills every player slot).
7. Ships from the players repo — Dockerfile, `policy_player.py`, and submission
   scripts all live inside the new package directory.
8. Scope-capped at **P4 Imposter** (deterministic role-aware agent). LLM
   strategy is explicitly deferred to a follow-on plan.
9. Is a **parallel experiment**. The existing `guided_bot` in
   `users/james/personal_cogs/among_them/guided_bot/` (in this repo)
   remains the production Daily-league submission throughout.

---

## 2. Locked-in decisions

From the conversation that produced this plan:

| # | Decision | Source |
|---|---|---|
| D1 | Agent name is `among-them-coborg` (the coplayer manifest `name` field, also the Docker tag `coborg-among-them:dev`). Python package is `players.among_them.coborg`. The leaf directory `players/among_them/coborg/` is a sibling of the scripted `among_them/` package (briefly nested during P0, then moved out because importing any submodule transitively loaded the parent's eager `mettagrid` import — a heavy coupling we did not want on the noop bot path). | James, 2026-05-13 (name); 2026-05-21 (canonicalized to `among-them-coborg`). |
| D2 | Perception is pixel-first, ported from the Nim modules. | James, 2026-05-13. |
| D3 | All logs/traces go to stderr. | James, 2026-05-13. |
| D4 | Local execution uses Coworld-first CLI flow (no Nim server scripts). | James, 2026-05-13. |
| D5 | Shipping artifacts live inside the players repo, not in `personal_cogs`. | James, 2026-05-13. |
| D6 | Scope ends at the imposter-capable deterministic agent (P4); LLM is later. | James, 2026-05-13. |
| D7 | Parallel experiment. Do not modify `guided_bot` or its submission flow. | James, 2026-05-13. |
| D8 | Numpy-first perception with numba as a measured fallback. | Drafted, not yet confirmed by James. |
| D9 | Allow sourcing lossy belief fields (e.g. `task_progress`) from the structured state vector even though perception is pixel-first. | Drafted, not yet confirmed by James. |

D8 and D9 are the only items in the plan not yet explicitly approved. The new
session should proceed under them unless James says otherwise.

---

## 3. Source pointers (read these before writing code)

### 3.0 Repo roles at a glance

- **this repo** (checked out at `~/coding/players_checkouts/players_main/`
  on James's machine; remote `Metta-AI/players`). Hosts the Coworld
  Player SDK (`players/player_sdk/`), every Python agent policy including
  this new agent (`players/among_them/coborg/`), and the in-repo home of
  the production `guided_bot` and its supporting Nim perception kernels
  under `users/james/personal_cogs/among_them/`.
- **`~/coding/bitworld/`** — the **BitWorld game implementation** itself
  (Nim). `~/coding/bitworld/among_them/` is the Among Them game: server,
  Skeld map, sprite atlas, manifest, native player bots in `players/` and
  `bot-policies/`, replay viewer. Source of truth for game constants
  (`coworld_manifest.json`, `config.json`).
- **`users/james/personal_cogs/among_them/`** (in this repo) — the
  **`guided_bot` production Daily-league submission**. This is the
  hybrid Python+Nim bot whose perception stack and policy bridge we are
  porting to Python + coborg. Includes `common/perception_kernels/`
  (shared Nim kernels) and `guided_bot/perception/` (bot-specific Nim
  perception). Was previously a sibling repo at `~/coding/personal_cogs/`
  before being absorbed into this monorepo; treat the in-repo copy as the
  source of truth.
- **`~/coding/metta/`** — Metta-AI/metta. Hosts the **Coworld tournament
  runner** under `packages/coworld/`, including the `coworld` CLI we use
  for local play and the WebSocket protocol the agent must speak.

### 3.1 Coworld Player SDK — the runtime we're using

- Package: `players.player_sdk`
- Source dir: `players/player_sdk/` (this repo)
- Key files:
  - `__init__.py` — public re-exports (read first; this is the API surface).
  - `runtime.py` — `AgentRuntime`, `Reflex`, `ReflexRule`, `RuntimeContext`.
  - `modes.py` — `Mode`, `ModeRegistry`, `DirectiveValidationError`.
  - `strategy.py` — `Strategy`, `AsyncStrategy`, `StrategyRunner` and the
    concrete `Manual/Synchronous/Threaded/AsyncStrategyRunner` variants.
  - `types.py` — `ModeParams`, `EmptyModeParams`, `ModeDirective`,
    `SharedMemory`, `SharedMemoryView`, `ActionIntent`, `ActionCommand`,
    `StrategyResult`, `ModeDecision`, `BeliefSnapshot`.
  - `trace.py` — `TraceEvent`, `TraceSink`, `MetricsSink`, `MetricSample`,
    and concrete `Null/List/Logging` trace+metrics sinks plus
    `WandbMetricsSink` (metrics-only; no `WandbTraceSink`).
  - `buffers.py` — `OverwriteBuffer` (newest-wins).
  - `coworld_json_bridge.py` — JSON `coworld.player.v1` adapter used by
    cogsguard-family players. **Not used by this agent** — Among Them
    speaks the binary `bitscreen_v1` wire protocol; see `coworld/README.md`.
- Docs:
  - `docs/metta_cogames_framework/README.md` — full architecture reference
    (read sections "Inner Loop Contract", "Mode Completion And Stalling",
    "Action Layer Contract", "LLM Boundary", "Design Invariants",
    "Anti-Patterns", "Validation Strategy").
  - `docs/metta_cogames_framework/PYTHON_FRAMEWORK.md` — short usage guide.
  - `docs/metta_cogames_framework/examples/toy_grid_agent.py` — the only
    runnable example today. Mirror its assembly pattern.

### 3.2 Existing Among Them prior art (read for state shapes and parsers)

In this repo:

- `players/among_them/scripted/__init__.py` —
  Softmax's `BitWorldAmongThemScoutPolicy` / `BitWorldAmongThemCyborgPolicy`,
  a screen-space scripted policy. **Not a coborg client.** Useful reference
  for: structured state-vector layout (`STATE_*`, `HEADER_*`, `PLAYER_*`,
  `TASK_*` constants) and BitWorld action constants. It is a **sibling**
  package of `coborg/` under `players/among_them/`, not a parent. Its
  mettagrid `AgentPolicy` plumbing is not relevant to this agent, which
  ships as a Docker image and is driven exclusively by the Coworld runner
  over the `bitscreen_v1` WebSocket.

In `~/coding/bitworld/among_them/` (game implementation, Nim):

- `coworld_manifest.json`, `config.json` — **source of truth for game
  constants** (player count, imposter count, tasks per player, kill
  range, vote timer, etc.). Inspect these at P0; if numbers drift from
  what's in §3.4 below, the manifest wins.
- `among_them.nim`, `server.nim`, `sim.nim` — game server / simulation.
  Skim only as needed to understand observation framing.
- `players/` — native player bots (Nim, compiled to `.dylib` and wrapped
  in Python via ctypes). `evidencebot_v2` is the default tournament
  reference; `nottoodumb` is a minimal smoke-test bot.
- `bot-policies/sidecar/` — Python-only Unix-socket sidecar bridge
  (Nim bot ↔ LLM) — reference for the LLM-bounded pattern, not used by
  this agent.

In `users/james/personal_cogs/among_them/` (the guided_bot we're porting
from; in this repo):

- `README.md` — current Coworld-only workspace boundary notes for the
  guided_bot. Does **not** carry the game constants (those live in the
  bitworld manifest above).
- `guided_bot/README.md` and `guided_bot/DESIGN.md` — the current hybrid
  Python+Nim production bot. Read DESIGN.md for the mode list, reflex list,
  belief structure, and trace schema we'll mirror.
- `guided_bot/coworld/policy_player.py` — the existing `bitscreen_v1`
  binary protocol bridge (Python; talks WebSocket to the Coworld runner).
  This is the closest analog to what
  `players/among_them/coborg/coworld/policy_player.py` must do, minus the
  Nim FFI glue.
- `guided_bot/perception.nim` and `guided_bot/perception/*.nim` — the
  bot-specific perception modules to port (see §5).
- `common/perception_kernels/*.nim` — the shared perception kernels
  (sprite_match, actors, localize, ocr) to port (see §5).
- `guided_bot/perception/baked/` — pre-baked sprite atlas data
  (`palette.bin`, `sprites.bin`, `map_pixels.bin`, `walk_mask.bin`,
  `wall_mask.bin`, `font.bin`, `map.json`, `manifest.json`,
  `nav_graph.json`, `nav_paths.bin`). Re-bakeable via
  `guided_bot/tools/bake_assets.{nim,sh}` from the upstream bitworld
  checkout; the in-repo result is checked in.
- `guided_bot/tools/` — offline developer utilities (`bake_assets`,
  `bake_nav.py`, `frame_viewer.py`, `frame_to_text.py`,
  `waypoint_editor.py`). **No frame-capture utility exists today**;
  P1 will either add one (instrumenting `guided_bot` to dump
  per-tick packed frames + percept sidecars) or replay recorded
  Coworld sessions. See §5.4 and §11 item 3.

### 3.3 Coworld toolchain (how we run it locally)

- Repo: `~/coding/metta` (`Metta-AI/metta`). Already cloned;
  `git pull` runs cleanly.
- CLI source: `~/coding/metta/packages/coworld/src/coworld/cli.py`. Key
  commands we care about (typer-based, all under `uv run coworld`):
  - `download <coworld_ref>` (-o `./coworld`): pulls the manifest + assets.
  - `play <manifest_uri> [player_images ...]` with `--variant default`,
    `--timeout-seconds 120`, `--run "<argv>"`, `--no-open-browser` (we'll
    want `--no-open-browser` in dev).
  - `run-episode` — headless variant of `play`.
  - `replay` — replays a saved replay artifact through the runner.
  - `upload-policy`, `submit`, `images`, `list`, `show` — not in scope
    for P0–P4.
- Play function source: `~/coding/metta/packages/coworld/src/coworld/play.py`
  (`play_coworld`).
- Runner: `~/coding/metta/packages/coworld/src/coworld/runner/runner.py` —
  `PlayerLaunchSpec`, `RunnableLaunchSpec`, `_wait_for_health`,
  `_wait_for_player_exit`. Read this before writing the `policy_player.py`
  so the protocol shape is exactly right.

### 3.4 Game constants reference

Approximate defaults to seed the design — the downloaded
`coworld_manifest.json` and `~/coding/bitworld/among_them/config.json`
are the source of truth and override anything below:

- Screen: 128×128, 4-bit indexed palette (PICO-8).
- Players: 8 (2 imposters by default; `imposterCount: 2` in the
  bitworld manifest).
- Tasks per player: 8.
- Vote timer: 600 ticks.
- Imposter kill cooldown: 1200 ticks.
- Action space: 27 discrete actions (directional + A/B combinations).

If the hosted Coworld variant differs from these defaults, the manifest
downloaded by `coworld download among_them -o ./coworld` is the source of
truth.

---

## 4. Project layout (target end-state at P4)

Rooted at
`players/among_them/coborg/`:

```
coborg/
  PLAN.md                           # this file
  README.md                         # what/why/status, written in P0
  DESIGN.md                         # architecture, decisions, tradeoffs, written in P0
  __init__.py                       # public build_runtime entry
  types.py                          # Observation, Percept, Belief, ActionState, Intent, Command
  belief.py                         # update_belief, evidence ledger
  perception/
    __init__.py
    frame.py                        # 4-bpp unpack, pixel access, ignore mask (port of frame.nim)
    geometry.py                     # coord transforms (port of geometry.nim)
    sprite_match.py                 # all-anchors match kernel (hot path; numpy + optional numba)
    actors.py                       # actor extraction (port of actors.nim shared + bot)
    interstitial.py                 # black-screen scene detector (port of interstitial.nim)
    ignore.py                       # ignore-mask construction (port of ignore.nim)
    localize.py                     # camera fit / map localization (port of localize.nim shared + bot)
    tasks.py                        # task icon / target inference (port of tasks.nim)
    ocr.py                          # screen text OCR (port of ocr.nim shared + bot)
    voting.py                       # meeting & voting screen parser (port of voting.nim)
    data/
      __init__.py
      sprite_atlas.npz              # baked sprite atlas (output of generate_baked.py)
      palette.py                    # PICO-8 palette + tint constants
      sprite_index.json             # sprite-name -> (atlas offset, w, h, anchor)
      generate_baked.py             # one-shot: Nim baked/ -> numpy .npz (checked-in result)
    parity/
      capture_fixtures.py           # capture frames + Nim percepts side-by-side
      run_parity.py                 # diff Python percepts vs Nim percepts on fixture set
      fixtures/                     # checked-in small fixture set with golden percepts
  modes/
    __init__.py
    idle.py
    navigate_to.py
    complete_task.py
    meeting.py
    speak.py
    vote.py
    report_body.py
    kill_target.py
    loiter.py
  action.py                         # intent -> BitWorld action index / chat packet
  reflexes.py                       # phase-change, body-sighted, kill-cooldown-ready
  strategy/
    __init__.py
    rule_based.py                   # deterministic strategy
    snapshot.py                     # belief -> structured context (reserved for LLM later)
  trace.py                          # stderr trace + metrics sink setup
  coworld/
    Dockerfile
    policy_player.py                # bitscreen_v1 binary WebSocket bridge
    entrypoint.sh
    README.md
  scripts/
    play_local.sh                   # convenience wrapper around `coworld play`
    capture_fixtures.sh             # capture parity fixtures via guided_bot
  tests/
    __init__.py
    fixtures/                       # tiny in-test fixtures (large ones live under perception/parity/fixtures/)
    test_frame.py
    test_sprite_match.py            # parity + perf
    test_actors.py
    test_tasks.py
    test_voting.py
    test_ocr.py
    test_localize.py
    test_perception_parity.py       # whole-pipeline parity vs Nim
    test_belief.py
    test_modes_*.py
    test_strategy_rule_based.py
    test_action.py
    test_reflexes.py
    test_coworld_player_smoke.py
```

---

## 5. Perception port — the cost center

### 5.1 Why this matters

The Nim perception is ~3,500 lines:

```
common/perception_kernels/  ~960 lines  (4 files: actors, localize, ocr, sprite_match)
guided_bot/perception/      ~2,500 lines (10 files: actors, data, frame, geometry,
                                          ignore, interstitial, localize, ocr, tasks,
                                          voting)
guided_bot/perception/baked/  binary sprite atlas
```

This is the bulk of the implementation work. The agent cannot perceive
gameplay without it, so it gates everything downstream. The plan invests an
entire phase (P1) in landing it cleanly with parity tests against Nim.

### 5.2 Per-module porting strategy

| Layer | Nim lines | Python approach | Why |
|---|---|---|---|
| `frame.py` (bit unpack, pixel access, ignore mask) | ~105 | Pure numpy | Trivially vectorizable; `np.bitwise_and` + `np.right_shift`. |
| `sprite_atlas` baked data | (binary) | One-shot `generate_baked.py` Nim→`.npz` | Checked-in result. Re-runnable when atlas changes. |
| `geometry.py` | ~265 | Pure numpy | Coordinate math. |
| `interstitial.py` | ~80 | Pure numpy (`np.count_nonzero`) | Black-pixel counting. |
| `ignore.py` | ~130 | Pure numpy | Boolean masks. |
| **`sprite_match.py`** (hot path) | ~233 | **Numpy first; numba fallback if budget missed** | See §5.3. |
| `actors.py` (shared + bot) | ~850 | Numpy + dict bookkeeping; calls into sprite_match | Per-tick. |
| `tasks.py` | ~220 | Numpy template-match (12×12 task icon) | One icon template. |
| `localize.py` (shared + bot) | ~1,035 | Numpy + small numba helper for patch-hash if measured slow | Camera fit. |
| `ocr.py` (shared + bot) | ~570 | Numpy per-glyph template match | Bounded glyph set. |
| `voting.py` | ~500 | Numpy + glyph match | Meeting/vote screen parser. |

### 5.3 Sprite-match (the hot kernel) plan

The Nim entrypoint `mb_match_actor_sprite_all` (in
`common/perception_kernels/sprite_match.nim`) does an all-anchors
convolution-style match over the 128×128 frame with stable / tint / miss
budgets and `flip_h` support. Its sibling `mb_actor_color_index_all`
produces a per-anchor argmax over 16 player colors. Numpy implementation
plan:

1. Build `numpy.lib.stride_tricks.sliding_window_view(frame, sprite_shape)`
   → shape `(maxY, maxX, sh, sw)` view, **zero-copy**.
2. Pre-mask the sprite into `stable_mask`, `tint_mask`, and a
   `transparent_mask` once per sprite.
3. For stable pixels: equality test broadcast against the window view,
   reduce over the sprite axes to get `matched_stable[ay, ax]`.
4. For tint pixels: membership test against a precomputed 16-byte LUT
   `PLAYER_COLORS ∪ SHADOW_MAP[PLAYER_COLORS]` (use a 256-entry boolean
   table indexed by palette byte), reduce to `matched_tint[ay, ax]`.
5. `misses = total_visible - matched_stable - matched_tint`; threshold the
   three counts against `max_misses`, `min_stable`, `min_tint`.
6. For `mb_actor_color_index_all`: per-anchor argmax over 16 player-color
   counts, also expressible as a broadcast equality against a
   `(16, sh, sw)` mask volume, then argmax over axis 0. Ties broken by
   lowest index (matches Python `np.argmax`).

Expected cost: <1 ms per sprite at 128×128 with 24×24 sprites on M-series
Mac. We will measure on the first parity pass. If we miss the budget,
drop the inner sum into a `@numba.njit` kernel — same algorithm, same
inputs/outputs, no API change.

### 5.4 Parity strategy

This is what makes the port credible.

1. **Capture**: No frame-capture utility ships today (the previous plan
   referenced a `scripts/capture.py` that does not exist in this repo).
   At P1, land a `perception/parity/capture_fixtures.py` that either
   (a) instruments `users/james/personal_cogs/among_them/guided_bot/`
   to dump per-tick packed frames + structured state vector + Nim
   percept JSON sidecars during a normal `coworld play` run, or
   (b) replays a recorded Coworld session (the runner already supports
   `replay`). Aim for ~50–100 frames intentionally spanning all
   gameplay phases: lobby, playing, body-sighted, meeting, voting,
   role-reveal, interstitial. Save the packed 128×128 frame plus the
   structured state vector.
2. **Ground truth**: For each fixture, run the existing Nim perception
   (via `guided_bot`'s `libguidedbot.dylib` or a small Nim CLI we write
   for the parity harness) and emit a JSON sidecar with:
   `{actors: [...], tasks: [...], vote_state: {...}, ocr_text: [...],
    interstitial: bool, localized: bool, camera: (x, y)}`.
3. **Diff harness**: `perception/parity/run_parity.py` walks the fixture
   set, runs the Python perception over each packed frame, and asserts
   equality (with documented numeric tolerance for sub-pixel sweeps).
4. **CI gate**: `tests/test_perception_parity.py` runs the harness on a
   trimmed fixture set; perception-layer changes don't merge unless it's
   green.
5. **Maintenance**: parity harness lives under `perception/parity/` and is
   re-runnable. When the Nim baked atlas changes, regenerate fixtures
   *and* `sprite_atlas.npz` from the same Nim snapshot.

### 5.5 Performance budget and measurement

- Target: <8 ms total perception per tick on M-series Mac.
- `tests/test_sprite_match.py` includes a perf assertion with slack
  (e.g. <3 ms for the worst-case sprite sweep).
- Profile with `cProfile` + `line_profiler`; promote any kernel to numba
  only after numbers prove the need.
- Numba cold-start (1–2 s on first call) is a risk for `policy_player.py`
  startup deadlines — warm kernels eagerly during player initialization,
  before signaling ready to the runner. See §10 R2.

---

## 6. Phasing

Stop and review with James at each phase boundary. Each phase is a logically
mergeable unit.

### P0 — Scaffold + Coworld harness

**Deliverables**:
- Package skeleton matching §4.
- `types.py` with skeleton `Observation`, `Percept`, `Belief`, `ActionState`,
  `Intent`, `Command` (most fields will be filled in P1/P2).
- `modes/idle.py` (emits noop).
- `coworld/policy_player.py` — `bitscreen_v1` binary WebSocket bridge (port
  the bits of `guided_bot/coworld/policy_player.py` that we still need,
  minus Nim FFI).
- `coworld/Dockerfile` + `entrypoint.sh`.
- `trace.py` with `LoggingTraceSink` + `LoggingMetricsSink` wired to a
  stderr `StreamHandler`, plus a `JsonStderrTraceSink` (~30 lines).
- `README.md` (short — status + how to run).
- `DESIGN.md` (the durable architecture doc; this PLAN.md gets pared down
  once DESIGN.md exists).
- Smoke test infrastructure: `scripts/play_local.sh` wrapping the
  `coworld play` invocation.

**Done when**:
1. `cd ~/coding/metta && uv run coworld download among_them -o ./coworld`
   succeeds.
2. `docker build -t coborg-among-them:dev -f .../coworld/Dockerfile .`
   produces a working linux/amd64 image.
3. `cd ~/coding/metta && uv run coworld play ./coworld/coworld_manifest.json \
     --variant default --timeout-seconds 120 --no-open-browser \
     coborg-among-them:dev` boots, runs to completion, and the agent emits
   noop actions every tick.
4. Trace events appear on stderr in the container log; stdout shows only
   protocol traffic.
5. `pytest players/among_them/coborg/tests`
   is green.

### P1 — Perception port

**Deliverables**: All §5.2 modules ported. Baked sprite atlas regenerated.
Parity fixture set captured (50–100 frames). `test_perception_parity.py`
green. Per-tick perception measured under 8 ms.

**Done when**:
1. All parity tests pass.
2. Per-tick perception measured under 8 ms on the dev machine.
3. `coworld play` smoke run still passes with live perception wired into
   the runtime (agent still emits noops, but parsed beliefs render in
   stderr traces).
4. `DESIGN.md` updated with any deviations from the Nim semantics.

### P2 — Crewmate

**Deliverables**: Belief layer with self/world/entities/tasks/social/
inferences sections. `modes/navigate_to.py`, `modes/complete_task.py`.
`strategy/rule_based.py` that picks the nearest unfinished task.
`action.py` waypoint movement + A-press timing.

**Done when**: Crewmate agent completes ≥3 tasks in a 120-s `coworld play`
match, no hangs, no illegal actions in stderr traces.

### P3 — Meetings & voting

**Deliverables**: `modes/meeting.py`, `modes/speak.py` (deterministic stub
chat), `modes/vote.py` (default vote-skip), `modes/report_body.py`.
Phase-transition reflex covering playing↔meeting↔voting↔role-reveal.
Evidence ledger updates from chat / voting / body sightings.

**Done when**: Agent transitions through a full meeting cycle, casts a
legal vote, returns to play; verified by stderr trace replay.

### P4 — Imposter

**Deliverables**: `modes/kill_target.py`, `modes/loiter.py`. Role-aware
strategy branching gated on `belief.self.role`. Kill-cooldown-ready reflex.

**Done when**: In imposter-pinned seeds (see `guided_bot/README.md`
seeds 50, 100), agent gets ≥1 successful kill in a 120-s match; if outed,
behaves plausibly in the meeting.

### Out of scope (later)

- LLM strategy (Anthropic / Bedrock async).
- Coworld upload-policy / submit / leagues integration.
- Advanced social reasoning (deception, trust models, alibi tracking).
- Pixel→state-vector hybrid ablation studies.
- Replay tooling improvements.

---

## 7. Coworld integration

### 7.1 Toolchain commands (James-confirmed)

```bash
cd ~/coding/metta
uv run coworld download among_them --output-dir ./coworld
uv run coworld play ./coworld/coworld_manifest.json \
    --variant default \
    --timeout-seconds 120 \
    --no-open-browser \
    coborg-among-them:dev
```

The single positional `player_images` arg is reused for every player slot.
`--run` lets us override the container argv if needed.

### 7.2 Player container shape (as built in P0)

- `coworld/Dockerfile` (base `python:3.12-slim`, `--platform=linux/amd64`):
  1. `ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1`.
  2. `WORKDIR /srv/players`.
  3. Install runtime deps directly so they cache independently of source:
     `pip install "numpy>=2.0.0" "pydantic>=2.12.2" "websockets>=13.0"`.
     This deliberately skips the `cogames` extra in `pyproject.toml` (which
     pulls `cogames` + `mettagrid`, a heavy Bazel + Nim build); the noop
     bot does not need any of it.
  4. `COPY pyproject.toml README.md ./` and `COPY players ./players`.
  5. `pip install --no-deps -e .` (deps are already satisfied above).
  6. `COPY .../coworld/entrypoint.sh /usr/local/bin/entrypoint.sh` and
     `ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]`.
- `coworld/entrypoint.sh` execs
  `python -m players.among_them.coborg.coworld.policy_player "$@"`.
  Stderr stays attached; stdout is reserved as a protocol channel even
  though the bridge connects out, not in.
- `coworld/policy_player.py` is the `bitscreen_v1` binary WebSocket
  bridge. It reads `COGAMES_ENGINE_WS_URL` (the runner injects this with
  `?slot=N&token=…` already filled in), holds one `AgentRuntime`, and
  calls `runtime.step(observation)` per inbound 8192-byte frame, sending
  each resulting wire packet back to the server. Pinned against
  `~/coding/metta/packages/coworld/src/coworld/runner/runner.py` at SHA
  `e791117ff1aac01a8ae220c258ab121876511aed`; verify against that file
  before each phase boundary and update the pin in `coworld/README.md`.

### 7.3 Manifest variants

The `--variant default` flag will fall back to `manifest.variants[0]` if no
`default` variant exists. Confirm at P0 by inspecting the downloaded
`coworld_manifest.json`. If the hosted manifest's game constants differ
from §3.4, prefer the manifest values.

---

## 8. Logging / tracing

- Top-level `logging.basicConfig(stream=sys.stderr, level=logging.INFO,
  format="%(asctime)s %(levelname)s %(name)s %(message)s")`.
- Coborg `LoggingTraceSink` and `LoggingMetricsSink` point at a logger
  whose only handler is `StreamHandler(sys.stderr)`.
- Add a tiny `JsonStderrTraceSink` that writes one JSON-line per
  `TraceEvent` to stderr — mirrors the structured trace shape used by
  `guided_bot`'s `trace.py`. This is what we'll grep when debugging
  post-run.
- **Stdout is reserved for protocol traffic.** Audit dependencies for
  rogue `print()` calls in P0; if any show up, redirect or replace.
- Trace event names follow the Coworld Player SDK canonical set as
  actually emitted by `players.player_sdk`: `perception`, `belief_updated`,
  `mode_entered`, `mode_exited`, `mode_completed`, `mode_stalled`,
  `reflex_evaluated`, `reflex_fired`, `action_intent`, `act_command`,
  `snapshot_submitted`, `strategy_evaluated`, `strategy_inferences`,
  `directive_rejected`, `directive_reaffirmed`, `fallback_activated`.
  Game-specific extensions reserved for later phases: `phase_change`,
  `body_sighted`, `task_started`, `task_completed`, `kill_attempted`,
  `vote_cast`, `chat_received`, `chat_sent`. The authoritative copy of
  this vocabulary lives in `DESIGN.md` §7; treat that section as the
  source of truth and keep it in sync if the SDK adds events.

---

## 9. Testing strategy

- **Unit**: per-layer — frame, sprite_match, actors, tasks, voting, ocr,
  localize, belief, each mode, action resolver, rule strategy, reflexes.
- **Parity**: `perception/parity/` harness gates all perception changes.
- **Mode lifecycle**: `on_enter`/`on_exit`, scratch reset on real switches,
  scratch preservation on reaffirmation.
- **Reflex**: priority ordering, fallback activation, TTL expiry traces.
- **Adapter smoke**: `test_coworld_player_smoke.py` replays a recorded
  `bitscreen_v1` transcript and asserts the expected action stream.
- **End-to-end**: every phase ends with a passing `coworld play` run; CI
  gates the cheap subset.

---

## 10. Risks / unknowns

| # | Risk | Mitigation |
|---|---|---|
| R1 | **`uv run` mettagrid build flakiness — root cause identified 2026-05-13.** `uv run coworld --help` rebuilds mettagrid (Bazel C++ + Nim mettascope), and the Nim step calls `nimby sync -g nimby.lock`. Failures observed: (a) stale `~/.nimby/nimbylock/` left behind by an earlier aborted nimby run, causing every subsequent invocation to print `Nimby is already running, delete ~/.nimby/nimbylock to release lock`; (b) cache corruption — `~/.nimby/pkgs/<name>/` directories missing their `.git`, causing nimby's `git status --porcelain` precheck to fail with `fatal: not a git repository`. Both were live as of 2026-05-13. **Important**: nimby does **not** clean `~/.nimby/nimbylock/` on error, so every failed sync leaves the lock behind; the mettagrid build backend's 3× retry loop hits the same stuck lock and is effectively a no-op. | **Recovery procedure** (run if the build stalls on `nimby sync` again):<br>1. `rmdir ~/.nimby/nimbylock` (safe iff `lsof +D ~/.nimby/nimbylock` is empty and `pgrep -fl nimby` is empty).<br>2. If sync then reports `fatal: not a git repository` for a pkg, delete that pkg dir under `~/.nimby/pkgs/<name>/` and re-run; nimby re-clones from the URL in `nimby.lock`.<br>3. Run `nimby sync -g nimby.lock` directly inside `~/coding/metta/packages/mettagrid/nim/mettascope/` to confirm before retrying the full `uv run` flow.<br>**Hard-blocker escalation**: if the issue recurs frequently, file an upstream nimby bug for the unreleased lock on error and ask the mettagrid team to wrap nimby invocations with a try/finally that clears `~/.nimby/nimbylock` on failure. |
| R2 | **Hot-path perception perf.** Numpy *should* be sufficient for sprite_match. If not, numba cold-start (1–2 s) may break the `policy_player.py` startup deadline. | Eagerly warm numba kernels during player init, before signaling ready to the runner. Measure cold-start; if it's a problem, AOT-compile via numba `cache=True`. |
| R3 | **Baked sprite-atlas drift.** `data.nim` + `baked/` are tied to game asset versions. The port snapshot can silently rot if upstream changes. | Keep `generate_baked.py` runnable and re-runnable. Add a checksum check that compares the Nim baked file digest against a stored digest; fail loudly on mismatch. |
| R4 | **OCR / voting parser edge cases.** Game screens have many corner states. | Port the simple cases first; leave explicit `TODO(parity-edge-case)` markers. Rely on the parity fixture set to surface the rare states; add fixtures when we hit one in the wild. |
| R5 | **Pixel vs state-vector divergence.** Some belief fields (e.g. exact task progress percentage) are easier and lossless from the structured state vector. | Pixel-first overall, but allow specific fields to be sourced from the state vector. Document each such field in `DESIGN.md` under a "State-vector taps" section. James drafted-approved this (D9). |
| R6 | **Coworld manifest variants.** `--variant default` may not exist on every variant set. | Inspect `coworld_manifest.json` at P0; fall back to `manifest.variants[0]` and surface the choice in `play_local.sh`. |
| R7 | **Protocol drift.** `bitscreen_v1` is the binary wire protocol BitWorld serves to Among Them players (see `~/coding/bitworld/docs/bitscreen_v1.md` and the spec at https://github.com/Metta-AI/bitworld/blob/master/docs/bitscreen_v1.md). The `guided_bot/coworld/policy_player.py` port is correct as of 2026-05-13; verify against the BitWorld spec and against `~/coding/metta/packages/coworld/src/coworld/runner/runner.py` at P0 and again at P4. | Pin against runner.py at the version that was current when this plan was written; record the git SHA in `coworld/README.md`. Re-check the `bitscreen_v1` spec doc whenever upgrading the bitworld submodule. |
| R8 | **Nim libguidedbot.dylib dependency for parity ground truth.** Parity needs the Nim perception to produce JSON sidecars. | At P1 we'll either (a) ship a small Nim CLI inside `perception/parity/` that reuses `guided_bot`'s perception modules, or (b) instrument `guided_bot`'s existing run to dump per-frame parity sidecars. (a) is preferred — keeps the parity rig self-contained. |

---

## 11. First-week sequence (start here in the new session)

1. **Verify the Coworld toolchain works at all.** From `~/coding/metta`:
   - `git pull` (was 10 commits behind origin/main on 2026-05-13; clean
     working tree, fast-forward safe).
   - `uv run coworld --help` — confirms mettagrid (Bazel C++ + Nim
     mettascope) rebuilds cleanly. **Verified working 2026-05-13** after
     clearing stale nimby state per R1 recovery procedure.
   - `uv run coworld download among_them --output-dir ./coworld` — must
     succeed. **Verified working 2026-05-13**; produces
     `coworld_manifest.json` and `coworld_images.json` (Among Them
     `0.1.11`). Pulls Docker images from
     `public.ecr.aws/q5f4m8t9/cogames`.
   - Try `uv run coworld play ./coworld/coworld_manifest.json --variant default --timeout-seconds 120 --no-open-browser <any-existing-noop-image>` to confirm the play path works. If the existing scripted Among Them policy has been packaged as an image, use that; otherwise pull the official noop player.
   - If the mettagrid rebuild stalls on `nimby sync`, apply the R1
     recovery procedure (clear `~/.nimby/nimbylock/`, delete any
     `~/.nimby/pkgs/<name>/` missing `.git`, re-run sync). If it still
     fails, surface to James before writing any code.
2. **Land P0 scaffold.** Mirror §4 layout. Get the noop agent through a full `coworld play` run with stderr traces visible. Don't move on until §6 P0 done-criteria are all green.
3. **Capture parity fixtures from current `guided_bot`.** No
   ready-made capture utility exists; land
   `perception/parity/capture_fixtures.py` first (see §5.4 step 1)
   that either instruments
   `users/james/personal_cogs/among_them/guided_bot/` to dump per-tick
   packed frames + Nim percept JSON sidecars during a `coworld play`
   run, or replays a recorded Coworld session. Aim for 50–100 frames
   spanning all phases. Check fixtures into
   `perception/parity/fixtures/`.
4. **Start the perception port at `frame.py` then `sprite_match.py`.** Get
   parity-green on actor matches first; that proves the spine of the
   port. Then ripple through `actors → tasks → localize → ocr → voting`.

---

## 12. Open questions to confirm with James in the new session

These were drafted in the plan but not explicitly confirmed:

1. **D8** — Numpy-first / numba-fallback perception strategy. Default is
   numpy first, measure, promote to numba per-kernel only if needed.
2. **D9** — Allowing specific belief fields (e.g. `task_progress`) to be
   sourced from the structured state vector when pixels would be lossy.
   Default is "yes, document each tap in DESIGN.md."
3. **Phasing stop point** — Plan ends at P4 (deterministic imposter-capable
   agent). LLM is explicitly out of scope. Confirm before P5 work is
   scheduled.
4. **Where does Nim parity ground truth come from?** Plan default is a
   small Nim CLI inside `perception/parity/` that reuses `guided_bot`'s
   perception modules. Confirm vs. instrumenting `guided_bot` directly.

---

## 13. Important context the new session must preserve

- **CLAUDE.md global rules apply.** Located at `~/.claude/CLAUDE.md`. Highlights: be direct/candid, push back when something is wrong, keep design docs current, treat docs as load-bearing, prefer existing dependencies, never commit secrets, run scaled tests, use Graphite stacks for PRs, never push or open PRs unprompted.
- **Today's date when this plan was written**: 2026-05-13.
- **User**: James Boggs (jmsboggs@gmail.com).
- **Active production bot is `guided_bot`**, not this one. Do not modify
  guided_bot or its submission flow unless James explicitly says so.
- **The Coworld Player SDK has no other concrete game agents yet.** This
  bot is the SDK's first real client; treat the SDK docs (especially the
  "Design Invariants" and "Anti-Patterns" sections of
  `players/player_sdk/docs/metta_cogames_framework/README.md`) as
  non-negotiable. Those docs still use "Cyborg framework" as the
  architecture name; the package was renamed to `players.player_sdk` /
  "Coworld Player SDK" but the underlying two-loop architecture name
  is retained there.
- **Stdout = protocol, stderr = logs.** Audit deps for stray `print()`
  during P0.
- **One Docker image fills all 8 player slots** in `coworld play`.
- **Parity-first perception**: don't merge perception changes without
  green parity tests against the Nim output.
- **R1 uv run flakiness — root-caused and resolved 2026-05-13.** Recovery
  procedure stays documented in §10 R1 in case the nimby lock ever sticks
  again.

---

## 14. Pointer summary (cheat-sheet)

Paths without a leading `~/` or `/` are relative to this repo root
(`~/coding/players_checkouts/players_main/` on James's machine).

| Need | Path |
|---|---|
| Player SDK framework code | `players/player_sdk/` |
| Player SDK framework docs | `players/player_sdk/docs/metta_cogames_framework/README.md` |
| Player SDK toy example | `players/player_sdk/docs/metta_cogames_framework/examples/toy_grid_agent.py` |
| Existing scripted Among Them (state-vector reference) | `players/among_them/scripted/__init__.py` |
| BitWorld Among Them game source (Nim) | `~/coding/bitworld/among_them/` |
| Game constants (source of truth) | `~/coding/bitworld/among_them/coworld_manifest.json`, `~/coding/bitworld/among_them/config.json` |
| Native player bots (reference only) | `~/coding/bitworld/among_them/players/` |
| Current production bot (do NOT modify; port source) | `users/james/personal_cogs/among_them/guided_bot/` |
| Nim perception (shared kernels; port source) | `users/james/personal_cogs/among_them/common/perception_kernels/` |
| Nim perception (bot-specific; port source) | `users/james/personal_cogs/among_them/guided_bot/perception/` |
| Existing coworld player bridge to mirror | `users/james/personal_cogs/among_them/guided_bot/coworld/policy_player.py` |
| Frame capture script | _(not yet implemented; see §5.4 step 1 and §11 item 3)_ |
| Coworld CLI source | `~/coding/metta/packages/coworld/src/coworld/cli.py` |
| Coworld play source | `~/coding/metta/packages/coworld/src/coworld/play.py` |
| Coworld runner (protocol authority) | `~/coding/metta/packages/coworld/src/coworld/runner/runner.py` |
| This plan | `players/among_them/coborg/PLAN.md` |
