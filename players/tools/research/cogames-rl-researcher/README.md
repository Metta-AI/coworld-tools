# cogames-rl-researcher

Claude-first RL researcher workflows for CoGames.

## Prompt Layer (Meta-Workflows)

If you want an AI agent (Codex/Claude) to run the workflow end-to-end, use the prompt pack:

- `cogames-rl-researcher/prompts/run-neophyte-workflow.md`
- `cogames-rl-researcher/prompts/run-experienced-workflow.md`

These prompts are the meta-layer. The scripts in this package are the tools those prompts call.

One-line commands:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_agent_workflow.py --agent codex --profile neophyte
./cogames-rl-researcher/scripts/run_ai_researcher_agent_workflow.py --agent claude --profile experienced
```

## Startup Workflow

Run the startup loop:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_startup.py \
  --policy metta://policy/role_py \
  --policy-name my-policy \
  --season beta-cvc
```

Startup writes `docs_digest.json` from CoGames docs each run. Use `--allow-interactive-login` to allow browser-based
auth recovery in local/manual runs. Gate checks are enforced by default; pass `--no-enforce-gates` to allow non-passing
runs to exit zero. Use `--researcher-profile neophyte` for stricter reliability/coverage gate budgets and documented
happy-path workflow enforcement.

## Resume Workflow

Resume from an existing run directory or `audit_bundle.json`:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_resume.py \
  --source ./artifacts/ai_researcher/20260212_120000
```

Optionally feed an explicit mined failure report into actor/critic + fix-pack ranking:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_resume.py \
  --source ./artifacts/ai_researcher/20260212_120000 \
  --log-mining-report ./artifacts/ai_researcher/log_mining_report.json
```

Opt into swarm planning during resume (still optional):

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_resume.py \
  --source ./artifacts/ai_researcher/20260212_120000 \
  --emit-swarm-plan \
  --swarm-workers 4
```

Resume pulls in submitted crash-defect backlog actions by default. Disable this with `--no-defect-fix-actions`.

## Pickup Workflow

Run pickup as a runnable diagnose/scrimmage shadow workflow:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_pickup.py \
  --policy class=greedy \
  --pool class=random \
  --pool class=greedy \
  --mission machina_1
```

Artifacts are written under `./artifacts/ai_researcher/<timestamp>_pickup/` and include:

- `pickup_result.json`
- `pickup_diagnosis.md`
- `replays/`

## Actor/Critic Workflow

Run actor/critic analysis on audit bundles:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_actor_critic.py \
  --current ./artifacts/ai_researcher/20260212_130000/audit_bundle.json \
  --baseline ./artifacts/ai_researcher/20260212_120000/audit_bundle.json \
  --output ./artifacts/ai_researcher/20260212_130000/actor_critic_report.json
```

## Optional Swarm Workflow

Build a multi-agent swarm task plan from actor/critic output:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_swarm.py \
  --actor-critic-report ./artifacts/ai_researcher/20260212_130000/actor_critic_report.json \
  --output ./artifacts/ai_researcher/20260212_130000/swarm_plan.json \
  --workers 4 \
  --timeout-seconds 900 \
  --max-tasks-per-worker 1
```

## Submit Coverage Workflow

Run a variant pack that expands valid submit coverage and writes a summary artifact:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_coverage_pack.py \
  --variants-file ./variants.json \
  --output ./artifacts/ai_researcher/coverage_pack.json \
  --policy metta://policy/role_py \
  --season beta-cvc
```

`variants.json` is a JSON list with entries like
`{"variant_id":"v1","policy_name":"my-policy-v1","experiment_family":"aligner"}`. If `experiment_family` is omitted,
family is inferred from the policy name for breadth tracking.

Generate the next tuned variant pack proposal from coverage and actor/critic artifacts:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_coverage_tuning.py \
  --coverage-pack ./artifacts/ai_researcher/coverage_pack.json \
  --actor-critic-report ./artifacts/ai_researcher/latest/actor_critic_report.json \
  --output ./artifacts/ai_researcher/coverage_tuning_plan.json
```

## CoGames Research Command

Run a single command that can train and then execute startup + resume researcher loops:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_research.py \
  --policy metta://policy/role_py \
  --policy-name my-policy \
  --train-command "uv run ./tools/run.py train arena run=my_exp trainer.total_timesteps=100000" \
  --season beta-cvc
```

Use `--skip-train` when you only want submission/diagnosis orchestration. `research` also supports
`--researcher-profile` and `--no-enforce-gates`.

## Log Mining Service

Mine failed `cogames` command attempts from gastown/claude/codex logs into durable artifacts:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_log_mining_service.py \
  --log-root ./artifacts \
  --log-root ./logs \
  --output ./artifacts/ai_researcher/log_mining_report.json \
  --iterations 1
```

Use `--watch` for continuous service mode.

## Crash Defect Intake

Submit crash defects and maintain a shared backlog:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_defect_intake.py \
  --store-dir ./artifacts/ai_researcher/defects \
  submit \
  --reporter claude \
  --command "cogames upload --name my-policy --policy metta://policy/role_py --season beta-cvc" \
  --observed-error "authentication failed: token expired"
```

Regenerate backlog summary:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_defect_intake.py \
  --store-dir ./artifacts/ai_researcher/defects \
  backlog
```

Generate a ranked fix plan from open/triaged defects:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_defect_intake.py \
  --store-dir ./artifacts/ai_researcher/defects \
  fix-plan
```

Validate a proposed fix command for a specific defect:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_defect_intake.py \
  --store-dir ./artifacts/ai_researcher/defects \
  validate-fix \
  --defect-id defect-20260223-120000-abcd1234 \
  --fix-command "uv run pytest cogames-rl-researcher/tests/test_resume.py -q"
```

Pass `--mark-fixed-on-success` when you want successful validation to set defect status to `fixed`.

Artifacts are written under `./artifacts/ai_researcher/<timestamp>/` and include:

- `audit_bundle.json`
- `docs_digest.json` + `docs_digest.md` (docs readthrough artifact from CoGames docs)
- `daily_report.md` (includes reaper SLO + historical comparison summary)
- `ranked_next_actions.json` (resume)
- `history_comparison.json` (baseline-vs-current comparison over recent runs)
- `gates_evaluation.json` (profile-aware quality gate results)
- `escalation_plan.json` (escalation guidance based on gate outcomes/history)
- `actor_critic_report.json` (resume/analysis, including significance assessment for deltas)
- `fix_pack_plan.json` (auto-proposed fix packs derived from log-mined failure signatures)
- `defect_fix_plan.json` (ranked next fixes from crash defect backlog)
- `swarm_plan.json` (optional swarm planner)
- `coverage_pack.json` (submit-coverage expansion summary with experiment-family breadth metrics)
- `coverage_tuning_plan.json` (ranked next variant pack proposal)
- `research_command_summary.json` (single-command training + submission orchestration status)
- `log_mining_report.json` + `log_mining_report.md` (mined cogames failure signatures by agent)
- `defects/crash_defects.jsonl` + `defects/defect_backlog.json` + `defects/defect_fix_plan.json`
- `defects/fix_attempts.jsonl` + `defects/fix_attempt_logs/*` (fix validation attempts)
- `steps/*.stdout.log` and `steps/*.stderr.log`
- `replays/`

## Development

```bash
uv run pytest cogames-rl-researcher/tests/test_startup.py -q
uv run pytest cogames-rl-researcher/tests/test_resume.py -q
uv run pytest cogames-rl-researcher/tests/test_actor_critic.py -q
uv run pytest cogames-rl-researcher/tests/test_swarm.py -q
uv run pytest cogames-rl-researcher/tests/test_pickup.py -q
uv run pytest cogames-rl-researcher/tests/test_coverage.py -q
uv run pytest cogames-rl-researcher/tests/test_coverage_tuning.py -q
```
