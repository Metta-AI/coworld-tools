# Among Them

[Among Them](https://softmax.com/alignmentleague) is the BitWorld
social-deduction game in the cogames Alignment League Benchmark. An 8-player
Among-Us clone running over the same 128x128 4-bit palette interface as the
rest of BitWorld, with 2 imposters and 8 tasks per player by default.

Current season: `among-them` (verify with `cogames season list`).

## Agents in this directory

| Agent | Status | Strategy |
|---|---|---|
| [`modulabot/`](modulabot/README.md) | full perception + crewmate task lifecycle complete; 236 tests passing | Modular scripted bot ported from the Nim `modulabot` architecture — pixel-mode perception (sprite matching, camera localization, voting parser, A\*), crewmate task selection / approach / hold / server-confirmed completion (with radar-dot evidence + icon-miss negative-evidence pruning), imposter fake-task/kill/flee, evidence-based voting. See [`modulabot/CREWMATE_TASK_FIX_PLAN.md`](modulabot/CREWMATE_TASK_FIX_PLAN.md) for the recent task-lifecycle fix work (Phases 0-4 + 6-7, Apr--May 2026). |
| [`guided_bot/`](guided_bot/README.md) | phase 2 complete — A\* pathfinding, 6 mode handlers (task\_completing, hunting, pretending, reporting, fleeing, meeting), 4-reflex system, all 7 Nim test suites passing | Modular Nim hybrid: fast scripted inner loop (perceive/update/decide/act) driven by a slow asynchronous LLM guidance loop that sets active `mode` + structured params. LLM takes direct control during meetings (phase 3). See [`guided_bot/DESIGN.md`](guided_bot/DESIGN.md). |

## Shared code

- [`common/`](common/README.md) — shared utilities consumed by **two
  or more** agents in this directory. Currently:
  [`common/perception_kernels/`](common/perception_kernels/) holds
  the pure-Nim perception kernels (sprite matching, camera fit /
  patch hash, task icon scan, OCR) that both modulabot and guided_bot
  import. The bar for adding to `common/` is at least two real
  consumers -- don't speculatively grow it.

## Conventions

- One agent per subdirectory. Each has its own `README.md` answering:
  what strategy, current status, leaderboard score once submitted, what's
  next.
- Submission bundle root is the agent directory (e.g. `modulabot/`). The
  cogames `ship` command gets `-f <agent_dir>`; everything the policy
  imports must live inside that directory. Code under `common/` that
  an agent's submission needs is bundled via `-f among_them/common/...`
  alongside the agent dir.

## Reference material

Prior art lives outside this repo and should be cited explicitly rather
than copied unless we need to:

- `~/coding/bitworld/among_them/players/` — canonical Nim bots
  (`nottoodumb.nim`, `modulabot/`, `evidencebot_v2.nim`), the battle-tested
  submission guide (`how_to_submit_to_cogames.md`), and the deep bot-making
  guide (`how_to_make_a_bot.md`). Read `modulabot/DESIGN.md` before making
  any architectural decisions here.
- `~/coding/metta/cogames-agents/src/cogames_agents/policy/bitworld_among_them.py` —
  Softmax's own scripted Python policies (`BitWorldAmongThemScoutPolicy`,
  `BitWorldAmongThemCyborgPolicy`). Good prior art for the BitWorld action
  space, state-observation layout, and the LLM-chat optional extra.
- `cogames docs amongthem_policy` — official walkthrough.
- `cogames tutorial make-policy --amongthem -o template.py` — up-to-date
  starter policy template.

---

## Prerequisites

All commands assume the repo root as cwd and the project venv activated:

```bash
cd /Users/jamesboggs/coding/personal_cogs
source .venv/bin/activate
```

The venv has `cogames`, `mettagrid`, and `bitworld` already installed.
Do not reinstall -- activate and use.

Scripts that start a local Nim server need the pre-built binaries:

| Binary | Default location | Override |
|---|---|---|
| `among_them` (server) | `~/coding/bitworld/out/among_them` | `AMONG_THEM_BINARY=<path>` or `--server-binary` |
| `nottoodumb` (filler bot) | `~/coding/bitworld/out/nottoodumb` | `FILLER_BOT_BINARY=<path>` or `--filler-binary` |

Docker is required for `cogames ship --dry-run` / `cogames upload --dry-run`.

---

## Running tests

Each agent ships its own tests. For modulabot, run from the repo root:

```bash
PYTHONPATH=among_them .venv/bin/python -m unittest discover \
    -s among_them/modulabot/tests
```

Expected: **236 tests, 0 failures**. With `MODULABOT_DISABLE_NATIVE=1` a
handful of Nim FFI parity tests skip; everything else passes via the
pure-Python fallback.

Run a single test module:

```bash
PYTHONPATH=among_them .venv/bin/python -m unittest \
    among_them.modulabot.tests.test_voting -v
```

---

## Running a bot

There are several ways to run modulabot (or any `-p` compatible policy),
depending on what you're testing. All play scripts accept `-p class.Path`
to select the policy and `--policy-kwarg KEY=VALUE` for constructor args.

| Mode | What it does | Server needed? | Script |
|---|---|---|---|
| [Local episode](#local-episode-play_localpy) | Starts server + fillers, connects 1 agent | No (starts its own) | `scripts/play_local.py` |
| [Connect to server](#connect-to-server-connectpy) | Connects N agents to an existing server | Yes (you provide it) | `scripts/connect.py` |
| [Live debug overlay](#live-debug-overlay-play_watchpy) | 1 agent + real-time perception overlay window | Yes (you provide it) | `scripts/play_watch.py` |
| [Debug harness](#debug-harness-play_debugpy) | Starts server + fillers + debug overlay | No (starts its own) | `scripts/play_debug.py` |
| [All-agent match](#all-agent-match-play_matchpy) | Starts server, fills all slots with agents | No (starts its own) | `scripts/play_match.py` |
| [Standalone server](#standalone-server-serverpy) | Start a server only, print host:port | n/a | `scripts/server.py` |
| [Capture frames](#capture-frames-capturepy) | Passive capture to .npy (no policy) | No (starts its own) | `scripts/capture.py` |
| [Tournament submission](#tournament-submission-cogames-ship) | Bundle + validate + upload + submit | Cloud (Softmax infra) | `cogames ship` |
| [Upload without submitting](#upload-without-submitting) | Bundle + upload only | Cloud (Softmax infra) | `cogames upload` + `cogames submit` |

> `cogames play` does **not** support Among Them -- it only works for
> CvC-family games. Use the scripts above for all Among Them local runs.

### Local episode (`play_local.py`)

Boots a real Nim server, fills the lobby with `nottoodumb` filler bots,
and connects one agent. Requires the Nim binaries.

```bash
PYTHONPATH=among_them python among_them/scripts/play_local.py --duration 20
```

Use `-p` to run a different policy:

```bash
PYTHONPATH=among_them python among_them/scripts/play_local.py \
    -p modulabot.policy.AmongThemPolicy --duration 60 \
    --metrics-out /tmp/metrics.jsonl
```

| Flag | Default | Notes |
|---|---|---|
| `-p` / `--policy` | `modulabot.policy.AmongThemPolicy` | Policy class path. |
| `--policy-kwarg` | | `KEY=VALUE` (repeatable). |
| `--duration` | 60 | Wall-clock seconds. 0 = indefinite. |
| `--num-players` | 8 | Total lobby size. |
| `--max-ticks` | derived | From `--duration` if omitted. |
| `--seed` | 42 | Policy RNG seed (also seeds server role shuffle). |
| `--imposter-count` | 2 | Number of imposters. |
| `--force-role` | off | `crewmate` or `imposter` — pins the first player slot via the server's `"slots"` config. **Not 100% reliable** due to a connection-order race with fillers; use known-good seeds instead (see below). |
| `--trace-dir` | off | Sets `MODULABOT_TRACE_DIR`. |
| `--trace-level` | `decisions` | `off`, `events`, or `decisions`. |
| `--metrics-out` | off | Per-tick JSONL. |
| `--capture-frames` | off | Frame `.npy` dump. |

**`--force-role` reliability note:** The flag has a race condition —
filler bots may claim slot 0 before the policy bot's first game tick
is processed. To reliably test a specific role, use known seeds:
- **Imposter seeds** (with `--force-role imposter`): 50, 100
- **Crewmate seeds** (any seed without `--force-role`, or seeds 1,
  7, 42, 99, 200 which ignore the flag)

Expected output: ~450 frames over 20 seconds, observation shape
`(4, 128, 128)`, action mix showing directional movement + A-presses.

### Connect to server (`connect.py`)

Connects one or more agents to an **already-running** server.
Does not start a server or spawn fillers -- you provide those.

**Single agent:**

```bash
PYTHONPATH=among_them python among_them/scripts/connect.py \
    --host 127.0.0.1 --port 2000
```

**Multiple agents:**

```bash
PYTHONPATH=among_them python among_them/scripts/connect.py \
    --host 127.0.0.1 --port 2000 --num-agents 4 --duration 120
```

**Run indefinitely** (until Ctrl-C or server disconnect):

```bash
PYTHONPATH=among_them python among_them/scripts/connect.py \
    --host 127.0.0.1 --port 2000 --duration 0
```

| Flag | Default | Notes |
|---|---|---|
| `--host` | `127.0.0.1` | Server address. |
| `--port` | 2000 | Server port. |
| `-p` / `--policy` | `modulabot.policy.AmongThemPolicy` | Policy class path. |
| `--name` | derived from policy | Player name. With `--num-agents > 1`, agents are named `<name>-0`, etc. |
| `--num-agents` | 1 | Number of agents, each on its own WebSocket. |
| `--duration` | 60 | Seconds. **0 = run indefinitely.** |
| `--seed` | 42 | Seed for agent 0. Agent *i* uses `seed + i`. |
| `--connect-timeout` | 10 | WebSocket connect timeout (seconds). |
| `--trace-dir` | off | Sets `MODULABOT_TRACE_DIR`. |
| `--trace-level` | `decisions` | `off`, `events`, or `decisions`. |
| `--metrics-out` | off | Per-tick JSONL (all agents interleaved, sorted by tick). |
| `--capture-frames` | off | Raw `.npy` frame dump. Per-agent suffix added when `--num-agents > 1`. |

### Live debug overlay (`play_watch.py`)

Connects one agent to an existing server and opens a tkinter window
showing the raw frame + perception overlay in real time. Requires a
running server.

```bash
PYTHONPATH=among_them python among_them/scripts/play_watch.py \
    --host 127.0.0.1 --port 2000
```

Close the window or press q/Esc to stop. Use `--render-every N` if the
overlay lags (BitWorld ticks at ~42 ms; the overlay renders at ~30-50 ms).

### Debug harness (`play_debug.py`)

One-shot: starts server + `nottoodumb` fillers + one agent with the
live debug overlay window. No manual server setup needed.

```bash
PYTHONPATH=among_them python among_them/scripts/play_debug.py
# With options:
PYTHONPATH=among_them python among_them/scripts/play_debug.py \
    --duration 120 --num-players 6 --trace-dir /tmp/debug
```

### All-agent match (`play_match.py`)

Starts a server and fills every slot with a Python policy instance
(no fillers). Useful for watching agents play against each other.

```bash
PYTHONPATH=among_them python among_them/scripts/play_match.py
# Custom count + duration:
PYTHONPATH=among_them python among_them/scripts/play_match.py \
    --num-agents 6 --duration 120 --seed 42
```

Each agent gets its own trace directory and metrics file. A viewer
URL is printed on startup.

### Standalone server (`server.py`)

Starts just the Nim server and prints `host:port` to stdout. Useful
when you want to connect clients separately (e.g. `connect.py` or
`play_watch.py`).

```bash
PYTHONPATH=among_them python among_them/scripts/server.py --num-players 8
```

### Capture frames (`capture.py`)

Starts a server + fillers and dumps raw 128x128 observation frames to an
`.npy` file (no policy -- sends noops). Used to build test fixtures.

```bash
PYTHONPATH=among_them python among_them/scripts/capture.py \
    --duration 20 --output /tmp/captured.npy
```

### Post-hoc debug overlay (`debug_overlay.py`)

Runs the full perception pipeline over previously captured `.npy` frames
and renders annotated overlays. Useful for offline debugging.

```bash
PYTHONPATH=among_them python among_them/scripts/debug_overlay.py \
    /tmp/mb_frames.npy --frame 150 --save /tmp/overlay.png
```

| Flag | Notes |
|---|---|
| `--frame N` | Render a single frame. |
| `--range START:END` | Render a range of frames. |
| `--outdir DIR` | Save all overlays to a directory. |
| `--summary` | Print perception stats without rendering. |
| `--watch` | Scrub through frames interactively. |
| `--scale N` | Upscale factor (default 4). |

### Perception benchmark (`bench_perception.py`)

Reports p50/p95/p99/max/mean timing for each perception kernel and
end-to-end `BotCore.step`. Run before and after any perception change.

```bash
PYTHONPATH=among_them python among_them/scripts/bench_perception.py
```

---

## Tournament submission (`cogames ship`)

`cogames ship` bundles, validates (dry-run), uploads, and submits in one
step:

```bash
cogames ship \
    -p "class=modulabot.policy.AmongThemPolicy" \
    -f among_them/modulabot \
    -n "$USER-modulabot-py" \
    --season among-them \
    --dry-run          # remove once dry-run is clean
```

The `-f among_them/modulabot` flag bundles the whole package. If the
policy pulls in external files (trained weights, prompt templates), add
another `-f`.

### Upload without submitting

Split the process into separate steps when you want to upload first and
submit later, or submit an already-uploaded policy to a different season:

```bash
# 1. Bundle
cogames create-bundle \
    -p "class=modulabot.policy.AmongThemPolicy" \
    -o submission.zip \
    -f among_them/modulabot

# 2. Upload (dry-run validates in Docker)
cogames upload -p ./submission.zip -n "$USER-modulabot-py" --no-submit

# 3. Submit to a season
cogames submit "$USER-modulabot-py" --season among-them

# 4. Track
cogames submissions --season among-them --policy "$USER-modulabot-py"
cogames season matches among-them --limit 20
```

### Secrets (LLM keys)

If the policy needs an API key at runtime:

```bash
cogames upload -p ./submission.zip -n my-llm-policy \
    --secret-env ANTHROPIC_API_KEY=sk-ant-...
```

### The 10-step validation gate

`--dry-run` (and `ship` without `--skip-validation`) runs the policy for
exactly 10 steps in Docker and requires at least one non-NOOP action.

Pixel-perception bots often spend the first 10 frames in an interstitial
(role-reveal splash) and emit only NOOPs by design. For that specific
failure -- `"Policy took no actions (all no-ops)"` -- and **only** that
failure, `--skip-validation` is appropriate. Any other dry-run error
(import failure, traceback, ABI mismatch) means fix the bug.

---

## Tracing

All play scripts support trace output via `--trace-dir` (or the
`MODULABOT_TRACE_DIR` environment variable). The trace is a structured
JSONL stream recording every policy branch decision.

```bash
# Via flag
PYTHONPATH=among_them python among_them/scripts/connect.py \
    --host 127.0.0.1 --port 2000 \
    --trace-dir /tmp/modulabot_runs --trace-level decisions

# Via env vars
export MODULABOT_TRACE_DIR=/tmp/modulabot_runs
export MODULABOT_TRACE_LEVEL=decisions
```

See [`modulabot/README.md` -- Tracing](modulabot/README.md#tracing) for
the full schema, trace levels, and output layout.

---

## Environment variables

| Variable | Effect |
|---|---|
| `AMONG_THEM_BINARY` | Override path to the Nim `among_them` server binary. |
| `FILLER_BOT_BINARY` | Override path to the Nim `nottoodumb` filler bot binary. |
| `MODULABOT_DISABLE_NATIVE=1` | Skip Nim FFI, use pure-Python perception fallback. |
| `MODULABOT_TRACE_DIR` | Enable JSONL trace writer to this directory. |
| `MODULABOT_TRACE_LEVEL` | `decisions` (default) or `events`. |
| `MODULABOT_TRACE_META` | Comma-separated `key=value` pairs for the trace manifest. |

---

## Game constants (from `mettagrid.bitworld`)

- Screen: 128 x 128, 4-bit indexed palette (PICO-8).
- Players: 8 (2 imposters).
- Tasks per player: 8.
- Vote timer: 600 ticks.
- Imposter kill cooldown: 1200 ticks.
- Action space: 27 discrete actions (directional + A/B combinations).

If the tournament configuration differs from these defaults for a given
season, check `cogames season show among-them` for the exact config.
