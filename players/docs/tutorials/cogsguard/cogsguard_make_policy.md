# CoGsGuard Tutorial: make-policy

This notebook walks through the scripted policy generator: `--scripted`, with the CoGsGuard `arena` mission as the
target mission.

## Prerequisites

- Run from the repo root with your virtual environment activated.
- If `cogames` is not found, activate `.venv` and retry.

## Note

Trainable tutorial coming later. For now, this tutorial focuses on the scripted policy flow.

## CogsGuard context

The built-in CoGsGuard scripted baselines live at
`src/agent_policies/policies/scripted/cogsguard/scripted_agent/cogsguard/`. Use them as references when you want
richer role logic or navigation beyond the template generated below.

## Check the CLI (optional)

Use these commands to confirm the tutorial entrypoints and available missions:

```bash
cogames tutorial make-policy --help
cogames play --help
```

## Step 1 — Scripted policy template

The scripted template is a rule-based policy you can edit by hand. It runs immediately with `cogames play` and does not
require training.

```bash
cogames tutorial make-policy --scripted -o my_scripted_policy.py
```

Expected output (example):

```
Scripted policy template copied to: /path/to/your/project/my_scripted_policy.py
Play with: cogames play -m arena -p class=my_scripted_policy.StarterPolicy
```

Note: Replace `/path/to/your/project/` with your local repo path.

Common pitfalls:

- These commands overwrite existing files; use `-o` to choose a new filename.

Run the scripted policy (no training required):

```bash
cogames play -m arena -p class=my_scripted_policy.StarterPolicy
```

This opens the GUI by default.

### Alternative: recipe runner (advanced)

If you want to run via the recipe runner, use:

```bash
./tools/run.py recipes.experiment.cogsguard.play \
  policy_uri=metta://policy/role render=gui max_steps=1000
```

This uses the built-in scripted role policy (not your generated file). Beginners can skip this.

Expected terminal output (example):

```
Playing arena
Max Steps: 1000, Render: gui
Initializing Mettascope...
Episode Complete!
Steps: <N>
Total Rewards: [<value>]
Final Reward Sum: <value>
```

Common pitfalls:

- These commands overwrite existing files; use `-o` to choose a new filename.

## Step 2 — Customize your own policy

## Summary

- **Scripted** = rule-based, runs immediately without training.

## What to do next

- **Scripted**: run the `cogames play ...` command printed by the CLI.
