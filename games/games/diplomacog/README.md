# Diplomacog

Diplomacog is a standalone extraction of the discussion-first Diplomacy game from the Metta monorepo.

This repo contains the game package surface that should live with the game itself:

- the mission and variant graph
- the scripted baseline talk policy
- the CoGames registration and Metta play recipe bridge
- renderer assets and asset-generation scripts
- game-facing docs

Heavier `metta`-specific shipping layers, including audits, curriculum wiring, and tournament/training glue, stay upstream until they are split cleanly into `mettagrid` / `cogames`.

## Package

The Python package lives at `src/diplomacog`. It depends on `cogames` and `mettagrid`.

## Install

For local development against the matching Metta branch:

```bash
./install.sh
```

By default this clones `Metta-AI/metta` at `main`, installs the `diplomacog` extra into a local virtualenv, then overlays this checkout without re-resolving dependencies. Override `METTA_REF` or `METTA_REPO_URL` only when testing another branch or fork.

## Quick Start

Run a local rollout with the built-in scripted policy after installation:

```bash
metta play diplomacog render=none max_steps=8 cogs=6 seed=9
```

Or create an environment directly:

```python
from diplomacog import make_diplomacog_env
from mettagrid.policy.policy import PolicySpec
from mettagrid.runner.rollout import run_episode_local

env = make_diplomacog_env(num_agents=6, max_steps=40, variants=["discussion_sessions"])
results, _ = run_episode_local(
    policy_specs=[
        PolicySpec(class_path="diplomacog.agent.diplomacy_agent.policy.DiplomacyPolicy"),
    ],
    assignments=[0] * env.game.num_agents,
    env=env,
    seed=7,
    render_mode="none",
)
print(results.steps, results.rewards)
```

Run tests:

```bash
.venv/bin/python -m pytest -q
```

## Template Sync

Diplomacog shares git history with [`Metta-AI/cogame`](https://github.com/Metta-AI/cogame), the standalone game template. This keeps shared docs, skills, and repo guidance mergeable from the template while Diplomacog owns its game code under `src/diplomacog`.

To pull future template updates into a local clone:

```bash
git remote add cogame git@github.com:Metta-AI/cogame.git  # if missing
git fetch cogame
git merge cogame/main
```

Resolve conflicts toward the Diplomacog package, assets, and tests. Do not push to `Metta-AI/cogame` from this repo.

## Assets

Diplomacy-specific MettaScope art lives under `assets/mettascope/diplomacy`. The asset-generation scripts are copied here unchanged except for repo-local path wiring, so future renderer work can move independently of the monorepo.

## Game-Authoring Guidance

The template game-authoring skills live in [`skills/`](skills/), with `.claude/skills` and `.codex/skills` symlinked to that directory. Start with [`skills/cg.game.new-game/SKILL.md`](skills/cg.game.new-game/SKILL.md) for new game mechanics work.
