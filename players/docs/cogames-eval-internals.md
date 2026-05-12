# CoGames Run Command Internals

Analysis of the `cogames run` and `cogames scrimmage` command implementation in the metta codebase. This document
covers the eval pipeline architecture, metrics collection, output formats, and identifies observability gaps relevant to
leaderboard optimization.

## 1. Run Command Implementation and Flags

### Entry Point

The evaluation command is defined in `packages/cogames/src/cogames/main.py` (lines 1150-1331). It is registered under two
names:

- `cogames run` -- multi-policy evaluation
- `cogames scrimmage` -- single-policy evaluation

The `scrimmage` variant enforces exactly one `--policy` with no proportion split. `cogames run` accepts multiple
policies for multi-policy evaluation.

The CLI framework is **Typer** with Rich console output.

### Flags

| Flag                  | Short | Default      | Description                                                                     |
| --------------------- | ----- | ------------ | ------------------------------------------------------------------------------- |
| `--mission`           | `-m`  | required     | Missions to evaluate (supports wildcards)                                       |
| `--cogs`              | `-c`  | from mission | Number of agents                                                                |
| `--variant`           | `-v`  |              | Mission variant (repeatable)                                                    |
| `--policy`            | `-p`  | required     | Policy spec (repeatable, supports proportions)                                  |
| `--episodes`          | `-e`  | 10           | Number of evaluation episodes                                                   |
| `--steps`             | `-s`  | 1000         | Max steps per episode                                                           |
| `--seed`              |       | 42           | RNG seed                                                                        |
| `--map-seed`          |       | same as seed | MapGen seed for procedural maps                                                 |
| `--action-timeout-ms` |       | 250          | Max ms per action before noop                                                   |
| `--format`            |       | (tables)     | Output format: `yaml` or `json`                                                 |
| `--save-replay-dir`   |       |              | Directory to save replay files                                                  |

### Policy Spec Format

Policies are specified as strings. Examples:

- `lstm` -- named policy
- `class=lstm,data=./train_dir/run/model_000001.pt` -- policy with checkpoint
- `s3://bucket/path/checkpoints/run:v5` -- URI-based policy spec

When multiple policies are given, proportions control agent allocation via `allocate_counts()` (see scoring.py).

## 2. Metrics Captured by Default

### Data Model

Per-episode raw data (`EpisodeRolloutResult` in `mettagrid/simulator/multi_episode/rollout.py:11`):

```
assignments: np.ndarray    # agent_id -> policy_idx
rewards: np.ndarray        # agent_id -> scalar reward
action_timeouts: np.ndarray # agent_id -> timeout count
stats: dict                # {"game": {...}, "agent": [{...}, ...]}
replay_path: str | None
steps: int                 # actual steps taken
max_steps: int             # configured max
```

### Aggregated Metrics

The summary layer (`mettagrid/simulator/multi_episode/summary.py`) produces:

**Game-level metrics** (averaged across episodes):

- All keys under `stats["game"]` -- examples include `game.steps`, `game.energy_used`, and mission-specific counters.

**Policy-level metrics** (`MultiEpisodeRolloutPolicySummary`):

- `agent_count` -- number of agents assigned to this policy
- `avg_agent_metrics` -- per-agent averages of all keys in `stats["agent"]` for agents belonging to this policy
- `action_timeouts` -- total timeouts across all episodes for this policy

**Per-episode reward breakdown**:

- `per_episode_per_policy_avg_rewards[episode_idx][policy_idx]` -- average reward per agent for each policy in each
  episode

### Agent Stats Keys (Common)

The exact keys depend on the mission/environment, but typical agent stats include: `heart.gained`, `carbon.gained`,
`oxygen.gained`, `heart.lost`, `energy.used`, `actions.total`, and mission-specific counters.

## 3. How Episodes Are Run and Scored

### Evaluation Pipeline

The core pipeline is in `packages/cogames/src/cogames/evaluate.py`:

1. **Validate** -- check missions and policies are provided, validate proportions sum correctly.

2. **For each mission:** a. `allocate_counts()` distributes agents among policies by weight (largest-remainder method).
   b. `np.repeat(np.arange(len(counts)), counts)` creates the initial assignment array.

3. **Episode loop** (`run_multi_episode_rollout()` in `mettagrid/runner/rollout.py`):
   - For each episode:
     - Shuffle assignments via `rng.shuffle(assignments)` (randomizes which agent slots get which policy).
     - `run_single_episode_rollout()` creates the environment, loads policies, runs the simulation, collects
       rewards/stats/timeouts.
     - Seed increments per episode: `seed + episode_idx`.
     - Optional replay capture to `.json.z` files.

4. **Aggregation** -- `build_multi_episode_rollout_summaries()` averages game stats across episodes and agent stats per
   policy.

5. **Output** -- formatted tables or JSON/YAML serialization.

### Scoring Utilities

`packages/cogames/src/metta_alo/scoring.py` provides:

- `allocate_counts(total, weights)` -- distribute N agents among K policies
- `compute_weighted_scores()` -- weighted average of per-match policy scores
- `value_over_replacement()` -- VOR = candidate_score - replacement_score
- `summarize_vor_scenario()` -- accumulates VOR stats from rollout results

The `pickup` command (`cogames pickup`) uses VOR to evaluate a candidate policy against a replacement pool.

## 4. Output Format and Logging

### Console Output (Default)

Five Rich tables are printed to the console:

1. **Policy Assignments** -- mission x policy x agent_count
2. **Average Game Stats** -- mission x metric x average value
3. **Average Policy Stats** -- per policy: mission x metric x average value
4. **Average Per-Agent Reward** -- mission x episode x per-policy avg reward
5. **Action Generation Timeouts** -- (only if timeouts > 0) mission x policy x timeout count

### Structured Output (--format)

With `--format json` or `--format yaml`, the output is a serialized Pydantic model:

```json
{
  "missions": [
    {
      "mission_name": "arena",
      "mission_summary": {
        "episodes": 10,
        "policy_summaries": [...],
        "avg_game_stats": {...},
        "per_episode_per_policy_avg_rewards": {...}
      }
    }
  ]
}
```

This is produced via `model.model_dump(mode="json")` on nested Pydantic models.

### Replay Output

When `--save-replay-dir` is specified, each episode produces a `.json.z` compressed replay file. The CLI prints the
replay command:

```
cogames replay <replay_path>
```

## 5. Wandb Integration Points

**There is no wandb integration in the eval/diagnose commands.**

The `cogames run`/`scrimmage`/`diagnose` pipelines do not import or call wandb. No metrics are logged to wandb during
evaluation.

Wandb integration exists only in:

- The **training pipeline** (`cogames tutorial train`) -- logs training curves, losses, and periodic eval metrics during
  training.

This is a significant observability gap. Eval results are ephemeral unless captured via `--format json` to a file.

## 6. Observability Gaps

### Missing Metrics for Leaderboard Optimization

| Gap                                | Description                                                                                                                           | Impact                                                      |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **No per-agent role performance**  | Agent stats are averaged across all agents in a policy. Individual role breakdown (miner, scout, aligner, scrambler) is not captured. | Cannot identify which roles contribute most to wins.        |
| **No resource efficiency metrics** | No resource-gathered-per-step or conversion ratios.                                                                                   | Cannot optimize resource gathering strategies.              |
| **No timing breakdowns**           | No per-step wall-clock timing or action latency distribution. Only aggregate timeout counts.                                          | Cannot identify performance bottlenecks in scripted agents. |
| **No win/loss tracking**           | No explicit success/failure flag. Only raw rewards.                                                                                   | Must infer outcomes from reward thresholds.                 |
| **No episode variance metrics**    | No std-dev, min/max, or confidence intervals on rewards.                                                                              | Cannot assess consistency of a policy.                      |
| **No role transition tracking**    | No data on how agents change roles during episodes.                                                                                   | Cannot evaluate adaptive role-switching strategies.         |
| **No structure interaction stats** | No data on junction/extractor/hub usage frequency.                                                                                    | Cannot diagnose bottlenecks in resource pipelines.          |
| **No wandb logging**               | Results disappear after terminal output.                                                                                              | No historical comparison across runs.                       |
| **No cross-mission aggregation**   | Each mission reported independently. No composite score.                                                                              | Must manually aggregate for leaderboard ranking.            |

### What We Can Do in cogames-agents (Without Modifying Metta Core)

1. **Post-process JSON output** -- parse `--format json` output and compute derived metrics (variance, composite scores,
   win rates).

2. **Wrapper script** -- invoke `cogames run --format json`, capture output, enrich with additional analysis,
   optionally log to wandb.

3. **Leverage existing trace modules** -- our `role_trace`, `rollout_trace`, and `prereq_trace` modules already capture
   per-agent role and resource data during instrumented rollouts. A unified eval wrapper can combine the standard eval
   metrics with trace-based enrichment.

See `scripts/enrich_eval_output.py` for the post-processing tool implementation.
