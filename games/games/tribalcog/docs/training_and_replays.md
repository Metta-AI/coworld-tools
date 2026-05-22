# Training and Replay Integration Notes

Date: 2026-05-22
Owner: Docs / ML Systems
Status: Active

## Purpose
Codex sessions frequently revisit training wiring, metta integration, and replay
support. This doc summarizes the current training flow and the replay writer
hooks that exist today.

## Training entry points
CLI (training subcommand, requires the `cogames` extra):
- `pip install -e .[cogames]`
- `tribalcog train --steps 1000000 --parallel-envs 8 --num-workers 4 --log-outputs`

Root `Metta-AI/games` workspace:
- `uv run --package tribalcog --extra cogames tribalcog train --steps 1000000 --parallel-envs 8 --num-workers 4 --log-outputs`

CoGames CLI (optional):
- `cogames train-tribal -p class=tribal --steps 1000000 --parallel-envs 8 --num-workers 4 --log-outputs`

Key files:
- `tribal_village_env/cli.py` (CLI wiring)
- `tribal_village_env/cogames/cli.py`
- `tribal_village_env/cogames/train.py`
- `tribal_village_env/environment.py`

### Defaults (check CLI for current values)
- Checkpoints: `./train_dir`
- Render mode: `ansi` (train-only)
- Episode length: 1000 steps

## Packaging notes
- The repo is a standalone, installable Python package (pyproject-based).
- The training CLI expects the native lib to be available
  (`tribal_village_env/libtribal_village.*`).
- If training from a Metta checkout, avoid older copies of `tribalcog` to
  prevent conflicts in import resolution. The intended optional-package source
  for new Metta/CoGames metadata is `https://github.com/Metta-AI/games.git`
  with subdirectory `games/tribalcog`.
- PufferLib vs pufferlib-core mismatches have caused issues in past sessions;
  prefer the versions pinned in the workspace you are running.

## Replay writer (Nim)
Replay output is supported in Nim via `src/replay_writer.nim` (ReplayVersion = 3).
It is opt-in and controlled by environment variables:
- `TV_REPLAY_DIR` : directory for replay files
- `TV_REPLAY_PATH` : explicit replay file path (overrides dir)
- `TV_REPLAY_NAME` : base name (default `tribal_village`)
- `TV_REPLAY_LABEL` : label metadata

Replays are written as compressed JSON: `*.json.z`.

To enable during a run:
1. Export `TV_REPLAY_DIR` (or `TV_REPLAY_PATH`).
2. Run `tribalcog play` (or `nim r -d:release --path:src tribal_village.nim`).
3. Verify output in the chosen directory.

This replay writer is the native Tribal Cog replay path. It is not the same
thing as hosted Coworld replay serving. A future Coworld runtime would still
need to read `COGAME_SAVE_REPLAY_URI` in rollout mode and serve
`/clients/replay?uri=...` when `COGAME_REPLAY_SERVER=1`.

## Common training issues seen in sessions
- "SPS = 0" or no logs: check PufferLib versions and vector env wiring.
- CLI confusion when `tribalcog train` is missing: install the `cogames`
  extra.
- Metta symlink setups can import the wrong package if an old copy exists.

## Suggested follow-ups
- Wire replay output into the Python training pipeline (set `TV_REPLAY_DIR` in
  train wrappers when desired).
- Add a README snippet whenever the training entry point changes.
