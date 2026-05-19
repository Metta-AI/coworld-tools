# Overcogged

Standalone home for the Overcogged kitchen-coordination game.

This repo carries the game-specific code that used to live under the Metta monorepo:
- the canonical `basic` kitchen mission,
- the preserved `classic` mission,
- the Overcogged variant graph,
- the built-in scripted policy.

It depends on the shared `mettagrid` package and integrates with `cogames` through optional install paths instead of
vendoring the whole Metta stack.

This repository is based on the [`Metta-AI/cogame`](https://github.com/Metta-AI/cogame) standalone game template. The
template docs and game-authoring skills live under [`docs/`](docs/) and [`skills/`](skills/) so future template updates
can be merged into this repo.

## Install

```bash
pip install -e ".[standalone]"
```

For the canonical Metta install path, use:

```bash
pip install "cogames[overcogged]"
```

Use the `standalone` extra when installing this repo directly so the CLI, policy parsing, and local play surface pull
in `cogames`.

To install the branch-pinned stack needed for `metta play overcogged`, create a virtualenv and run:

```bash
./install.sh
```

Run that from the `overcogged` branch checkout you want to use. `install.sh` defaults to `METTA_REF=main`, clones that editable `metta` branch, then layers the current `overcogged` checkout on top without re-resolving dependencies. That keeps the `cogames`/`mettagrid` package set chosen by the Metta install and makes `metta play overcogged` resolve the standalone package instead of an in-tree copy.

Override `METTA_REF` or `METTA_REPO_URL` only if you intentionally want a different branch or fork.

## Quick Start

Headless scripted rollout:

```bash
overcogged play --render none --autostart --seed 7
```

Watch the kitchen in a GUI:

```bash
overcogged play --render gui --autostart --seed 7
```

Play the preserved classic mission:

```bash
overcogged play --mission classic --cogs 2 --render none --autostart --seed 7
```

Run a harder kitchen variant:

```bash
overcogged play --variant hard --variant tight_hub --render none --autostart --seed 7
```

## CLI

Run through the Metta CLI:

```bash
metta play overcogged render=none autostart=true seed=7
```

Run that command from the `overcogged` checkout. This repo now carries the `.repo-root` marker and `tools/run.py` entrypoint that the installed Metta CLI expects.

List missions:

```bash
overcogged missions
```

List variants:

```bash
overcogged variants
```

Override the policy explicitly:

```bash
overcogged play \
  --policy class=overcogged.agent.overcogged_agent.policy.OvercookedPolicy \
  --render none \
  --autostart
```

## Layout

`src/overcogged/`
: standalone game package

`src/overcogged/game/`
: canonical kitchen mission and CoGame registration

`src/overcogged/classic/`
: preserved original classic mission

`src/overcogged/variants/`
: launch and curriculum variant graph

`src/overcogged/agent/overcogged_agent/`
: built-in scripted policy

## Notes

Overcogged is intended to be the standalone source of truth. The Metta monorepo should only carry the optional install
contract and shared engine / renderer support needed to launch it.
