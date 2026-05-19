# Game Design

> **Status:** repository convention document. The canonical runtime contract for Coworld game
> containers lives in metta at `packages/coworld/src/coworld/GAME_RUNTIME_README.md`.

## Purpose

This repo is the implementation home for games. Unlike the role repos such as `reporters`,
`graders`, `diagnosers`, and `commissioners`, it is not an empty scaffold for one process-style role.
It is an aggregate of real game packages with different runtimes, languages, and migration states.

The job of this document is to state how `Metta-AI/games` should differ from those role repos while
still fitting the Coworld split.

## Repository contract

`Metta-AI/games` owns:

- Game source packages and runtime containers.
- Game assets, schemas, local servers, replay viewers, and game-specific docs.
- Coworld manifests when the game package is already container-first.
- Reusable game-authoring templates.
- Migration inventory for game packages moved from older standalone repos.

It does not own:

- General player/policy development. Use `Metta-AI/players`.
- Episode reports. Use `Metta-AI/reporters`.
- Grading implementations. Use `Metta-AI/graders`.
- Diagnostics implementations. Use `Metta-AI/diagnosers`.
- Round orchestration implementations. Use `Metta-AI/commissioners`.
- Coplayer UI/workbench code. Use `Metta-AI/optimizers` unless that repo is explicitly repurposed.

## Expected layout

```text
games/<game>/                 # One imported game package or Coworld runtime
templates/<template>/          # Reusable starting points for new games
docs/inventory.md              # Imported game list and provenance
docs/migration-plan.md         # Cross-repo migration plan
docs/COWORLD_REFERENCE.md      # Navigation guide into metta Coworld sources
docs/GAME_DESIGN.md            # This repo-level convention document
```

The repo should not mirror the role-repo placeholder shape of
`games/templates/game_template`, `games/among_them/among_them_game`, and so on. Games are larger
packages, not one-file role entrypoints.

## Per-game expectations

Each `games/<game>/` directory should converge toward these properties:

1. A clear package-local README.
2. A reproducible build or run command using the game's native toolchain.
3. A documented path to build the game container when it is Coworld-compatible.
4. A current `coworld_manifest.json` when the package is a Coworld game.
5. Short certification configs separate from production variants.
6. Tests or smoke commands that can run from this repo.
7. No required dependency on the legacy standalone source repo.

These are migration goals, not requirements for the initial import. Preserve behavior first.

## Runtime categories

The initial import intentionally keeps mixed runtime shapes:

| Runtime category | Repo treatment |
| --- | --- |
| Python / MettaGrid / CoGames | Include as root `uv` workspace members when self-contained. |
| Nim + Python wrapper | Keep native build/test commands inside the game directory. |
| JavaScript / TypeScript / Coworld | Keep package manager files inside the game directory. |
| Container-first Coworld examples | Keep local manifests and Dockerfiles package-local. |
| Templates | Keep under `templates/`, not `games/`. |

Do not collapse these into one shared build system until a game-specific migration proves it is safe.

## Coworld game obligations

When a game is Coworld-compatible, it should follow metta's game runtime contract:

- Read runtime config from `COGAME_CONFIG_URI`.
- Serve `GET /healthz`.
- Serve player and global viewer routes.
- Write results to `COGAME_RESULTS_URI`.
- Write replay data to `COGAME_SAVE_REPLAY_URI`.
- Support replay server mode through `COGAME_REPLAY_SERVER=1`.
- Validate results against the manifest `results_schema`.
- Keep protocol docs reachable from public HTTP(S) URLs before upload.

The exact contract belongs in metta. If the contract changes, update metta first and then refresh
[`docs/COWORLD_REFERENCE.md`](COWORLD_REFERENCE.md).

## Migration rules

- Keep migrations narrow and per-game.
- Do not delete or archive the old source repositories from this repo.
- Do not rewrite imported history or package layout just to make games look uniform.
- Move shared authoring guidance to `docs/` or `templates/`; avoid copying new shared docs into
  every game directory.
- Update downstream references in metta and `cogames` only after the corresponding game builds or
  certifies from this repo.

## Open follow-ups

1. Normalize current Coworld manifests to the latest metta schema.
2. Add a small smoke command table per imported game.
3. Decide when legacy standalone repos should become mirrors, archives, or stay active.
4. Decide whether each package should publish artifacts from this repo or only build images locally.
5. Add a new-game generator or tighten `templates/mettagrid-python` once one more game migrates cleanly.
