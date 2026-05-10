# among_them/common

Shared utilities used by more than one Among Them agent. Per the repo
[`MISSION.md`](../../MISSION.md) layout convention: `<game>/common/`
exists "only once it does", i.e. once two agents actually share code.
Don't speculatively grow this directory — extract here when a second
consumer appears, not before.

`../modulabot/` is now fully deprecated. It remains only as historical
reference and should not be inspected, modified, tested, or used as a
consumer when planning new work unless James explicitly asks for
modulabot. `../guided_bot/` is the active consumer of these kernels.

## Current contents

### `perception_kernels/`

Pure-Nim, stateless perception kernels. Every buffer is caller-allocated;
the kernels never own memory or carry state across calls.

| File | What it does |
|---|---|
| `sprite_match.nim` | Bulk all-anchors sprite matching (`mb_match_actor_sprite_all`) and per-anchor dominant-tint colour lookup (`mb_actor_color_index_all`). Includes the shared `PlayerColors` / `ShadowMap` palette tables. |
| `localize.nim` | Camera-fit scoring (`mb_score_camera`), 16×16 frame-patch hashing (`mb_hash_frame_patches`), and bulk patch-vote candidate collection (`mb_vote_camera_candidates`). |
| `actors.nim` | Task-icon scanning (`mb_scan_task_icons`). |
| `ocr.nim` | Variable-width pixel-font glyph picking (`mb_best_glyph`) and line-text matching (`mb_text_matches`). |

The `mb_*` symbols are exported with `{.exportc, dynlib.}` so they can
be consumed via FFI, but the active path is plain Nim imports from
[`guided_bot/`](../guided_bot/README.md) — see
[`guided_bot/perception/localize.nim`](../guided_bot/perception/localize.nim)'s
`from "../../common/perception_kernels/X" as kX import nil`.

### Consumers, current

- **guided_bot** (`among_them/guided_bot/`)
  - `guided_bot/perception/localize.nim` imports the kernels via
    relative-path `from "../../common/perception_kernels/X"
    as kX import nil` (Phase 1.2).
  - `guided_bot/perception/actors.nim`, `tasks.nim`, `ocr.nim`, and
    `voting.nim` consume the matching actor/task/OCR kernels.
- **modulabot** (`among_them/modulabot/`) is a legacy historical consumer
  only. Do not update its FFI, ABI, or parity tests unless James
  explicitly asks for modulabot work.

## Adding a new kernel

1. Add the `.nim` file under `perception_kernels/` (or a new
   subdirectory if it's a different concern).
2. Add or update guided_bot tests that exercise the active caller.
3. If guided_bot wants to consume it, add the matching
   `from "../../common/perception_kernels/X" as kX import nil`.
4. If James explicitly asks for modulabot compatibility, then update
   its legacy FFI/ABI surface and parity tests as part of that separate
   modulabot-scoped task.

## Adding new shared code (non-kernel)

Pick a sibling subdirectory next to `perception_kernels/`. Examples
that may eventually land here:

- `proto/` — shared Among Them wire-format helpers if both agents
  ever talk to the Nim server directly from Python.
- `traces/` — common trace-event schemas if the offline LLM-driven
  outer loop wants to consume both agents' traces.

Resist the urge to dump anything that looks vaguely shared into
`common/`. The bar is **at least two real active consumers** or a
clearly documented migration need.
