# HungerCog

Standalone home for the Hunger survival game.

This repo carries the game-specific code that used to live under the Metta monorepo:
- the HungerCog mission and variant graph,
- the built-in scripted policy,
- the tree-curriculum recipe surface used by Metta.

It depends on the shared `cogames` and `mettagrid` packages instead of keeping the game inside `metta`.

## Install

```bash
pip install -e .
```

To install the Metta stack needed for `metta play hungercog`, create a virtualenv and run:

```bash
./install.sh
```

That clones Metta `main` by default, syncs the active virtualenv against the cloned Metta lockfile with the
`hungercog` extra enabled, then overlays the current `hungercog` checkout editable. Set `METTA_REF` if you need a
different Metta branch. If no virtualenv is active, the script creates `.venv/` in this repo first. That makes the
standalone repo follow the same schema as other extracted games: standalone game packages are represented as optional
dependencies declared by `packages/cogames/pyproject.toml`.

From an existing Metta checkout on the matching branch, use the same optional game path directly:

```bash
metta install hungercog
```

## CLI

Run through the Metta CLI:

```bash
metta play hungercog render=none autostart=true seed=7
```

Run that command from the `HungerCog` checkout. This repo carries the `.repo-root` marker and `tools/run.py` entrypoint that the installed Metta CLI expects.

## Notes

The standalone package name and recipe surface are both `hungercog`, even though the game itself is the former in-tree Hunger game. Metta owns only the optional install metadata and in-tree deletion; this package owns the game logic and `play` / `train` recipe entrypoints.

## Template Upstream

This repo's history includes `Metta-AI/cogame` as a template parent. In a fresh clone, add the template remote before merging template updates:

```bash
git remote add upstream git@github.com:Metta-AI/cogame.git
git fetch upstream main
git merge upstream/main
```

Resolve only template changes that apply to HungerCog, then push to `origin`. Do not push to `upstream`.
