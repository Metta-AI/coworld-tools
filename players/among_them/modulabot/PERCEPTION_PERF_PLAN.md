# Perception performance plan — moving modulabot pixel work to native code

> **Status (2026-04-30):** Phases 0–4 complete. All headline wins landed.
>
> Results summary:
>
> | Stage                            | Baseline   | After Phases 0–4 | Speedup |
> | -------------------------------- | ---------- | ---------------- | ------- |
> | `actors.scan_all` p50            | 8 587 µs   | 2 516 µs         | 3.4×    |
> | `localize.update_location` cold  | 4 690 µs   | 910 µs           | 5.2×    |
> | `localize.update_location` warm  | 32 µs      | 29 µs            | 1.1×    |
> | `voting.parse_voting_screen` chat| 24 903 µs  | 8 573 µs         | 2.9×    |
> | `BotCore.step` (playing) p50     | 9 003 µs   | 2 645 µs         | 3.4×    |
> | `BotCore.step` (playing) p99     | 11 607 µs  | 5 414 µs         | 2.1×    |
> | `BotCore.step` (playing) max     | 16 595 µs  | 9 051 µs         | 1.8×    |
> | `BotCore.step` (interstitial)    | 3 249 µs   | 1 429 µs         | 2.3×    |
>
> At 42 ms/tick (24 Hz) budget, gameplay p50 is now 6 % and p99 13 %
> of budget; voting/meeting p99 is 20 %. All phases tested for byte-parity
> against the numpy fallback path; `MODULABOT_DISABLE_NATIVE=1` remains a
> one-switch rollback.

## 1. Problem framing

Observed costs per frame (from `modulabot/README.md` and the code):

| Stage | Current wall time | Where it happens |
|---|---|---|
| `scan_all` (sprites + HUD + radar) | ~8–9 ms typical | `actors.py::scan_all` → `sprite_match.match_actor_sprite_all_anchors` (×3 sprites × ≤2 flips) |
| `score_camera` local refit | ~1 ms/candidate, up to 289 candidates | `localize.py::_locate_near_frame` |
| Patch-hash cold path | ~5 ms | `localize.py::_locate_by_patches` |
| `parse_voting_screen` + chat OCR | ~25 ms chat-heavy | `voting.py` + `ascii.py::best_glyph` |
| `compute_ignore_mask` | ≪ 1 ms | `frame.py` (numpy stamps) |
| `_build_patch_index` | ~500 ms once per process | `localize.py` (cached) |

Tick budget is 42 ms @ 24 Hz. Worst-case meeting frames (~50+ ms including
non-perception Python) blow past the budget; gameplay is within budget but
there's no headroom for policy/A\* latency spikes or garbage collection.

Hot spots, in order of bang-per-buck:

1. **`match_actor_sprite_all_anchors`** — numpy does ~60–100
   `(max_y × max_x)` passes (one per opaque sprite pixel), allocating fresh
   boolean arrays. This is the single biggest fixed cost.
2. **`score_camera`** — vectorised but the local refit does it 1–289× per
   frame with no early-exit, unlike Nim's scalar version that bails after
   the miss budget.
3. **`best_glyph`** — vectorised per-width but still allocates per-glyph,
   per-position. Worst on voting-chat frames.
4. **`scan_task_icons`** — scalar Python over tasks × 3 bob offsets × 7×7
   search × sprite pixels. Not currently a headliner because localisation
   gates it, but it's O(interpreter) and will hurt more as we tighten
   other paths.

All of these are pure, stateless pixel→result kernels. They are the perfect
target for native-code replacement.

## 2. Options considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Numba / mypyc** | Stay in Python; small diff | Numba adds 10–30 s JIT warmup per process (will break cogames' 10-step validation gate budget); mypyc helps Python-loop code but our hot paths are already numpy; no win for `match_actor_sprite_all_anchors` | Reject |
| **B. Cython** | Faster numpy-loop kernels; mature | New build toolchain (we already have Nim); no fundamental advantage over options C/D | Reject |
| **C. Rust + PyO3 or C + ctypes** | Fast, typed, good tooling | Nothing in this repo uses Rust; Nim produces identical performance and the reference bot is already written in it | Reject |
| **D. Nim shared lib + ctypes** | Matches `nottoodumb`'s build pattern and modulabot-upstream's `ffi/lib.nim`; Nim source for every perception primitive *already exists* in `~/coding/bitworld/among_them/players/modulabot/{sprite_match,actors,localize,frame,ascii,voting,geometry}.nim` (~2.1 kLOC); `nimby`-managed toolchain already ships in the cogames bundle path | Need a Python-friendly FFI (the upstream FFI wraps the whole bot; we want perception-only) | **Recommended** |
| **E. Import upstream `modulabot` whole-hog via `ffi/lib.nim`** | Zero new FFI code | Throws away the Python modular architecture; can't mix Python policy with Nim perception; loses the trace writer we just shipped; loses the modular policy layer | Reject |

**Decision: Option D.** Port only the perception *primitives* to Nim, keep
the BotCore/policy/trace/state/chat/evidence layers in Python. This
preserves the architecture win of the rewrite (which is why we ported in
the first place) while moving the pixel-bashing into native code where it
belongs.

## 3. Scope

### 3.1 Port to Nim (behind an FFI)

Stateless, hot, pure pixel kernels. Every function below has an existing
Nim implementation we can re-export:

| Python symbol | Nim source | Notes |
|---|---|---|
| `sprite_match.match_actor_sprite_all_anchors` | `sprite_match.nim` (scalar — vectorise inside Nim, or run scalar which is already fast enough there) | Biggest win |
| `sprite_match.actor_color_index_all_anchors` | `sprite_match.nim::crewmateColorIndex` | |
| `sprite_match.sprite_misses` / `matches_sprite_shadowed` / `matches_crewmate` | `sprite_match.nim` | Small callers; single-anchor |
| `localize.score_camera` | `localize.nim::scoreCamera` | With early-exit |
| `localize._hash_frame_patches` | `localize.nim::framePatchHash` | |
| `localize._build_patch_index` | `localize.nim::buildPatchEntries` | Build once per process; one-shot helper is fine |
| `frame.compute_ignore_mask` | `frame.nim` | Called every frame, inside `localize` |
| `actors.scan_radar_dots` | `actors.nim::scanRadarDots` | Tiny but cheap to co-locate |
| `ascii.best_glyph` / `find_text` / `text_matches` | `common/pixelfonts.nim` + `texts.nim` | OCR is slow on chat-heavy frames |
| `actors.scan_task_icons` | `actors.nim::scanTaskIcons` | Rolls in sprite match + ignore + task list — better as one FFI call than many |

### 3.2 Keep in Python

Anything stateful, policy-shaped, or cheap:

- `BotCore` orchestration, `state.py` dataclasses, `trace.py` JSONL writer.
- All `policies/` (crewmate / imposter / voting decision half).
- `path.py` A\* — per-goal not per-frame; current 10–30 ms is fine.
- `evidence.py`, `chat.py`, `diag.py`, `tuning.py`.
- Interstitial gate (`looks_like_interstitial`) — already O(one numpy
  pass), not worth the FFI boundary cost.
- `voting.py` parse orchestration — calls many sub-primitives; keeping the
  glue in Python lets us iterate on the voting decisions without
  rebuilding.

### 3.3 Non-goals

- Not porting the whole bot. The upstream `ffi/lib.nim` does this; we
  reject it in § 2.
- Not changing perception *semantics*. We're swapping implementations under
  a 1:1 API. All existing snapshot and parity tests
  (`test_perception_snapshots.py::VectorisedParityTests`,
  `test_localize.py`, `test_voting.py`, `test_ascii.py`) must pass
  unchanged.
- Not introducing GPU dependencies. Tournament runners are CPU-only.

## 4. FFI design

### 4.1 Surface

A thin Nim module `modulabot/nim_perception/lib.nim` exporting C symbols
with this shape:

```nim
# Every entry point is pure and stateless except those explicitly noted.
# Buffer args are raw pointers + lengths; Python-side is zero-copy into
# NumPy's `arr.ctypes.data`. Output buffers are caller-allocated.

proc mb_abi_version*(): cint {.exportc, dynlib.}

# Sprite matching — vectorised all-anchors, one flip per call.
proc mb_match_actor_sprite*(
    frame: ptr uint8,          # (128*128,) uint8
    sprite_pixels: ptr uint8,  # (sh*sw,) uint8
    sh: cint, sw: cint,
    flip_h: cint,
    max_misses: cint,
    min_stable: cint,
    min_tint: cint,
    out_mask: ptr uint8,       # (max_y*max_x,) uint8 (0/1)
) {.exportc, dynlib.}

proc mb_actor_color_index_all*(
    frame: ptr uint8,
    sprite_pixels: ptr uint8, sh: cint, sw: cint,
    flip_h: cint,
    out_indices: ptr int8,     # (max_y*max_x,) int8
) {.exportc, dynlib.}

# Localization — score + patch hashes + ignore mask (one-shot combined).
proc mb_score_camera*(
    frame: ptr uint8,
    map_pixels: ptr uint8, map_w: cint, map_h: cint,
    ignore_mask: ptr uint8,
    cx: cint, cy: cint,
    max_errors: cint,
    out_score: ptr int32,      # [score, errors, compared]
) {.exportc, dynlib.}

proc mb_hash_frame_patches*(
    frame: ptr uint8,
    ignore_mask: ptr uint8,
    out_hashes: ptr uint64,    # (16*16,)
    out_valid: ptr uint8,      # (16*16,) 0/1
) {.exportc, dynlib.}

proc mb_build_patch_index*(
    map_pixels: ptr uint8,
    map_w: cint, map_h: cint,
    min_cx: cint, max_cx: cint,
    min_cy: cint, max_cy: cint,
    # Returns an opaque handle; caller frees with mb_free_patch_index.
): pointer {.exportc, dynlib.}

proc mb_patch_index_lookup*(
    handle: pointer,
    hash: uint64,
    out_first: ptr int32,      # index into cam_xs/cam_ys
    out_last: ptr int32,
) {.exportc, dynlib.}

proc mb_patch_index_cams*(
    handle: pointer,
    out_cam_xs: ptr ptr int32,  # returns internal arrays + length
    out_cam_ys: ptr ptr int32,
    out_len: ptr int32,
) {.exportc, dynlib.}

proc mb_free_patch_index*(handle: pointer) {.exportc, dynlib.}

# Ignore mask stamp (one call does all dynamic sprite stamps).
proc mb_compute_ignore_mask*(
    frame: ptr uint8,
    # Flattened list of (sprite_ptr, sh, sw, anchor_x, anchor_y, flip_h)
    stamps: ptr uint8,     # see layout doc
    num_stamps: cint,
    role_is_imposter: cint,
    is_ghost: cint,
    out_mask: ptr uint8,
) {.exportc, dynlib.}

# OCR / voting.
proc mb_best_glyph*(
    frame: ptr uint8,
    font_data: ptr uint8, font_widths: ptr uint8, font_count: cint,
    x: cint, y: cint,
    max_misses: cint,
    out_glyph_idx: ptr int32,
    out_advance: ptr int32,
    out_error: ptr int32,
) {.exportc, dynlib.}

proc mb_find_text*(
    frame: ptr uint8,
    font_data: ptr uint8, font_widths: ptr uint8, font_count: cint,
    needle: cstring,
    out_x: ptr int32, out_y: ptr int32,
) {.exportc, dynlib.}
```

**Key design choices:**

- **All buffers owned by Python / NumPy**, passed as raw pointers. No
  marshalling. No allocation in the hot path. This is the pattern
  `ffi/lib.nim` already uses for frame input.
- **Opaque handles for the patch index.** Built once per map, freed at
  process exit. The Python side stores the `c_void_p` on the cached
  `PatchIndex` dataclass (or replaces the dataclass with the handle
  entirely).
- **Font and sprite data passed per-call.** The Python side has them in
  numpy buffers already. No need to shadow-copy into Nim globals.
- **No Nim-managed state.** Unlike `ffi/lib.nim`, which holds
  `ModulabotPolicies`, this FFI is pure functions. All bot state stays in
  Python. Dramatically easier to reason about lifetimes and threading.
- **ABI version stamp** (`mb_abi_version`). Mirror of the upstream pattern;
  Python refuses to load a mismatched library.

### 4.2 Python wrapper

A single module `modulabot/nim_perception/__init__.py`:

- Loads `libmodulabot_perception.{dylib,so}` via `ctypes.CDLL`.
- Declares `argtypes` / `restype` for every symbol.
- Provides thin Python wrappers that accept the same arguments as today's
  numpy kernels and call the Nim entry points with
  `arr.ctypes.data_as(...)`.
- Exposes a `HAVE_NATIVE: bool` flag (False when the library failed to
  load) so `sprite_match` / `localize` / `ascii` can fall back to
  pure-Python for dev machines without Nim.

### 4.3 Call-site changes

For every kernel listed in § 3.1, the Python module grows a single
dispatch:

```python
# sprite_match.py
def match_actor_sprite_all_anchors(frame, sprite, flip_h, *,
                                   max_misses, min_stable_pixels, min_tint_pixels):
    if nim_perception.HAVE_NATIVE:
        return nim_perception.match_actor_sprite(
            frame, sprite.pixels, flip_h,
            max_misses, min_stable_pixels, min_tint_pixels,
        )
    return _match_actor_sprite_numpy(
        frame, sprite, flip_h,
        max_misses=max_misses,
        min_stable_pixels=min_stable_pixels,
        min_tint_pixels=min_tint_pixels,
    )
```

The numpy fallback is the *current* implementation, renamed. Nothing else
in `modulabot` changes.

## 5. Build system

Mirror the upstream pattern (`players/modulabot/build_modulabot.py` +
`config.nims`):

- **New file**: `among_them/modulabot/nim_perception/build.py` — resolves
  `nimby` (reuses `~/.nimby/` if present), invokes `nim c --app:lib
  -d:release --opt:speed
  --out:libmodulabot_perception.{dylib,so} lib.nim`.
- **New file**: `among_them/modulabot/nim_perception/lib.nim` — the FFI;
  imports existing Nim sources via `--path:` (symlink or copy relevant Nim
  files into `nim_perception/src/`).
- **Source vendoring**: rather than depend on `~/coding/bitworld/...`,
  copy the 7 Nim files (`sprite_match.nim`, `actors.nim`, `localize.nim`,
  `frame.nim`, `ascii.nim`, `pixelfonts.nim`, `geometry.nim`,
  `types.nim`) into `nim_perception/src/` at port time. This keeps the
  submission bundle self-contained (`cogames ship -f modulabot` remains
  valid) and avoids a cross-repo dependency when the bitworld Nim bot
  drifts. Add a comment at the top of each copied file pointing at its
  upstream origin and commit hash so we can redo the copy later.
- **Lazy build**: `policy.py` on import calls `build.ensure_library()`. If
  the library exists and ABI stamp matches, skip the build. Otherwise,
  invoke `nim c`. Caches built libs keyed on source hashes. (Matches
  upstream's lazy `build_modulabot.py`.)
- **Shipped artifact**: never commit `*.dylib` / `*.so` / `*.dll` —
  already covered by `MISSION.md` § layout. The cogames worker rebuilds on
  first import.
- **`MODULABOT_DISABLE_NATIVE=1`** env var forces pure-Python fallback for
  debugging / CI on Nim-less machines.

## 6. Testing & parity

The existing test suite is the golden oracle. Nothing needs rewriting:

1. **`VectorisedParityTests`** in `test_perception_snapshots.py` already
   pins numpy vs. scalar equivalence across 275 real frames. Extend it to a
   third leg: pure-Python, Nim, and the existing vectorised-Python
   implementation. Assert all three agree element-wise.
2. **`test_localize.py`** — run against the same patch index built by Nim;
   compare camera lock rates and `score_camera` outputs frame-by-frame.
3. **`test_ascii.py`** — per-glyph `best_glyph` output must match
   byte-for-byte.
4. **`test_perception_snapshots.py`** — acts as a regression floor. If a
   Nim rewrite changes any `CrewmateMatch` field by one pixel, this test
   catches it.
5. **New**: `test_nim_perception.py` — per-FFI-entry-point smoke tests
   (empty frame, all-black frame, edge-anchor sprite, off-map camera) that
   run *without* loading the rest of the bot. Helps bisect ABI vs. logic
   regressions.
6. **Bench harness**: add `scripts/bench_perception.py` that times
   `scan_all` + `update_location` + `parse_voting_screen` over
   `fixtures_frames.npy`, printing p50 / p95 / p99 for Python vs. Nim
   paths. Run before and after each phase of the port; target numbers go
   in the README perception table.

**Non-perturbation contract**: `test_trace.py::NonPerturbationTests`
currently asserts trace writing doesn't change action sequences. Extend
with a parity test: running `scan_all` under `MODULABOT_DISABLE_NATIVE=1`
vs. with Nim must produce identical action sequences over the full
fixture. This is the strongest possible correctness guarantee.

## 7. Migration plan (phased, checkpointed)

Each phase is independently mergeable, passes all 191 existing tests, and
produces a measurable speedup.

### Phase 0 — build plumbing & "hello world" (0.5 day)

- Add `nim_perception/` directory, build script, `lib.nim` stub with only
  `mb_abi_version`.
- Wire `policy.py` to call `ensure_library()` on import, with a clean
  fallback when Nim is unavailable.
- Add `scripts/bench_perception.py` (pure-Python baseline numbers).
- New CI-equivalent: `PYTHONPATH=among_them .venv/bin/python -m unittest
  discover -s modulabot/tests -v` plus `python
  modulabot/nim_perception/build.py`.

**Gate**: 191 tests pass; `libmodulabot_perception.dylib` builds on macOS
ARM.

### Phase 1 — sprite matching (1 day)

- Vendor `sprite_match.nim`, `types.nim`, `protocol.nim` (palette),
  `frame.nim` (for `spriteCovers`).
- Export `mb_match_actor_sprite`, `mb_actor_color_index_all`,
  `mb_sprite_misses`, `mb_matches_sprite_shadowed`,
  `mb_matches_crewmate`.
- Flip `sprite_match.py` to dispatch through Nim when available.
- Extend `VectorisedParityTests` to assert Nim ≡ vectorised-numpy ≡
  scalar.

**Expected gain**: `scan_all` 8–9 ms → 1–2 ms. Biggest single phase win.

### Phase 2 — localization (1–2 days)

- Vendor `localize.nim`, `geometry.nim`.
- Export `mb_score_camera`, `mb_hash_frame_patches`,
  `mb_build_patch_index` (+ handle helpers), `mb_compute_ignore_mask`.
- Flip `localize.py`'s `score_camera`, `_hash_frame_patches`,
  `_build_patch_index` dispatchers.
- Keep `Localizer` state (previous camera, home, game_started) in Python —
  Nim is stateless for this layer.

**Expected gain**: local refit 1 ms × 289 → Nim scalar with early-exit ≈
0.1 ms × 289. Patch build 500 ms → ≤ 100 ms. Worst-case localisation
frame drops from ~5 ms to < 1 ms.

### Phase 3 — task icons + radar + ignore mask (0.5 day)

- Vendor `actors.nim`.
- Export `mb_scan_task_icons` (takes the task-rect list in one call),
  `mb_scan_radar_dots`.
- Flip `actors.py`.

**Expected gain**: kills the scalar-Python task-icon search. Modest
absolute (< 1 ms) but removes a latent cliff when many tasks are on
screen.

### Phase 4 — OCR (0.5–1 day)

- Vendor `pixelfonts.nim`, `texts.nim`.
- Export `mb_best_glyph`, `mb_find_text`, `mb_text_matches`,
  `mb_read_line`, `mb_read_run`.
- Flip `ascii.py`.

**Expected gain**: voting-chat frames 25 ms → 2–3 ms. Unblocks aggressive
meeting-time policy work (LLM calls, richer chat parsing).

### Phase 5 — cleanup (0.5 day)

- Delete now-unused vectorised numpy kernels once parity has held for a
  week.
- Update `MISSION.md` and `modulabot/README.md` perception table with new
  numbers.
- Update `AGENTS.md` to document the Nim toolchain dependency (already
  implied by the repo's existing Nim bots, but modulabot's README claims
  "pure Python" today).
- Write a one-page `nim_perception/README.md` covering: how to rebuild,
  how to add a new FFI entry point, how to debug a parity failure.

**Skip-able**: Phase 3 if you're schedule-constrained. Phase 4 only
matters if voting-phase latency becomes a problem — but it will, once the
voting policy grows.

## 8. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Nim toolchain missing on tournament runner | Low — upstream already ships a Nim bot that builds on-demand via nimby | Same `build_modulabot.py` pattern works; nimby bundles the compiler |
| Library build timeout > cogames 10-step gate | Medium | Pre-build in `policy.py` `__init__` (imports), not inside `step_batch`; keep library build under 10 s with `-d:release --opt:speed`; first `step_batch` is the gate's 10th frame, well after import |
| Parity regression slips past snapshot tests | Medium | Three-way parity (scalar / numpy / Nim) in CI; non-perturbation assertion over the 275-frame fixture; keep the numpy kernel around (just unused) for at least one tournament cycle |
| Nim stdlib differences between macOS dev and Linux runner | Low | Upstream modulabot runs the same Nim on both; nimby pins version 2.2.4 |
| Zero-copy buffer lifetime bugs | Medium | Python holds a reference to every numpy array passed to Nim for the duration of the call; `ctypes` already enforces this; write a stress test that runs `scan_all` 10 000× to surface refcount bugs |
| Upstream Nim sources drift | Low-medium | Vendor at a known commit; include the commit SHA in a `nim_perception/VENDOR.md`; re-vendor deliberately |

**Rollback**: Every phase is guarded by `HAVE_NATIVE` /
`MODULABOT_DISABLE_NATIVE`. If a bug ships, setting
`MODULABOT_DISABLE_NATIVE=1` in the tournament env restores pure-Python
behaviour with zero code changes. Keep the numpy kernels in the tree for
at least one season past the switchover.

## 9. Expected end state

After all phases:

| Stage | Current | Target |
|---|---|---|
| `scan_all` gameplay frame | 8–9 ms | 1–2 ms |
| `update_location` warm | 0.07 ms | 0.07 ms (no change — already fast) |
| `update_location` cold | 5 ms | ≤ 1 ms |
| `parse_voting_screen` chat-heavy | 25 ms | 2–3 ms |
| End-to-end pixel pipeline p95 | 15 ms | 3–5 ms |
| End-to-end pixel pipeline p99 | 40+ ms (meeting) | 8–10 ms |

That restores ~30 ms of headroom per tick for A\*, LLM chat, richer
imposter heuristics, and whatever the outer-loop trace-harness wants to
do at submission time.
