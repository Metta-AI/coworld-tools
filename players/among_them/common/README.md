# among_them/common

Shared utilities used by more than one Among Them agent. Per the repo
[`MISSION.md`](../../MISSION.md) layout convention: `<game>/common/`
exists "only once it does", i.e. once two agents actually share code.
Don't speculatively grow this directory — extract here when a second
consumer appears, not before.

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

The `mb_*` symbols are exported with `{.exportc, dynlib.}` so they
can be consumed via FFI (which is how
[`modulabot/`](../modulabot/README.md) wires them into Python via
[`modulabot/nim_perception/lib.nim`](../modulabot/nim_perception/lib.nim)
+ a Python ctypes loader). They're equally usable as plain Nim
imports, which is how
[`guided_bot/`](../guided_bot/README.md) consumes them — see
[`guided_bot/perception/localize.nim`](../guided_bot/perception/localize.nim)'s
`from "../../common/perception_kernels/X" as kX import nil`.

### Consumers, current

- **modulabot** (`among_them/modulabot/`)
  - `modulabot/nim_perception/lib.nim` defines the modulabot-specific
    FFI surface (just an ABI-version stamp on top of the kernels).
  - `modulabot/nim_perception/build.py` builds the dylib, with
    `--path:` set to `among_them/common/perception_kernels`.
  - The kernels are parity-pinned by `modulabot/tests/test_nim_perception.py`
    against the numpy fallbacks in `modulabot/{sprite_match,localize,actors,ascii}.py`.
- **guided_bot** (`among_them/guided_bot/`)
  - `guided_bot/perception/localize.nim` imports the kernels via
    relative-path `from "../../common/perception_kernels/X"
    as kX import nil` (Phase 1.2).
  - Future phases (1.3 actors, 1.4 task icons, 1.5 OCR) will pull in
    `actors.nim` / `ocr.nim` the same way.

## Adding a new kernel

1. Add the `.nim` file under `perception_kernels/` (or a new
   subdirectory if it's a different concern).
2. Update modulabot's [`lib.nim`](../modulabot/nim_perception/lib.nim)
   to `import` and `export` the new module if it carries `mb_*`
   exports.
3. Bump `ABI_VERSION` in
   [`modulabot/nim_perception/build.py`](../modulabot/nim_perception/build.py)
   and `lib.nim`'s `ModulabotPerceptionAbiVersion` if the new symbols
   are part of the FFI ABI.
4. Add a numpy-fallback parity test in modulabot's test suite —
   shared kernels live here precisely so they have *one* parity story
   that protects every consumer.
5. If guided_bot wants to consume it, add the matching
   `from "../../common/perception_kernels/X" as kX import nil`.

## Adding new shared code (non-kernel)

Pick a sibling subdirectory next to `perception_kernels/`. Examples
that may eventually land here:

- `proto/` — shared Among Them wire-format helpers if both agents
  ever talk to the Nim server directly from Python.
- `traces/` — common trace-event schemas if the offline LLM-driven
  outer loop wants to consume both agents' traces.

Resist the urge to dump anything that looks vaguely shared into
`common/`. The bar is **at least two real consumers**.
