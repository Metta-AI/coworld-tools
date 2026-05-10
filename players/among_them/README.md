# Among Them

[Among Them](https://softmax.com/alignmentleague) is the BitWorld
social-deduction game in the cogames Alignment League Benchmark. An 8-player
Among-Us clone running over the same 128x128 4-bit palette interface as the
rest of BitWorld, with 2 imposters and 8 tasks per player by default.

Current season: `among-them` (verify with `cogames season list`).

## Active agent

`guided_bot/` is the only active Among Them bot in this directory.
`modulabot/` is fully deprecated and remains only as historical reference.
Do not inspect, modify, test, run, benchmark, ship, or otherwise work on
the local modulabot unless James explicitly asks for modulabot work in
the current prompt.

## Agents in this directory

| Agent | Status | Strategy |
|---|---|---|
| [`modulabot/`](modulabot/README.md) | **deprecated / historical only** | Former Python port of the Nim modulabot architecture. Keep the code for future reference, but do not read, modify, test, run, or submit it unless explicitly asked. |
| [`guided_bot/`](guided_bot/README.md) | phase 6 in progress — full perception pipeline, A\* pathfinding, 6 mode handlers (task\_completing, hunting, pretending, reporting, fleeing, meeting) with complete lifecycles, 4-reflex system, LLM guidance loop, structured trace writer, all 8 Nim test suites passing | Modular Nim hybrid: fast scripted inner loop (perceive/update/decide/act) driven by a slow asynchronous LLM guidance loop that sets active `mode` + structured params. LLM takes direct control during meetings (phase 3). See [`guided_bot/DESIGN.md`](guided_bot/DESIGN.md). |

## Shared code

- [`common/`](common/README.md) — shared utilities consumed by **two
  or more** agents in this directory. Currently:
  [`common/perception_kernels/`](common/perception_kernels/) holds
  the pure-Nim perception kernels (sprite matching, camera fit /
  patch hash, task icon scan, OCR). The kernels were extracted when
  both modulabot and guided_bot consumed them; guided_bot is now the
  active consumer and modulabot is historical-only. The bar for adding
  to `common/` is still real reuse by active code -- don't
  speculatively grow it.

## Conventions

- One agent per subdirectory. Each has its own `README.md` answering:
  what strategy, current status, leaderboard score once submitted, what's
  next.
- Submission bundle root is the agent directory (e.g. `guided_bot/`). The
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
  guide (`how_to_make_a_bot.md`). Treat upstream modulabot material as
  historical prior art only; active architectural decisions belong in
  [`guided_bot/DESIGN.md`](guided_bot/DESIGN.md).
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

Each agent ships its own tests. For active Among Them work, use
guided_bot's checks. The full suite is documented in
[`guided_bot/README.md`](guided_bot/README.md#tests); common quick checks
from the repo root are:

```bash
# Build the guided_bot shared library used by the cogames wrapper.
python3 among_them/guided_bot/build_guided_bot.py

# Python action-table guard.
PYTHONPATH=among_them .venv/bin/python -m unittest \
    among_them.guided_bot.test.test_action_table -v

# Fallback/playability Nim suite.
nim c -r -d:release --threads:on --mm:orc \
    among_them/guided_bot/test/fallback_test.nim
```

Do not run modulabot's tests unless James explicitly asks for modulabot.

---

## Running a bot

There are several ways to run the active guided_bot policy, depending on
what you're testing. All play scripts accept `-p class.Path` to select
the policy and `--policy-kwarg KEY=VALUE` for constructor args.

Some scripts still have an old modulabot default. Always pass
`-p guided_bot.cogames.amongthem_policy.AmongThemPolicy` for current
work unless James explicitly asks for another policy.

| Mode | What it does | Server needed? | Script |
|---|---|---|---|
| [Local episode](#local-episode-play_localpy) | Starts server + fillers, connects 1 agent | No (starts its own) | `scripts/play_local.py` |
| [Connect to server](#connect-to-server-connectpy) | Connects N agents to an existing server | Yes (you provide it) | `scripts/connect.py` |
| Live debug overlay | **Deprecated modulabot-only tooling** | n/a | `scripts/play_watch.py` |
| Debug harness | **Deprecated modulabot-only tooling** | n/a | `scripts/play_debug.py` |
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
PYTHONPATH=among_them python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 20
```

Use `--policy-kwarg` to pass constructor options:

```bash
PYTHONPATH=among_them python among_them/scripts/play_local.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --duration 60 \
    --metrics-out /tmp/metrics.jsonl
```

| Flag | Default | Notes |
|---|---|---|
| `-p` / `--policy` | pass `guided_bot.cogames.amongthem_policy.AmongThemPolicy` | Policy class path. |
| `--policy-kwarg` | | `KEY=VALUE` (repeatable). |
| `--duration` | 60 | Wall-clock seconds. 0 = indefinite. |
| `--num-players` | 8 | Total lobby size. |
| `--max-ticks` | derived | From `--duration` if omitted. |
| `--seed` | 42 | Policy RNG seed (also seeds server role shuffle). |
| `--imposter-count` | 2 | Number of imposters. |
| `--force-role` | off | `crewmate` or `imposter` — pins the first player slot via the server's `"slots"` config. **Not 100% reliable** due to a connection-order race with fillers; use known-good seeds instead (see below). |
| `--trace-dir` | off | Enables per-run trace output. |
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
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --host 127.0.0.1 --port 2000
```

**Multiple agents:**

```bash
PYTHONPATH=among_them python among_them/scripts/connect.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --host 127.0.0.1 --port 2000 --num-agents 4 --duration 120
```

**Run indefinitely** (until Ctrl-C or server disconnect):

```bash
PYTHONPATH=among_them python among_them/scripts/connect.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --host 127.0.0.1 --port 2000 --duration 0
```

| Flag | Default | Notes |
|---|---|---|
| `--host` | `127.0.0.1` | Server address. |
| `--port` | 2000 | Server port. |
| `-p` / `--policy` | pass `guided_bot.cogames.amongthem_policy.AmongThemPolicy` | Policy class path. |
| `--name` | derived from policy | Player name. With `--num-agents > 1`, agents are named `<name>-0`, etc. |
| `--num-agents` | 1 | Number of agents, each on its own WebSocket. |
| `--duration` | 60 | Seconds. **0 = run indefinitely.** |
| `--seed` | 42 | Seed for agent 0. Agent *i* uses `seed + i`. |
| `--connect-timeout` | 10 | WebSocket connect timeout (seconds). |
| `--trace-dir` | off | Enables per-run trace output. |
| `--trace-level` | `decisions` | `off`, `events`, or `decisions`. |
| `--metrics-out` | off | Per-tick JSONL (all agents interleaved, sorted by tick). |
| `--capture-frames` | off | Raw `.npy` frame dump. Per-agent suffix added when `--num-agents > 1`. |

### Legacy debug overlays

`scripts/play_watch.py`, `scripts/play_debug.py`, and
`scripts/debug_overlay.py` are modulabot-specific visual debugging tools.
Do not use them unless James explicitly asks for modulabot. For guided_bot,
use trace output (`--trace-dir`, `--trace-level`) and the live test
workflow in [`guided_bot/README.md`](guided_bot/README.md).

### All-agent match (`play_match.py`)

Starts a server and fills every slot with a Python policy instance
(no fillers). Useful for watching agents play against each other.

```bash
PYTHONPATH=among_them python among_them/scripts/play_match.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy
# Custom count + duration:
PYTHONPATH=among_them python among_them/scripts/play_match.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
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

### Legacy modulabot analysis scripts

`scripts/debug_overlay.py` and `scripts/bench_perception.py` run the
deprecated modulabot pipeline. Do not use them for guided_bot work unless
James explicitly asks for modulabot.

---

## Tournament submission (`cogames ship`)

Use guided_bot's submission wrapper for active Among Them submissions:

```bash
cd /Users/jamesboggs/coding/personal_cogs/among_them/guided_bot/cogames
SEASON=among-them POLICY_NAME="$USER-guided-bot" ./ship.sh dry-run
```

Or run `cogames ship` directly from the repo root:

```bash
cogames ship \
    -p "class=guided_bot.cogames.amongthem_policy.AmongThemPolicy" \
    -f among_them/guided_bot \
    -f among_them/common/perception_kernels \
    -n "$USER-guided-bot" \
    --season among-them \
    --dry-run          # remove once dry-run is clean
```

Do not ship modulabot unless James explicitly asks for a modulabot
submission.

### Upload without submitting

Split the process into separate steps when you want to upload first and
submit later, or submit an already-uploaded policy to a different season:

```bash
# 1. Bundle
cogames create-bundle \
    -p "class=guided_bot.cogames.amongthem_policy.AmongThemPolicy" \
    -o submission.zip \
    -f among_them/guided_bot \
    -f among_them/common/perception_kernels

# 2. Upload (dry-run validates in Docker)
cogames upload -p ./submission.zip -n "$USER-guided-bot" --no-submit

# 3. Submit to a season
cogames submit "$USER-guided-bot" --season among-them

# 4. Track
cogames submissions --season among-them --policy "$USER-guided-bot"
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
`GUIDED_BOT_TRACE_DIR` environment variable). The trace is a structured
JSONL stream recording every policy branch decision.

```bash
# Via flag
PYTHONPATH=among_them python among_them/scripts/connect.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --host 127.0.0.1 --port 2000 \
    --trace-dir /tmp/guided_bot_runs --trace-level decisions

# Via env vars
export GUIDED_BOT_TRACE_DIR=/tmp/guided_bot_runs
export GUIDED_BOT_TRACE_LEVEL=decisions
```

See [`guided_bot/README.md` -- Tracing](guided_bot/README.md#tracing) for
the schema, trace levels, and output layout.

---

## Environment variables

| Variable | Effect |
|---|---|
| `AMONG_THEM_BINARY` | Override path to the Nim `among_them` server binary. |
| `FILLER_BOT_BINARY` | Override path to the Nim `nottoodumb` filler bot binary. |
| `GUIDED_BOT_TRACE_DIR` | Enable guided_bot JSONL tracing to this directory. |
| `GUIDED_BOT_TRACE_LEVEL` | `decisions` or `full`; prefer the play-script `--trace-level` flag. |
| `ANTHROPIC_API_KEY` | Enables guided_bot's LLM guidance loop in submissions/local runs. |

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
