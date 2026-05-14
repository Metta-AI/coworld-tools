# modulabot/nim_perception/

> **Deprecated / historical only.** This directory belongs to the local
> modulabot, which is no longer active. Do not inspect, modify, rebuild,
> test, or use it unless James explicitly asks for modulabot work. Active
> perception-kernel work belongs in `../../common/perception_kernels/`
> and active bot work belongs in `../../guided_bot/`.

Native Nim perception kernels loaded into Python via `ctypes`. Every
hot-path pixel kernel has a parity-pinned numpy fallback in the
corresponding `modulabot/*.py` module, so `MODULABOT_DISABLE_NATIVE=1`
rolls the whole thing back with zero code changes.

Full design and phase-by-phase perf results live in
`modulabot/PERCEPTION_PERF_PLAN.md`.

## Layout

```
nim_perception/
├── lib.nim              # FFI surface; imports+re-exports src/*.nim
├── build.py             # nim c runner, source-hash gated rebuild
├── __init__.py          # ctypes loader + numpy-aware wrappers
├── src/
│   ├── sprite_match.nim # Phase 1: match_actor_sprite, actor_color_index
│   ├── localize.nim     # Phase 2 + 2.5: score_camera, hash_frame_patches,
│   │                    #                 vote_camera_candidates (bulk)
│   ├── actors.nim       # Phase 3: scan_task_icons
│   └── ocr.nim          # Phase 4: best_glyph, text_matches
├── nimcache/            # Nim build artifacts (never committed)
├── libmodulabot_perception.dylib         # built library (never committed)
└── libmodulabot_perception.dylib.sources # source-hash sidecar
```

## Rebuilding

The library rebuilds automatically on first import if its sources have
changed (tracked via SHA256 of `lib.nim` + every `src/*.nim` + the ABI
version). To force a rebuild:

```bash
# Direct invocation (clean output):
PYTHONPATH=among_them .venv/bin/python \
    among_them/modulabot/nim_perception/build.py --force

# Or via -m (emits a cosmetic RuntimeWarning about sys.modules —
# harmless, see build.py main-block comment for why):
PYTHONPATH=among_them .venv/bin/python \
    -m modulabot.nim_perception.build --force
```

Typical build time: ~500 ms with `-d:release --opt:speed`.

## Adding a new FFI entry point

1. Add the proc in the relevant `src/*.nim` with `{.exportc, dynlib.}`.
   Use `ptr UncheckedArray[T]` for buffer args; never allocate in the
   hot path.
2. Update `lib.nim`'s imports and **bump `ModulabotPerceptionAbiVersion`
   by one**. The ABI version catches stale `.dylib` + source pairs at
   load time.
3. Update `build.py::ABI_VERSION` to match.
4. In `__init__.py::_bind`, declare `restype` + `argtypes` for the new
   symbol.
5. Write a Python wrapper in `__init__.py` that takes numpy arrays,
   casts to ctypes pointers, and returns friendly Python types.
6. Add the Python dispatcher in the matching `modulabot/*.py` module —
   check `_nim_perception.HAVE_NATIVE` and fall through to the numpy
   kernel when False. Rename the existing numpy kernel with a leading
   underscore to mark it as private / fallback-only.
7. Add a parity test in `tests/test_nim_perception.py` that sweeps
   the 275-frame fixture (or synthetic inputs for OCR) and asserts
   byte-identical output between Nim and numpy paths.

## Debugging a parity failure

1. Run `python -m unittest modulabot.tests.test_nim_perception -v` to
   narrow down which kernel diverged.
2. Pick a single failing fixture frame and instrument both paths to
   dump intermediate state (e.g. miss counts per sprite pixel, hash
   values per patch).
3. Set `MODULABOT_DISABLE_NATIVE=1` to confirm the numpy path still
   produces the expected output — if it doesn't, the bug is in Python.
4. If both match but disagree with older snapshots, regenerate the
   snapshot only after auditing the change.

Common sources of drift:

- **Integer overflow.** Nim `uint64` wraps silently; numpy does too
  (we cast to `np.uint64`). Any intermediate `int` / `int32` math
  in Nim will trap differently than numpy's silent wrap.
- **Early-exit sentinels.** Returning a miss count equal to
  `max_errors + 1` as a "budget exceeded" sentinel must be distinct
  from a real "exceeded by one" count. See `ocr.nim::scoreGlyph` for
  the canonical workaround (use `budget + 1` as the strict sentinel).
- **Tie-break ordering.** numpy's `argmin` / `argmax` pick lowest
  index on ties; any Nim routine that depends on order must match
  this explicitly.

## Requirements

- Nim 2.2.4 on `PATH` (upstream `~/coding/bitworld` uses nimby to
  manage this; any equivalent install works).
- A C compiler (Nim backend). macOS: Xcode command-line tools.
  Linux: gcc or clang.
- numpy (already a modulabot dependency).
- Python 3.10+ for the modern type-hint syntax used in the wrappers.
