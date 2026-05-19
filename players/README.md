# players

Single-source repository for the development and internal publication of
players for [Coworld](https://github.com/Metta-AI/metta/tree/main/packages/coworld)
games. Players developed here are intended to be the canonical, shareable
players used across the Softmax Coworld system — uploadable with the
`coworld` CLI, submittable to leagues, and bundleable into game manifests.

The repo contains four things:

1. **Concrete players for Coworld games** — under `players/`, organized
   one subdirectory per target game. Each player ideally builds into a
   Coworld-compatible Docker image that can be uploaded via
   `coworld upload-policy` and either `coworld submit`-ted to a league or
   bundled into a game's `coworld_manifest.json`. See
   [docs/coworld-player-packaging.md](docs/coworld-player-packaging.md)
   for the build/packaging contract every player is expected to satisfy.
2. **The Coborg agent framework** — under `src/players_lib/coborg/`.
   The intended framework and starter template for future agent
   development in this repo. New policies should prefer Coborg over
   ad-hoc scaffolding.
3. **Cogbase** — under `tools/cogbase/`. A standalone meta-pipeline
   toolkit whose goal is to accelerate, and ultimately automate, the
   generation of initial starter policies (game guides, perception,
   action, packaging) for new Coworld games. Ships its own
   `pyproject.toml` and is not part of the `players` distribution.
4. **Documentation** — workspace-level docs under `docs/`, plus
   tool-specific docs that live next to their tool (e.g.
   `tools/cogbase/docs/`).

## Layout

```
players/             # Concrete players, one subdir per Coworld game
  among_them/        #   BitWorld "Among Them"
  cogsguard/         #   Cogs vs Clips
  paintarena/        #   Paint Arena (reserved)
  infinite_blocks/   #   Infinite Blocks (reserved)
src/players_lib/     # Importable shared library package (`players_lib`)
  coborg/            #   Coborg agent framework
  eval/              #   Eval/metric helpers reused across players
tools/cogbase/       # Standalone Cogbase toolkit (own pyproject)
users/               # Contributor-owned active projects (incubation)
validation/          # Repo-wide pytest suite
docs/                # Workspace-level documentation
```

The `players/` tree is flat: one directory per game, then one directory
per concrete policy inside that game. The single explicit exception to
per-policy self-containment is `players/cogsguard/_shared/`, which holds
helpers used by multiple Cogsguard policies.

## Python packages

This repo's `pyproject.toml` declares one distribution, `players`, that
installs two top-level importable packages. The distribution exists for
local development (`uv sync`, `pip install -e .`, test imports) rather
than for PyPI publication.

- `players_lib` (from `src/players_lib/`): the Coborg framework plus
  importable eval/tooling helpers.
- `players` (from the top-level `players/` tree): concrete importable
  game players.

`tools/cogbase/` is a separate distribution with its own
`pyproject.toml` and is not pulled in by installing `players`.

## Working Rules

- Put reusable agent framework code under `src/players_lib/coborg/`
  (and any future frameworks as siblings under `src/players_lib/`).
- Put importable eval/tooling helpers under `src/players_lib/eval/`.
- Put concrete importable policies under `players/<game>/<policy>/`.
- Keep `tools/cogbase/` standalone; do not import it from
  `players_lib` or `players`.
- Keep active personal projects under `users/<handle>/<project>` until
  they are intentionally promoted into the shared `players/` tree.
- Keep policy-language sources next to the policy that owns them (Nim,
  Python, etc.).
- Keep game/runtime package code in its owning repo unless the file is
  genuinely policy source.
