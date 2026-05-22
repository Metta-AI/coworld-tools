# Nim oracle dumper

`extract_oracle.nim` is the **parity oracle** for the among-them-coborg
perception port. It is a self-contained Nim program that:

1. Loads each `.bin` fixture under `../fixtures/`.
2. Runs the upstream perception kernels from
   `users/james/personal_cogs/among_them/common/perception_kernels/`
   against the fixture.
3. Writes a JSON sidecar next to the fixture
   (`gameplay_131.bin` → `gameplay_131.json`) recording the kernel
   outputs.

Sidecars are checked in. The Python parity harness at
`../run_parity.py` reads them as the ground-truth oracle and gates
perception-layer changes on every fixture re-producing the same
output through the Python port.

## What this is not

- **Not a runtime path.** It does not talk to a Coworld server, a
  BitWorld server, or any live game. It reads checked-in fixtures and
  writes checked-in sidecars. It fits the "offline tools" exemption
  documented in `users/james/personal_cogs/AGENTS.md`.
- **Not a Python module.** This directory contains Nim source plus
  build artifacts. The Python side never imports from here; it just
  consumes the `*.json` sidecars produced under `../fixtures/`.
- **Not invoked by tests.** Tests at
  `players/among_them/coborg/tests/` read the checked-in sidecars
  directly. The dumper is run manually whenever the upstream Nim
  kernels change or the fixture set is widened.

## Regenerating sidecars

From repo root:

```sh
nim c -r players/among_them/coborg/perception/parity/extract_nim_oracle/extract_oracle.nim
```

Or from inside this directory:

```sh
nim c -r extract_oracle.nim
```

`nim.cfg` here pins the build flags (`-d:release --mm:orc --threads:on`,
import path into the upstream personal_cogs tree, hints off) so a bare
`nim c -r` produces a deterministic output. The compiled binary
(`extract_oracle`) is .gitignored.

## Schema

The sidecar JSON has a versioned schema. **S2 first pass
(`schema_version: 1`)** is intentionally narrow: it covers only what
the S2 stack-entry kernels (`frame.py`, `sprite_match.py`) need to
parity-test against:

```jsonc
{
  "fixture": "gameplay_131.bin",
  "schema_version": 1,
  "frame_length": 16384,        // total bytes in the unpacked fixture
  "screen_width": 128,
  "screen_height": 128,
  "sprite_matches": [
    {
      "sprite": "player",       // snake_case name from sprite_index.json
      "atlas_index": 0,         // index into baked sprite atlas
      "sh": 12, "sw": 12,       // sprite dimensions
      "flip_h": false,          // horizontal flip applied during match
      "max_misses": 8,          // budget passed to mb_match_actor_sprite_all
      "min_stable": 8,
      "min_tint": 8,
      "anchors": [[ay, ax], ...]  // sparse: positive anchors only
    },
    { "flip_h": true, ... }
  ],
  "actor_color_index": [
    {
      "sprite": "player",
      "atlas_index": 0,
      "sh": 12, "sw": 12,
      "flip_h": false,
      "indices": [[ay, ax, color_idx], ...]
        // only at sprite_match anchors above. The raw
        // mb_actor_color_index_all output reports a non-(-1) value at
        // essentially every anchor (every PICO-8 palette index is in
        // PlayerColors[]); the downstream consumer only ever reads it
        // at match-mask positions, so we trim accordingly.
    },
    { "flip_h": true, ... }
  ]
}
```

### Schema evolution

- **S3** widens coverage to body and ghost sprites with their own
  budgets, and adds `task_match` plus per-task icon results.
- **S4** adds entries for `ocr_text`, `voting`, `interstitial`,
  `localize`, and `ignore` percept fields.
- Each widening bumps `schema_version`. New keys are additive; the
  Python harness should tolerate unknown keys gracefully and only
  assert on the keys it knows about.

When the schema changes, regenerate all sidecars and commit them with
the dumper changes in the same commit so the checked-in oracle never
disagrees with the dumper source.

## Determinism

The kernels are deterministic and the JSON output uses raster-order
anchor lists, so re-running the dumper on an unchanged source tree
produces byte-identical sidecars. Manifest churn from non-deterministic
output would be a regression to fix.
