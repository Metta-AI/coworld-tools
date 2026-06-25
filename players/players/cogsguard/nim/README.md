# CogsGuard Nim

Six scripted policies for the `cogs_vs_clips` Coworld whose hot loops are
implemented in Nim and exposed to Python through generated FFI bindings. The
Python layer (`agents.py`) is a thin shim: each `MultiAgentPolicy` subclass
forwards to a corresponding Nim policy class via the `NimMultiAgentPolicy`
base from mettagrid.

| short_name   | Python class                                | Nim source                          |
| ------------ | ------------------------------------------- | ----------------------------------- |
| `thinky`     | `ThinkyAgentsMultiPolicy`                   | `thinky_agents.nim`                 |
| `nim_random` | `RandomAgentsMultiPolicy`                   | `random_agents.nim`                 |
| `race_car`   | `RaceCarAgentsMultiPolicy`                  | `racecar_agents.nim`                |
| `role_nim`   | `CogsguardAgentsMultiPolicy`                | `cogsguard_agents.nim`              |
| `alignall`   | `CogsguardAlignAllAgentsMultiPolicy`        | `cogsguard_align_all_agents.nim`    |
| `nlanky`     | `NlankyAgentsMultiPolicy`                   | `nlanky_*.nim`                      |

Game: `cogs_vs_clips`.

## Strategy

Each Nim policy implements its own decision loop; the Python wrappers exist
only to satisfy the mettagrid `MultiAgentPolicy` interface and to forward the
URI's keyword arguments (e.g. `?miner=4&scrambler=2`) through to the Nim
constructor.

At a high level:

- **`thinky`** — search-based planner with explicit lookahead.
- **`race_car`** — speed-tuned variant of `thinky` with reduced search depth.
- **`role_nim`** — Nim port of the `role` vibe-state-machine, including the
  miner/scout/aligner/scrambler roles.
- **`alignall`** — `role_nim` variant whose aligners attempt every reachable
  junction rather than the closest cluster.
- **`nlanky`** — goal-tree policy (counterpart to the Python `buggy`/`cranky`)
  with full goal/navigator/entity-map machinery in Nim.
- **`nim_random`** — uniform-random control for benchmarking.

The Nim sources live alongside the wrappers; see the individual `.nim` files
for the per-policy decision logic.

## Runtime contract

This player ships as a self-contained Coworld player container:

- Speaks the [`coworld.player.v1`](../../docs/coworld-player-packaging.md#game-specific-player-protocols)
  JSON-over-websocket protocol by hosting the selected `NimMultiAgentPolicy`
  inside `players.player_sdk.coworld_json_bridge`.
- Reads `COGAMES_ENGINE_WS_URL` and `COGAMES_POLICY_URI` (default
  `metta://policy/thinky`). Append query parameters for policies that accept
  them (e.g. `metta://policy/nlanky?miner=4&scrambler=2&trace=1`).
- Exits when the engine sends `{"type":"final"}` or closes the socket.

## Build & artifacts

```bash
players/cogsguard/nim/build.sh
```

The Dockerfile compiles the Nim bindings at image-build time:

1. `apt-get` installs `build-essential` (Nim emits C; gcc compiles it) and
   `ca-certificates` (nimby + manual nimby.lock sync use HTTPS).
2. `pip install -e ".[cogames]"` installs the `players` package, mettagrid,
   and the bridge dependencies.
3. `python -m players.cogsguard.nim.build` invokes `build_nim()`, which
   downloads the pinned Nim toolchain (`.nim-version` = 2.2.6) via nimby
   (`.nimby-version` = 0.1.26), syncs `nimby.lock`, and runs
   `nim c nim_agents.nim` to produce the importable `nim_agents` module.

Produces:

- A `linux/amd64` Docker image tagged `players-cogsguard-nim:dev`
  (override with `--tag`). Expect a multi-minute first build because of the
  Nim toolchain download; subsequent builds are fast.
- A `coworld_manifest.json` `player[]` snippet on stdout, optionally also
  written to `--manifest-out <path>`.
- `players/cogsguard/nim/dist/coplayer_manifest.json`.

Optional flags: `--push <registry-ref>` to re-tag and push, `--no-build` to
render manifests only (skips the docker build entirely).

### Selecting which short_name to deploy

The `nim/` leaf registers six short_names: `thinky` (default), `nim_random`,
`race_car`, `role_nim`, `alignall`, `nlanky`. The default `metta://policy/thinky`
is baked into the image via the Dockerfile `ENV COGAMES_POLICY_URI=...`.

The manifest snippet `build.sh` emits intentionally leaves `env` empty. This is
deliberate: declaring `COGAMES_POLICY_URI` in the manifest would let a
deploy-time misconfiguration swap the image's policy for an arbitrary other
URI that mettagrid resolves (potentially even downloading one from S3). The
in-image default is the source of truth.

To deploy a non-default short_name, hand-author a manifest entry that overrides
the env:

```json
{
  "id": "cogsguard-nim-nlanky",
  "name": "CogsGuard Nim (nlanky)",
  "type": "player",
  "description": "Nlanky variant of the Nim-bindings policy",
  "image": "players-cogsguard-nim:dev",
  "env": { "COGAMES_POLICY_URI": "metta://policy/nlanky?miner=4&scrambler=2" }
}
```

Append query parameters (e.g. `?miner=4&scrambler=2&trace=1`) to control
per-policy knobs.

### Local development (no Docker)

`build_nim()` runs lazily the first time any wrapper imports `nim_agents`,
so the Nim toolchain is needed on the host for local invocation. The script
auto-installs nim via nimby into `~/.nimby/` and is safe to re-run.

```bash
uv run --project . -- python -m players.cogsguard.nim.build
```

## Layout

```
nim/
├── __init__.py
├── agents.py               # Python wrappers; one MultiAgentPolicy per Nim entrypoint
├── build.py                # build_nim(): installs nim via nimby and compiles bindings
├── nim_agents.nim          # Top-level Nim module that re-exports each policy
├── thinky_agents.nim       # Per-policy implementations
├── racecar_agents.nim
├── cogsguard_agents.nim
├── cogsguard_align_all_agents.nim
├── random_agents.nim
├── nlanky_*.nim
├── nimby.lock              # Pinned Nim package versions
├── install.sh              # Local convenience: `nim c nim_agents.nim`
├── thinky_eval.py          # Evaluation/scoring harness used during tuning
├── test_agents.py          # Smoke tests
├── Dockerfile              # linux/amd64 player image
├── build.sh                # Coworld build entrypoint
└── README.md               # This file
```

## See also

- [`docs/coworld-player-packaging.md`](../../docs/coworld-player-packaging.md) — Coworld player contract.
- [`players/player_sdk/coworld_json_bridge.py`](../../player_sdk/coworld_json_bridge.py) — shared protocol bridge.
- [`players/cogsguard/role/README.md`](../role/README.md) — the Python sibling of `role_nim`/`alignall`.
- [`players/cogsguard/buggy/README.md`](../buggy/README.md) — Python sibling of `nlanky`.
