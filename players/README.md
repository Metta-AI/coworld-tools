# players

Single-source repository for the development and internal publication of
players for [Coworld](https://github.com/Metta-AI/metta/tree/main/packages/coworld)
games. Players developed here are intended to be the canonical, shareable
players used across the Softmax Coworld system — uploadable with the
`coworld` CLI, submittable to leagues, and bundleable into game manifests.

> **Status:** shared player source inside `Metta-AI/coworld-tools`. The old `Metta-AI/players` repo is archived. Keep
> reusable policies and player SDK work here. Keep bundled starter players or game-coupled policy code in the owning
> `Metta-AI/coworld-<slug>` repo until they are intentionally promoted into this shared tree.

The repo contains four things:

1. **Concrete players for Coworld games** — under `players/`, organized
   one subdirectory per target game. Each player ideally builds into a
   Coworld-compatible Docker image that can be uploaded via
   `coworld upload-policy` and either `coworld submit`-ted to a league or
   bundled into a game's `coworld_manifest.json`.
2. **The Coworld Player SDK** — under `players/player_sdk/`. The
   importable two-loop (strategy/reflex) agent framework (formerly
   known as Coborg) and starter template for future agent development
   in this repo. New policies should prefer the Player SDK over ad-hoc
   scaffolding.
3. **Cogbase** — under `tools/cogbase/`. A standalone meta-pipeline
   toolkit whose goal is to accelerate, and ultimately automate, the
   generation of initial starter policies (game guides, perception,
   action, packaging) for new Coworld games. Ships its own
   `pyproject.toml` and is not part of the `players` distribution.
4. **Documentation** — workspace-level docs under [`docs/`](docs/README.md)
   (start with the [Coworld Integration Guide](docs/coworld-integration-guide.md)
   and the [Coworld Player Packaging Contract](docs/coworld-player-packaging.md)),
   plus tool-specific docs that live next to their tool (e.g.
   `tools/cogbase/docs/`).

## Layout

```
players/             # Concrete players plus the shared SDK
  cogsguard/         #   Cogs vs Clips
  paintarena/        #   Paint Arena (reserved)
  infinite_blocks/   #   Infinite Blocks (reserved)
  player_sdk/        #   Coworld Player SDK (two-loop agent framework)
tools/cogbase/       # Standalone Cogbase toolkit (own pyproject)
users/               # Contributor-owned active projects (incubation)
validation/          # Repo-wide pytest suite
docs/                # Workspace-level documentation
```

The `players/` tree is flat: one directory per game, then one directory
per concrete policy inside that game. The single explicit exception to
per-policy self-containment is `players/cogsguard/_shared/`, which holds
helpers used by multiple Cogsguard policies, including policy-facing semantic
prompt and planner support layered on the public `cogsguard.semantic` game
surface.

## Documentation

System-level knowledge — what a player must do at runtime, how it is
packaged, and how the broader Coworld system reaches it — lives under
[`docs/`](docs/README.md):

- [Coworld Integration Guide](docs/coworld-integration-guide.md) —
  developer-facing reference for the player runtime: episode lifecycle,
  environment variables the runner injects, websocket-protocol
  expectations, log/replay visibility, and the `coworld` CLI commands
  used to debug a hosted episode. Start here when building a new
  player.
- [Coworld Player Packaging Contract](docs/coworld-player-packaging.md) —
  authoritative reference for what every
  `players/<game>/<policy>/build.sh` must produce (Docker image,
  `player[]` manifest snippet, `coplayer_manifest.json`) and the
  underlying Coworld upload/manifest requirements.

Per-player implementation notes live with each player under
`players/<game>/<policy>/` (typically `README.md` and, where relevant,
`PLAN.md`). Tool-specific docs (e.g. Cogbase) live next to their tool,
indexed from that tool's own README.

## Python packages

This repo's `pyproject.toml` declares one distribution, `players`, that
installs the top-level `players` package — game subpackages plus the
shared `players.player_sdk`. The distribution exists for local
development (`uv sync`, `pip install -e .`, test imports) rather than
for PyPI publication.

`tools/cogbase/` is a separate distribution with its own
`pyproject.toml` and is not pulled in by installing `players`.

## Working Rules

- Put reusable agent framework code under `players/player_sdk/`.
- Put concrete importable policies under `players/<game>/<policy>/`.
- Put game-specific eval/tooling helpers under
  `players/<game>/` (e.g. `players/cogsguard/eval_result_metrics.py`,
  `players/cogsguard/evals/`).
- Keep `tools/cogbase/` standalone; do not import it from `players`.
- Keep active personal projects under `users/<handle>/<project>` until
  they are intentionally promoted into the shared `players/` tree.
- Keep policy-language sources next to the policy that owns them (Nim,
  Python, etc.).
- Keep game/runtime package code in its owning repo unless the file is
  genuinely policy source.
