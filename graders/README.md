# graders

Grader implementations for Coworld supporting runnables.

> **Status:** Coworld role repo under construction. The Coworld grader role is still `reserved`, but the current
> tentative contract is documented in `~/coding/metta/packages/coworld/src/coworld/docs/roles/grader.md`.

## What Is A Coworld Grader?

A Coworld is a Softmax v2 tournament unit: one game container, one or more player containers, a Coworld manifest,
and supporting role runnables. A grader is a post-episode, on-demand supporting runnable declared under
`manifest.grader[]`.

The current tentative grader contract is:

- read an episode bundle zip from `COGAME_EPISODE_BUNDLE_URI`;
- inspect the bundle's `manifest.json` to find `results.json` and any other needed artifacts;
- write one JSON grade file to `COGAME_GRADE_URI`;
- include a required `score` and, by convention, a `grader_id`.

The episode runner does not automatically launch graders. Grader invocation is owned by future CLI, hosted UI, or
pipeline surfaces.

## Repository Layout

```text
graders/
|-- CATALOG.yaml
|-- README.md
|-- pyproject.toml
|-- docs/
|   |-- COWORLD_REFERENCE.md
|   `-- GRADER_DESIGN.md
`-- graders/
    |-- default/
    |   `-- default_grader/
    |-- among_them/
    |   `-- among_them_grader/
    |-- paint_arena/
    |   `-- paint_arena_grader/
    `-- cogs_v_clips/
        `-- cogs_v_clips_grader/
```

`CATALOG.yaml` is the repo-level implementation index. Source on disk without a catalog entry is not a published
implementation.

## Status Of Each Grader

| Grader | Coworld | Status |
| --- | --- | --- |
| `default/default_grader` | Default / generic | Starter implementation; cataloged |
| `among_them/among_them_grader` | Among Them | Starter implementation; cataloged |
| `paint_arena/paint_arena_grader` | PaintArena | Starter implementation; cataloged |
| `cogs_v_clips/cogs_v_clips_grader` | Cogs vs Clips | Starter implementation; cataloged |
| `bitworld_score/bitworld_score_grader` | Generic BitWorld score games | Starter implementation; cataloged |
| `crewrift/crewrift_grader` | Crewrift | Starter implementation; cataloged |
| `mettagrid/mettagrid_score_grader` | Generic MettaGrid score games | Starter implementation; cataloged |
| `liarliar/liarliar_grader` | Liar Liar | Starter implementation; cataloged |
| `persephones_escape/persephones_escape_grader` | Persephone's Escape | Starter implementation; cataloged |
| `tribal_cog/tribal_cog_grader` | Tribal Cog / Tribal Fortress | Starter implementation; cataloged |

## Authoritative Coworld Sources

Treat the Metta checkout as the source of truth:

- `~/coding/metta/packages/coworld/src/coworld/docs/roles/grader.md` - grader role contract.
- `~/coding/metta/packages/coworld/src/coworld/docs/roles/OVERVIEW.md` - role composition and artifact flow.
- `~/coding/metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md` - bundle format consumed by graders.
- `~/coding/metta/packages/coworld/src/coworld/MANIFEST_README.md` - manifest field reference.
- `~/coding/metta/packages/coworld/src/coworld/coworld_manifest_schema.json` - generated manifest schema.
- `~/coding/metta/docs/specs/0045-coworld-role-repos.md` - role-repo layout and `CATALOG.yaml` schema.

This repo should not invent a different grader runtime contract. If the Coworld docs change, update the implementation
and these docs together.

## Development

Run focused tests:

```bash
python3 -m unittest discover -s tests
```

Build a starter image:

```bash
cd graders/default/default_grader
./build.sh

cd graders/among_them/among_them_grader
./build.sh

cd graders/paint_arena/paint_arena_grader
./build.sh

cd graders/cogs_v_clips/cogs_v_clips_grader
./build.sh

cd graders/bitworld_score/bitworld_score_grader
./build.sh

cd graders/crewrift/crewrift_grader
./build.sh

cd graders/mettagrid/mettagrid_score_grader
./build.sh

cd graders/liarliar/liarliar_grader
./build.sh

cd graders/persephones_escape/persephones_escape_grader
./build.sh

cd graders/tribal_cog/tribal_cog_grader
./build.sh
```

Each build defaults to the cataloged local image name for `linux/amd64`.
