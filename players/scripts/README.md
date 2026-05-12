# Benchmark Scripts

Harness for evaluating scripted agents on CogsGuard missions via `cogames scrimmage`.

## Scripts

For an end-to-end runbook, see `cogames-agents/docs/scripted-baselines-howto.md`.

### `benchmark_agents.sh`

Runs every registered scripted agent through `cogames scrimmage` and saves per-agent JSON results.

```bash
# Run all agents (defaults: 10 episodes, 1000 steps, arena)
./scripts/benchmark_agents.sh

# Custom run
./scripts/benchmark_agents.sh -e 20 -s 2000 -m arena -o ./my_results

# Subset of agents
./scripts/benchmark_agents.sh -a role,baseline,wombo -e 50
```

**Options:**

| Flag     | Default                 | Description                |
| -------- | ----------------------- | -------------------------- |
| `-e`     | 10                      | Episodes per agent         |
| `-s`     | 1000                    | Max steps per episode      |
| `-m`     | `arena`                 | Mission                    |
| `-o`     | `./benchmark_results`   | Output directory           |
| `-a`     | all agents              | Comma-separated agent list |
| `--seed` | 42                      | RNG seed                   |

Results are written to `<outdir>/<timestamp>/<agent>.json`.

### `compare_agents.py`

Parses benchmark JSON results and prints a ranked comparison table.

```bash
# Table output (default)
python scripts/compare_agents.py ./benchmark_results/20260128_143000

# CSV for spreadsheets
python scripts/compare_agents.py ./benchmark_results/20260128_143000 --format csv

# JSON for programmatic use
python scripts/compare_agents.py ./benchmark_results/20260128_143000 --format json
```

**Metrics captured:**

| Metric                    | Source                                        | Description                |
| ------------------------- | --------------------------------------------- | -------------------------- |
| `reward`                  | per-episode avg                               | Average agent reward       |
| `heart.gained`            | `env_agent/heart.gained`                      | Hearts collected           |
| `heart.lost`              | `env_agent/heart.lost`                        | Hearts consumed            |
| `aligned.junction.held`   | `avg_game_stats["cogs/aligned.junction.held"]`   | Junctions held             |
| `aligned.junction.gained` | `avg_game_stats["cogs/aligned.junction.gained"]` | Junctions aligned          |
| `action_timeouts`         | policy summary                                | Action generation timeouts |

### `quick_eval.sh`

Fast single-agent eval for development iteration (3 episodes, 500 steps by default).

```bash
# Quick table output
./scripts/quick_eval.sh role

# JSON output
./scripts/quick_eval.sh nlanky --json

# Open in MettaScope GUI
./scripts/quick_eval.sh baseline --gui

# Custom parameters
./scripts/quick_eval.sh wombo -e 5 -s 1000 --seed 99
```

### `run_scripted_baselines_report.py`

Thread Vision staged one-command artifact pipeline for scripted baselines. Runs static role specialists + adaptive
gap-filler on a fixed seed matrix and writes:

- `scripted_baselines_report.json` (Stage 2 + Stage 3 technical bundle: KPI/guardrail threshold checks, stage rollups,
  richer role-event signals, BC-readiness checks, shaped-reward alignment checks, and locked technical sprint-gate
  results; retention/cohort metrics are intentionally out-of-scope for this script)
- `scripted_baselines_report.html` (shareable summary with stage-status cards, compact role fingerprint radar, pass/fail
  badges, and per-role failure symptom/next fix)

```bash
# Default seeds (11,23,42)
uv run python cogames-agents/scripts/run_scripted_baselines_report.py

# Custom output directory and seeds
uv run python cogames-agents/scripts/run_scripted_baselines_report.py \
  --output-dir outputs/scripted_baselines_stage2_3 \
  --seeds 11,23,42

# Allow report generation without failing CI/automation on gate misses
uv run python cogames-agents/scripts/run_scripted_baselines_report.py --no-enforce-gates
```

### `launch_amongthem_cyborg_llm_observer.py`

Launches a local BitWorld AmongThem server, opens the global observer, and connects eight agents to one batched
`amongthem_cyborg` policy with LLM-backed meeting talk. The launcher rebuilds the local BitWorld AmongThem server and NotTooDumb shared
library first so the observer route and Nim-backed policy evidence API match the current checkout. Normal observer runs
use the canonical settings: eight players, two imposters, eight tasks per crewmate, 1200-tick imposter cooldown, and a
600-tick vote timer; the smoke command below intentionally lowers the task load.

```bash
uv run python cogames-agents/scripts/launch_amongthem_cyborg_llm_observer.py

# Bind to this machine's Tailscale IPv4 and print a shareable observer URL
uv run python cogames-agents/scripts/launch_amongthem_cyborg_llm_observer.py --tailscale

# Bedrock/Anthropic explicitly
CLAUDE_CODE_USE_BEDROCK=1 uv run python cogames-agents/scripts/launch_amongthem_cyborg_llm_observer.py \
  --provider anthropic --tailscale --model global.anthropic.claude-sonnet-4-5-20250929-v1:0

# OpenAI explicitly
OPENAI_API_KEY=... uv run python cogames-agents/scripts/launch_amongthem_cyborg_llm_observer.py \
  --provider openai --tailscale

# Fast baseline/debug run with only the local NotTooDumb core
uv run python cogames-agents/scripts/launch_amongthem_cyborg_llm_observer.py --tailscale --no-llm-talk

# Quick task-completion smoke
uv run python cogames-agents/scripts/launch_amongthem_cyborg_llm_observer.py \
  --tailscale --imposters 0 --tasks-per-player 1 --task-complete-ticks 36 --no-llm-talk
```

Open the observer manually if the browser does not launch: `http://localhost:2000/client/global.html?reconnect=1` or the
Tailscale URL printed by `--tailscale`.

## Available Agents

Registered scripted agents (from `cogames-agents` package):

| Agent                | Description                     |
| -------------------- | ------------------------------- |
| `role`               | Python multi-role CogsGuard     |
| `role_nim`           | Multi-role Nim CogsGuard policy |
| `nlanky`             | Nim goal-tree scripted agent    |
| `wombo`              | Alternative multi-role          |
| `baseline`           | Standard baseline               |
| `tiny_baseline`      | Minimal baseline                |
| `cogsguard_v2`       | CogsGuard v2                    |
| `cogsguard_control`  | Control-focused variant         |
| `cogsguard_targeted` | Targeted behavior               |
| `teacher`            | Teacher wrapper                 |
| `ladybug_py`         | Ladybug Python                  |
| `thinky`             | High-cognition Nim              |
| `nim_random`         | Nim random                      |
| `race_car`           | Race car Nim                    |
| `ladybug`            | Ladybug Nim                     |
| `alignall`           | All-aligner Nim                 |

Canonical tutorial role policies (`miner`, `scout`, `aligner`, `scrambler`) live in `cogames`.
