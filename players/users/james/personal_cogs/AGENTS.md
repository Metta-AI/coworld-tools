# AGENTS.md

Workshop repo for Softmax Alignment League Benchmark agents.

## Current Among Them Rule

Among Them is now Coworld-only in this checkout.

- Do not use local server scripts.
- Do not use legacy bundle upload helpers.
- Do not use hosted-play wrappers.
- Do not use deprecated historical bot directories.
- Do not run Coworld through a local Metta checkout for this project.

The intended command surface is:

```sh
uv run coworld ...
```

from the repo-local UV project under `among_them/`.

## Read First

For Among Them work, read:

1. `among_them/README.md`
2. `among_them/guided_bot/README.md`
3. `among_them/guided_bot/coworld/README.md`

`MISSION.md`, `COGAMES.md`, and `COGAMES_CLI.md` have been reset to reflect the
same Coworld-only direction.

## Layout

```text
among_them/
  README.md
  common/
  guided_bot/
    README.md
    coworld/
    perception/
      baked/        # checked-in assets consumed at runtime
    tools/          # offline asset bakers and inspectors (see below)
```

Execution belongs under Coworld. New runtime tooling should be added through
the repo-local UV project, not as ad hoc scripts.

## Offline Tools (`guided_bot/tools/`)

The `tools/` directory holds offline, developer-only utilities that produce or
inspect the checked-in artifacts under `guided_bot/perception/baked/`. They are
Coworld-compatible: they do not run the game, do not talk to a local server,
and do not implement an alternative run path. They are explicitly **exempt**
from the "Coworld-only" restriction below.

Current contents:

- `bake_assets.nim` / `bake_assets.sh` — bake `palette.bin`, `sprites.bin`,
  `map_pixels.bin`, `walk_mask.bin`, `wall_mask.bin`, `font.bin`, and `map.json`
  from an upstream bitworld checkout (`BITWORLD_DIR`).
- `bake_nav.py` — A* over `walk_mask.bin` to produce `nav_paths.bin` from
  `nav_graph.json`.
- `waypoint_editor.py` — pygame editor for `nav_graph.json` (waypoints and
  edges over the walk mask).
- `frame_viewer.py` — pygame viewer for `frames.bin` files recorded inside
  trace session directories.
- `frame_to_text.py` — converts recorded `frames.bin` frames to text grids for
  LLM-readable inspection.

These tools operate on already-recorded traces or on static upstream art
assets. They are not a frame-capture pipeline against a live game and must not
be conflated with the forbidden raw-capture run path.

## Validation Expectations

After implementation changes:

- run the narrowest useful static/unit checks available without reviving deleted
  run paths;
- validate end-to-end through Coworld via `uv run coworld ...`;
- inspect Coworld logs and stderr JSONL traces for runtime-sensitive behavior.

If a check cannot be run because the public PyPI dependency set is unavailable
or credentials are missing, say that explicitly in the handoff.

## Documentation Expectations

Keep runtime docs Coworld-only. Do not add instructions for local game servers,
live raw-frame-capture run paths, hosted-play shims, or legacy bundle upload
commands.

The offline utilities under `guided_bot/tools/` are not part of the runtime
surface and may be documented freely — including the frame viewer/text dumper,
which only reads already-recorded `frames.bin` files. Do not describe them as
runtime paths or as substitutes for `uv run coworld ...`.

Before committing, audit the docs touched by the session and update stale run
instructions in the same change.
