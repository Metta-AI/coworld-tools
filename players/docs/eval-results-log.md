# Eval Results Log

Continuous evaluation tracking for the cogas agent. Each row is appended automatically by `scripts/ci_eval.sh` after a
successful eval run.

**Columns:**

- **AJH** — aligned.junction.held (game-level)
- **AJG** — aligned.junction.gained (game-level)
- **Reward** — average per-episode reward
- **H+** / **H-** — heart.gained / heart.lost (agent-level)
- **Timeouts** — action_timeouts (policy-level)

| Date | Version | Policy | AJH | AJG | Reward | H+  | H-  | Timeouts |
| ---- | ------- | ------ | --- | --- | ------ | --- | --- | -------- |

## Run: 2026-01-28 — Pre-Submission Dry Run (cg-ooz8)

### Environment

- **Machine**: local macOS (darwin aarch64)
- **cogames CLI**: wrapper at `~/.local/bin/cogames` → `uv run --project /Users/relh/Code/metta python -m cogames.main`
- **mettagrid**: 0.2.0.58 (installed in metta monorepo)
- **Mission**: `cogsguard_arena.basic` (88x88, 10 agents, 1000 steps)
- **Branch**: `polecat/mutant/cg-ooz8@mkyyp1yg`

### Setup Required

The `cogas` policy is **not installed** in the metta monorepo by default. To make it available to the `cogames` CLI:

```bash
# Symlink cogas module into metta's cogames-agents package
ln -s /path/to/co_gas/cogames-agents/src/cogames_agents/policy/scripted_agent/cogas \
      /path/to/metta/cogames-agents/src/cogames_agents/policy/scripted_agent/cogas
```

After symlinking, `cogames policies` lists `cogas` and `cogames validate-policy -p cogas` passes.

### Critical Blocker: `aligned.junction.held` Not Emitted

**The `aligned.junction.held` metric does not appear in game stats output.** This is not a cogas-specific issue — no
agent (including the Nim `role` agent) produces junction metrics on `cogsguard_arena.basic` locally.

Game stats only include:

- `chest.*.deposited` / `chest.*.amount` (resource deposits)
- `objects.*` (map object counts)
- `tokens_*` (token space metrics)

Agent metrics only include:

- `action.*` (move success/failure, noop, change_vibe)
- `energy.*` / `hp.*` (resource amounts)
- `status.max_steps_without_motion`

**No junction, heart, alignment, or reward metrics are emitted.** This suggests the locally installed mettagrid/cogames
version does not instrument junction tracking, or the `cogsguard_arena.basic` mission config does not enable junction
scoring.

### Available Metrics (10 Episodes, Default Params)

| Metric                    | Value   |
| ------------------------- | ------- |
| Total resources deposited | 7,990   |
| HP at end (avg)           | 9.1     |
| HP gained (avg)           | 1,562.3 |
| HP lost (avg)             | 1,553.2 |
| Successful moves (avg)    | 3,258   |
| Failed moves (avg)        | 3,094   |
| Noop actions (avg)        | 3,638   |
| Action timeouts           | 0       |
| Max steps without motion  | 982.3   |
| Energy at end (avg)       | 45.3    |

### Role Distribution Comparison (5 Episodes Each)

| Config                                | Deposited | HP End | HP Gained | Moves | Noop  | Stuck Max |
| ------------------------------------- | --------- | ------ | --------- | ----- | ----- | --------- |
| Default (A=4, S=3, M=2, Sc=1)         | 7,990     | 9.1    | 1,562.3   | 3,258 | 3,638 | 982.3     |
| Heavy Aligner (A=6, S=2, M=1, Sc=1)   | 8,020     | 9.9    | 865.3     | 1,669 | 1,828 | 411.9     |
| Balanced (A=3, S=3, M=3, Sc=1)        | 7,980     | 2.0    | 747.9     | 1,616 | 1,735 | 491.7     |
| Heavy Scrambler (A=3, S=5, M=1, Sc=1) | 8,420     | 10.5   | 0.2       | 1,666 | 1,774 | 412.2     |
| Mining Focus (A=2, S=2, M=5, Sc=1)    | 8,160     | 13.6   | 768.5     | 1,634 | 1,801 | 452.5     |

All distributions produce similar resource deposits (~8,000). Without junction metrics, it's impossible to determine
which distribution best maximizes `aligned.junction.held`.

The Heavy Scrambler config produced the highest total deposits (8,420) and highest end-of-episode HP (10.5). The Default
config has the highest move count and HP gained, suggesting more active gameplay.

### Agent Behavior Observations

1. **Agent moves and interacts**: The cogas agent successfully moves (~3,258 moves per 10 episodes), changes vibes, and
   manages energy/HP. It is not stuck or idle.
2. **High move failure rate**: ~49% of move attempts fail, suggesting pathfinding collisions or blocked paths.
3. **Stuck detection fires**: `max_steps_without_motion` of 982 (out of 1000) in the default config indicates some
   agents get stuck for extended periods. The alternate configs show much lower stuck values (~400-500), suggesting the
   default distribution may over-allocate roles that depend on junctions.
4. **No timeouts**: Action timeouts are 0 across all runs, confirming the policy responds within time limits.
5. **HP management**: Agents maintain non-zero HP at episode end (9.1 avg), suggesting the survival goals work.

### Blockers for Full Eval

1. **Primary**: `aligned.junction.held` metric is not emitted by the local cogames/mettagrid installation. The
   leaderboard submission target metric cannot be measured locally.
2. **Secondary**: The `cogas` module must be manually symlinked into the metta monorepo's `cogames-agents` package. It
   should be contributed upstream or the eval harness should support loading from external paths.
3. **Unit tests stale**: 50 of 92 tests fail because the test expectations reference the old API (Phase.BOOTSTRAP, 3
   miners + flex role, etc.) while the code has been updated to use Phase.EARLY/MID/LATE and different defaults (4
   aligners, 3 scramblers, 2 miners, 1 scout). Tests need updating to match current implementation.

### Recommendations

1. **Run on machina1 or cloud**: The `aligned.junction.held` metric may only be tracked in the production mettagrid
   build (e.g., on mettabox containers or the tournament server). Local eval cannot verify this metric.
2. **Update unit tests**: Align test expectations with the current cogas implementation.
3. **Upstream the cogas module**: Add it to the metta monorepo's cogames-agents package so `cogames` CLI can find it
   without symlinks.
4. **Debug mode eval**: Once junction metrics are available, run with `cogas?debug=2` to get per-tick junction state
   logging for bottleneck analysis.

### Commands Used

```bash
# Validate policy
cogames validate-policy -p cogas

# Default 10-episode eval
cogames scrimmage -m cogsguard_arena.basic \
  -p "metta://policy/cogas?aligner=4&scrambler=3&miner=2&scout=1" \
  -e 10 -s 1000 --seed 42 --format json

# Alternate distributions (5 episodes each)
cogames scrimmage -m cogsguard_arena.basic \
  -p "metta://policy/cogas?aligner=6&scrambler=2&miner=1&scout=1" \
  -e 5 -s 1000 --seed 42 --format json

cogames scrimmage -m cogsguard_arena.basic \
  -p "metta://policy/cogas?aligner=3&scrambler=3&miner=3&scout=1" \
  -e 5 -s 1000 --seed 43 --format json

cogames scrimmage -m cogsguard_arena.basic \
  -p "metta://policy/cogas?aligner=3&scrambler=5&miner=1&scout=1" \
  -e 5 -s 1000 --seed 44 --format json

cogames scrimmage -m cogsguard_arena.basic \
  -p "metta://policy/cogas?aligner=2&scrambler=2&miner=5&scout=1" \
  -e 5 -s 1000 --seed 45 --format json
```
