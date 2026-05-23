# Among Them Starter (ivotewell)

The canonical starter player for the BitWorld Among Them Coworld. It is a Nim
screen-reading policy that connects to the Bitscreen player websocket,
localizes the screen, navigates to tasks, holds the action button to complete
them, reports bodies, and votes from observed evidence.

- Source: `ivotewell.nim` (kept in this repo so policy changes can be made
  via a normal PR review here without round-tripping through BitWorld).
- Game: `among_them`. Speaks the binary [`bitscreen_v1`](https://github.com/Metta-AI/bitworld/blob/master/docs/bitscreen_v1.md)
  wire protocol.

## Strategy

`ivotewell` perceives BitWorld's 128×128 4-bit packed frames directly off the
websocket and runs a deterministic decision loop:

1. **Localize** — compare the live frame against a known map cache to find
   the camera's world position. A patch-hash + voting fallback handles
   occlusion and HUD overlay.
2. **Find a task** — match task-icon templates against the radar overlay.
3. **Path** — A* navigation toward the chosen task, respecting walls and
   currently visible imposters.
4. **Execute** — hold the action button until the task completes (or yields
   to a "task ready" deadband if the icon disappears mid-press).
5. **Report / vote** — when a body is visible, press the report button; in
   the voting phase, vote from accumulated evidence (last-seen positions
   and witness counts of every player).

All state machine logic and constants are in `ivotewell.nim`; the file is
~140KB and self-contained.

## Runtime contract

This player ships as a self-contained Coworld player container:

- Speaks the [`bitscreen_v1`](https://github.com/Metta-AI/bitworld/blob/master/docs/bitscreen_v1.md)
  binary wire protocol directly from the Nim binary.
- Reads `COWORLD_PLAYER_WS_URL` from the environment at startup
  (`ivotewell.nim` line ~4547). The Coworld runner sets that variable for
  every player container, so the binary's address/port CLI flags are not
  needed in production.
- Exits when the engine closes the websocket.

## Build & artifacts

The Nim source imports framework modules from the BitWorld monorepo
(`../../sim`, `../../texts`, `../../votereader`, `../../../common/server`)
plus `nimby.lock`, `nim.cfg`, and Among Them asset files (`*.json`,
`*.aseprite`, `*.png`) and `clients/data/`. The build therefore needs a
BitWorld checkout as a secondary input.

The script auto-detects one of these in order:

1. `$BITWORLD_ROOT` (env override).
2. `../bitworld` next to this players repo.
3. `$HOME/coding/bitworld`.

```bash
# With auto-detection (uses ~/coding/bitworld if BITWORLD_ROOT is unset):
players/among_them/starter/build.sh

# With an explicit checkout:
BITWORLD_ROOT=/path/to/bitworld players/among_them/starter/build.sh
```

The Dockerfile uses `docker buildx --build-context player=<leaf>` to overlay
this repo's `ivotewell.nim` on top of the BitWorld build context. This
guarantees the image always contains the freshest in-repo player source,
not whatever BitWorld currently has on disk.

Produces:

- A `linux/amd64` Docker image tagged `among-them-starter:dev`
  (override with `--tag`). Expect a multi-minute first build because of
  the Nim toolchain download.
- A `coworld_manifest.json` `player[]` snippet on stdout, optionally also
  written to `--manifest-out <path>`.
- `players/among_them/starter/dist/coplayer_manifest.json`.

Optional flags: `--push <registry-ref>` to re-tag and push, `--no-build` to
render manifests only (does not require BitWorld to be present).

## Layout

```
starter/
├── ivotewell.nim       # Player source (~140KB, self-contained Nim)
├── Dockerfile          # linux/amd64 build using BitWorld as primary context
├── build.sh            # Coworld build entrypoint
└── README.md           # This file
```

## See also

- [`docs/coworld-player-packaging.md`](../../../docs/coworld-player-packaging.md) — Coworld player contract.
- [`players/among_them/coborg/README.md`](../coborg/README.md) — the in-repo Python coborg agent for the same game.
- BitWorld Among Them protocol: [bitscreen_v1.md](https://github.com/Metta-AI/bitworld/blob/master/docs/bitscreen_v1.md).
- Public league guide: <https://softmax.com/play_amongthem.md>.
