# Scripted Baselines How-To

This runbook is the canonical "how to run it" guide for CogsGuard scripted teammates.

## Canonical Policies

- Use `metta://policy/role` for scripted base roles and adaptive `gear` behavior.
- Use `role_order=...` for static specialists (`miner`, `scout`, `aligner`, `scrambler`).
- Keep `cogames` tutorial role wrappers (`miner`, `scout`, `aligner`, `scrambler`) for tutorial/demo use only.

## Quick Start

```bash
# 1) Static scripted team with smart defaults
uv run ./tools/run.py recipes.experiment.cogsguard.play \
  policy_uri=metta://policy/role \
  render=log \
  max_steps=200

# 2) Adaptive gap-filler team (all agents start in gear mode)
uv run ./tools/run.py recipes.experiment.cogsguard.play \
  'policy_uri=metta://policy/role?gear=8' \
  render=log \
  max_steps=200

# 3) Fixed static role specialist (single-role behavior)
uv run ./tools/run.py recipes.experiment.cogsguard.play \
  'policy_uri=metta://policy/role?role_order=miner' \
  render=log \
  max_steps=200
```

## Mixed-Team Runs

```bash
# 50/50 scripted + random mixture
uv run ./tools/run.py recipes.experiment.cogsguard.play \
  'policy_uris=["metta://policy/role","metta://policy/random"]' \
  'proportions=[0.5,0.5]' \
  render=log \
  max_steps=200
```

## One-Command Thread Vision Artifact Bundle

```bash
uv run python cogames-agents/scripts/run_scripted_baselines_report.py \
  --output-dir outputs/scripted_baselines \
  --seeds 11,23,42 \
  --no-enforce-gates
```

Outputs:

- `outputs/scripted_baselines/scripted_baselines_report.json`
- `outputs/scripted_baselines/scripted_baselines_report.html`

## Instrumented Diagnostics

```bash
# Role/resource trace audit
uv run cogames-agents/scripts/run_cogsguard_instrumented_audit.py \
  --steps 200 \
  --agents 4 \
  --policy-uri 'metta://policy/role?gear=4'

# Sanity rollout with role/prereq checks
uv run cogames-agents/scripts/run_cogsguard_rollout.py \
  --steps 200 \
  --agents 4 \
  --policy-uri 'metta://policy/role?gear=4' \
  --trace-roles \
  --trace-prereqs
```

## Tests

```bash
uv run pytest -q \
  cogames-agents/tests/test_cogsguard_determinism.py \
  cogames-agents/tests/test_cogsguard_guardrails.py \
  cogames-agents/tests/test_rollout_trace.py
```
