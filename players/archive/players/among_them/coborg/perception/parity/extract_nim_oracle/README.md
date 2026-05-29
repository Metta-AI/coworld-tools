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

The sidecar JSON has a versioned schema. The current version is
**`schema_version: 2`** (landed at S3 P1 kickoff). The v1 keys
(`sprite_matches`, `actor_color_index`) are kept at v2 and simply
widened with more entries; v2 adds new top-level keys for the
orchestrated outputs of the upstream `actors.nim` and `tasks.nim`.

```jsonc
{
  "fixture": "gameplay_131.bin",
  "schema_version": 2,
  "frame_length": 16384,        // total bytes in the unpacked fixture
  "screen_width": 128,
  "screen_height": 128,

  // --- Kernel-level outputs (v1 keys, widened at v2) -------------------
  // Five entries: player x {flip=False, True}, body x {flip=False},
  // ghost x {flip=False, True}. Each uses the upstream actor budgets:
  //   player (= crewmate scan): max_misses=8, min_stable=8, min_tint=8
  //   body                    : max_misses=9, min_stable=6, min_tint=6
  //   ghost                   : max_misses=9, min_stable=6, min_tint=6
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
    // ... player flip=true, body flip=false, ghost flip=false, ghost flip=true
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
    // ... one per (sprite, flip) pair, matching sprite_matches above
  ],

  // --- Orchestrated outputs (new at v2) --------------------------------
  // Each fixture is treated as a fresh first-frame check: no prior
  // ghost-icon or kill-icon frame counters, role starts at Unknown.
  // Matches what upstream `scanAll` would compute on tick 1.

  // HUD slot probes for the kill-button / ghost-icon sprite at
  // (KillIconX=1, KillIconY=115). new_role is one of "unknown",
  // "crewmate", "imposter" (the BotRole enum as a lowercase string).
  "role": {
    "ghost_icon_frames": 0,
    "kill_icon_frames": 1,
    "is_ghost": false,
    "kill_ready": false,
    "role_updated": false,
    "new_role": "unknown"
  },

  // Center-camera color vote at the player's drawn position
  // (ScreenWidth/2 - SpriteSize/2, same for Y) with a small search
  // window. color_index is -1 when no anchor in the window matched.
  "self_color": {
    "updated": true,
    "color_index": 0
  },

  // Living crewmate sprites detected by scanCrewmates (excludes self
  // via the PlayerIgnoreRadius mask). Order is upstream raster + dedup.
  "crewmates": [
    {"x": 12, "y": 34, "color_index": 7, "flip_h": false},
    ...
  ],

  // Dead crewmate (body) sprites detected by scanBodies. Bodies don't
  // flip in-game, hence no flip_h field.
  "bodies": [
    {"x": 56, "y": 78, "color_index": 3},
    ...
  ],

  // Ghost sprites detected by scanGhosts. Ghosts are translucent so no
  // reliable color extraction — only anchor + flip.
  "ghosts": [
    {"x": 90, "y": 12, "flip_h": true},
    ...
  ],

  // Yellow palette-index-8 hits in the screen-edge periphery ring,
  // Chebyshev-1 deduped. HUD-layer; camera-independent.
  "radar_dots": [
    {"x": 0, "y": 64},
    ...
  ]
}
```

### Schema evolution

- **v3 (S4):** add the deferred task-icon scan (needs localize's
  camera offset) plus the `interstitial`, `ignore`, `localize`,
  `ocr`, and `voting` percept fields.
- Each widening bumps `schema_version`. New keys are additive; the
  Python harness should tolerate unknown keys gracefully and only
  assert on the keys it knows about. Older schemas remain readable
  by `run_parity.py` (the supported-versions set is explicit).

When the schema changes, regenerate all sidecars and commit them with
the dumper changes in the same commit so the checked-in oracle never
disagrees with the dumper source.

## Determinism

The kernels are deterministic and the JSON output uses raster-order
anchor lists, so re-running the dumper on an unchanged source tree
produces byte-identical sidecars. Manifest churn from non-deterministic
output would be a regression to fix.
