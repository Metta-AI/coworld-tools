# Among Them

[Among Them](https://softmax.com/alignmentleague) is the BitWorld
social-deduction game in the cogames Alignment League Benchmark. An 8-player
Among-Us clone running over the same 128x128 4-bit palette interface as the
rest of BitWorld, with 2 imposters and 8 tasks per player by default.

Current public competition: Coworld v2 **Among Them Daily** (verify from
`~/coding/metta` with `uv run coworld leagues`). The legacy `cogames`
`among-them` season is a separate surface and should not be used for Daily
league status or submission.

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
| [`guided_bot/`](guided_bot/README.md) | phase 6 core behavior live-verified — full perception pipeline, hierarchical waypoint navigation, 6 complete gameplay/meeting mode handlers, 4-reflex system, LLM guidance loop, structured trace writer with optional frame capture, focused Nim/Python checks passing | Modular Nim hybrid: fast scripted inner loop (perceive/update/decide/act) driven by a slower asynchronous LLM guidance loop that sets active `mode` + structured params. Meeting chat and vote choice are LLM-controlled through a guarded action queue; gameplay mode params and per-mode scratch summaries are included in LLM snapshots. See [`guided_bot/DESIGN.md`](guided_bot/DESIGN.md). |

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
- Legacy submission bundle root is the agent directory (e.g. `guided_bot/`).
  The `cogames ship` command gets `-f <agent_dir>`; everything the policy
  imports must live inside that directory. Current Among Them Daily uses
  the Docker-image Coworld flow in `guided_bot/coworld/` instead.

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

Docker is required for the public Among Them Docker-image submission flow and
for legacy `cogames upload --dry-run` validation.

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
| [Public submission](#public-submission-docker-image) | Build linux/amd64 image + upload + submit | Cloud (Softmax infra) | `guided_bot/coworld/README.md` |
| Legacy bundle upload | Older Python bundle path | Cloud (Softmax infra) | `guided_bot/cogames/ship.sh` |

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
| `--imposter-cooldown-ticks` | 1200 | Imposter kill cooldown in server ticks. Useful for fast imposter iteration. |
| `--tasks-per-player` | 8 | Tasks assigned to each crewmate. Useful for keeping voting-focused tests from ending by tasks too early. |
| `--force-role` | off | `crewmate` or `imposter` — pins the first player slot via the server's `"slots"` config. **Not 100% reliable** due to a connection-order race with fillers; use known-good seeds instead (see below). |
| `--trace-dir` | off | Enables per-run trace output. |
| `--trace-level` | `decisions` | `off`, `events`, `decisions`, or `full`. Use `full` to record `frames.bin`. |
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
| `--trace-level` | `decisions` | `off`, `events`, `decisions`, or `full`. Use `full` to record `frames.bin`. |
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
# Small imposter iteration with shorter kill cooldown:
PYTHONPATH=among_them python among_them/scripts/play_match.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --num-agents 4 --num-players 4 --imposter-count 1 \
    --imposter-cooldown-ticks 600 --duration 180 --seed 42
# Voting-mechanics check with frame traces:
PYTHONPATH=among_them python among_them/scripts/play_match.py \
    -p guided_bot.cogames.amongthem_policy.AmongThemPolicy \
    --num-agents 8 --num-players 8 --imposter-count 2 \
    --imposter-cooldown-ticks 600 --tasks-per-player 16 \
    --duration 90 --seed 42 \
    --trace-dir among_them/guided_bot/traces --trace-level full
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

## Public submission (Docker image)

The current public Among Them instructions are
<https://softmax.com/play_amongthem.md>. They submit a standalone linux/amd64
Docker image to the Coworld v2 **Among Them Daily** league. The image connects
to the hosted runner through `COGAMES_ENGINE_WS_URL`; the flow does not use the
older Python policy bundle or the legacy `cogames submit --season among-them`
surface.

Use guided_bot's image path:

```bash
cd /Users/jamesboggs/coding/personal_cogs/among_them
export IMAGE=jamesboggs-guided-bot-public:$(date +%Y%m%d-%H%M%S)
export POLICY_NAME=jamesboggs-guided-bot-public-$(date +%Y%m%d-%H%M%S)

docker buildx build \
    --platform linux/amd64 \
    -t "$IMAGE" \
    --load \
    -f guided_bot/coworld/Dockerfile \
    .

docker run --rm --platform linux/amd64 "$IMAGE" /bin/guided_bot --help
```

Then use the Coworld v2 CLI from the Metta checkout:

```bash
cd /Users/jamesboggs/coding/metta
uv run softmax login
uv run coworld leagues
uv run coworld download among_them --output-dir ./coworld
uv run coworld run-episode ./coworld/coworld_manifest.json "$IMAGE"

uv run coworld upload-policy "$IMAGE" \
    --name "$POLICY_NAME" \
    --use-bedrock \
    --secret-env GUIDED_BOT_BEDROCK_MODEL=global.anthropic.claude-sonnet-4-5-20250929-v1:0

uv run coworld submit "$POLICY_NAME:v1" \
    --league league_494db37d-d046-4cba-a99a-536b1439262f
uv run coworld submissions --policy "$POLICY_NAME:v1" --json
```

See [`guided_bot/coworld/README.md`](guided_bot/coworld/README.md) for the
runtime protocol, Coworld v2 status commands, and the Docker 29 ECR manifest
workaround.

Do not ship modulabot unless James explicitly asks for a modulabot submission.
The old `guided_bot/cogames/ship.sh` path is legacy bundle tooling only; it does
not create the Docker-image-backed policy version expected by
`play_amongthem.md`.

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
| `GUIDED_BOT_TRACE_LEVEL` | `off`, `events`, `decisions`, or `full`; prefer the play-script `--trace-level` flag. |
| `USE_BEDROCK` | Set by `coworld upload-policy --use-bedrock`; makes guided_bot prefer AWS Bedrock credentials. |
| `GUIDED_BOT_BEDROCK_MODEL` | Optional Bedrock model override for Coworld submissions. |
| `ANTHROPIC_API_KEY` | Enables guided_bot's LLM guidance loop in submissions/local runs. |

---

## Game constants (from `mettagrid.bitworld`)

- Screen: 128 x 128, 4-bit indexed palette (PICO-8).
- Players: 8 (2 imposters).
- Tasks per player: 8.
- Vote timer: 600 ticks.
- Imposter kill cooldown: 1200 ticks.
- Action space: 27 discrete actions (directional + A/B combinations).

If the hosted configuration differs from these defaults, download and inspect
the Coworld manifest:

```bash
cd /Users/jamesboggs/coding/metta
uv run coworld download among_them --output-dir ./coworld
uv run python -m json.tool ./coworld/coworld_manifest.json
```
