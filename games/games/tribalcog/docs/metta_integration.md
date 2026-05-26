# Metta Integration

Date: 2026-05-22
Owner: Docs / Game Integration
Status: Active

This page explains how Tribal Cog fits the current `Metta-AI/games`, CoGames,
Metta recipe, and Coworld conventions.

## Source of Truth

Tribal Cog lives in `Metta-AI/games` under `games/tribalcog`.

The standalone package shape is intentional:

- Nim simulation, renderer, assets, and native tests live in `src/`, `data/`,
  `tests/`, and `tribal_village.nim`.
- The Python wrapper and CLI live in `tribal_village_env/`.
- The package entry point is `tribalcog`.
- The Metta recipe bridge is `tribal_village_env.recipe`.

Do not reshape Tribal Cog into a role-repo scaffold. General player policies
belong in `Metta-AI/players`; game runtime code belongs here.

## Local Run Surfaces

From this package directory:

```bash
pip install -e .
tribalcog play
tribalcog play --render ansi --steps 128
```

From the root `Metta-AI/games` workspace:

```bash
uv run --package tribalcog tribalcog play --render ansi --steps 128
```

The direct Nim GUI path is still useful when debugging native rendering or
compile-time flags:

```bash
nim r -d:release --path:src tribal_village.nim
```

`tribalcog play` builds or reuses the native GUI binary for normal GUI mode.
When profiling, step timing, or render timing flags are enabled, the CLI invokes
Nim directly with the matching compile-time defines.

## Metta Recipe Surface

Metta exposes Tribal Cog as a game recipe:

```bash
metta play tribalcog max_steps=128
```

The recipe mirrors the standalone CLI instead of duplicating game logic. It
shells out to the `tribalcog play` command, rejects `policy_uri`, `num_agents`,
and `cogs` overrides, and keeps Tribal Cog's fixed native agent count. The
default recipe render mode is `none`, which maps to ANSI rendering for a quiet
smoke run.

When updating Metta or CoGames optional package metadata, point Tribal Cog at
this repository:

```toml
tribalcog = { git = "https://github.com/Metta-AI/games.git", subdirectory = "games/tribalcog" }
```

The import module for optional loading is:

```text
tribal_village_env.recipe
```

## CoGames Training

Training is package-local and optional:

```bash
pip install -e .[cogames]
tribalcog train --steps 1000000 --parallel-envs 8 --num-workers 4 --log-outputs
```

If Tribal Cog is installed through CoGames optional loading, the training code
still resolves to this package's `tribal_village_env/cogames/` modules.

## Coworld Status

Tribal Cog now has a Coworld runtime in this repository:

- `coworld_manifest.json` declares the hosted game, player image, docs,
  variants, and certification fixture.
- `Dockerfile` builds the game runtime image and serves the Coworld routes.
- `player/Dockerfile` builds the lightweight reference player image.
- `tribal_village_env/coworld/server.py` owns the game server.
- `tribal_village_env/coworld/player.py` owns the bundled town-overseer player.

The implementation follows the canonical Metta Coworld game runtime contract:

- Read concrete episode config from `COGAME_CONFIG_URI`.
- Serve `GET /healthz` on `0.0.0.0:8080`.
- Serve player and global viewer clients and websockets.
- Validate player slot tokens injected by the runner.
- Write final results to `COGAME_RESULTS_URI`.
- Write replay artifacts to `COGAME_SAVE_REPLAY_URI`.
- Serve replay mode when `COGAME_REPLAY_SERVER=1` is set.

The Coworld controller shape is town-scoped: it exposes 8 player slots, one per
team/town. The simulation still runs 125 citizens per team plus 6 game-owned
goblin/NPC agents. Human or LLM controllers edit building program templates;
citizens snapshot those templates when they transform through a building and
then continue under compiled Nim policies. Unconnected towns keep using the
built-in default policies.

The manifest describes the game container, config schema, results schema,
protocol docs, variants, certification fixture, `rules.md`, and
`play_tribalcog.md`.

Do not treat local docs as proof that a live Coworld upload has the same docs.
For hosted leagues, verify the uploaded Coworld manifest or Observatory row
before saying the live game is updated.

## Defaults to Keep Straight

There are two valid runtime defaults:

- Direct Nim runtime: `defaultEnvironmentConfig()` starts with `maxSteps=3000`
  and `VictoryAll`.
- Python wrapper: `EnvironmentConfig()` starts with `max_steps=10000` and
  `victory_condition=0` (`VictoryNone`) before sending the config through FFI.

Use explicit `max_steps` and `victory_condition` in tests, training jobs, and
public examples when the difference matters.

## Validation

For docs-only changes, run at least the package import or CLI help if the change
touches commands. For code or contract changes, use the package validation
sequence:

```bash
make check
gtimeout 15s nim r -d:release --path:src tribal_village.nim
make test-nim
```

On Linux, use `timeout` instead of `gtimeout`.

For Coworld contract checks from a Metta checkout, use:

```bash
uv run --package coworld coworld certify /Users/relh/Code/games/games/tribalcog/coworld_manifest.json
```

The checked-in hosted manifest is fixed at 8 town slots because current Coworld
manifest validation requires `tokens.minItems == tokens.maxItems` and
`certification.players` must match that count. Local runtime smoke tests can
start with fewer connected controllers; the remaining towns use default
compiled policies.
