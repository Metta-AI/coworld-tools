# Player SDK docs

Documentation for `players.player_sdk` (the Coworld Player SDK / Cyborg
framework).

## Framework reference

- [`metta_cogames_framework/README.md`](metta_cogames_framework/README.md) —
  the Cyborg two-loop architecture: layers, contracts, and design rationale.
- [`metta_cogames_framework/PYTHON_FRAMEWORK.md`](metta_cogames_framework/PYTHON_FRAMEWORK.md) —
  quickstart for building a new agent on the SDK.
- [`metta_cogames_framework/SOURCE_REPOS.md`](metta_cogames_framework/SOURCE_REPOS.md) —
  historical source pointers that informed the first version.

## Engine bridges

A **bridge** connects a player policy to a game engine's websocket player
protocol. All bridges share one transport — `run_message_bridge`
(`message_bridge.py`): connect, async-iterate inbound text/binary frames, let a
handler emit outbound frames, and exit 0 when the server closes (the Coworld
runner requires player containers to exit 0 on episode end, *including* abrupt
code-1006 closes). Each engine bridge is a thin specialization that owns its wire
envelope and takes a game-supplied callback.

The SDK ships one bridge per supported engine, under a standardized naming
convention — module `<engine>_bridge` exposing `run_<engine>_bridge` and, where
the engine carries per-step context, an `<Engine>Context`:

| Engine | Run function | Protocol | Callback / contract |
|---|---|---|---|
| **cogweb** | `run_cogweb_bridge` | `cogweb.player.v1` (JSON, request/reply) | `decide(view, ctx) -> decision`; opaque view/decision, id echo, reason re-request, chess-clock, cheap talk |
| **BitWorld/SpriteV1** | `run_sprite_bridge` | `/sprite_player` (binary render stream) | `decide(world, ctx) -> mask` (or `(mask, chat)`); raw `SpriteWorld` of sprites+objects, held controller mask |
| **mettagrid** | `run_mettagrid_bridge` | `coworld.player.v1` (JSON, triplet tokens) | hosts a registered mettagrid `MultiAgentPolicy` resolved from a URI |

Notes:

- **cogweb** (`cogweb_bridge.py`) and **sprite** (`sprite_bridge.py`) are both
  thin `decide`-callback specializations of `run_message_bridge`, and neither
  imports mettagrid — they are part of the grid-free core. The sprite bridge
  deliberately hands `decide` the *raw* accumulated sprite/object state and does
  **not** decode pixels, the palette, or game semantics; perception is the
  game's job (it may use mettagrid's `bitworld_sprite_player` helpers). The
  canonical SpriteV1 wire reference is mettagrid's `bitworld_sprite_player.py`.
- **mettagrid** (`coworld_json_bridge.py`) is policy-hosting rather than
  `decide`-callback, predates `run_message_bridge`, and imports mettagrid — so it
  requires the optional `cogames` extra and is exported **lazily** from
  `players.player_sdk` (accessing `run_mettagrid_bridge` / `MettagridBridge`
  resolves it on demand; a bare `import players.player_sdk` stays grid-free).
  Its module/`main` entrypoint is retained because Docker images launch it as
  `python -m players.player_sdk.coworld_json_bridge`; `run_bridge` /
  `CoworldJsonBridge` remain as back-compat aliases. Aligning it onto
  `run_message_bridge` is a deferred follow-up (see the design doc below).

URL source: the cogweb and sprite bridges read the websocket URL via `env_ws_url`
(`COWORLD_PLAYER_WS_URL`, legacy alias `COGAMES_ENGINE_WS_URL`). The mettagrid
bridge's `main()` reads `COGAMES_ENGINE_WS_URL` directly (along with
`COGAMES_POLICY_URI` and friends — see its module docstring).

## Designs

Living design documents for SDK evolution.

- [`designs/generalizing-the-sdk-for-turn-based-games.md`](designs/generalizing-the-sdk-for-turn-based-games.md) —
  how to make the SDK useful for turn-based / message-driven games (e.g. Cue n
  Woo) without removing the gridworld machinery: an explicit telemetry/grid
  boundary, a generic message bridge, a shared LLM-client helper, an opaque
  trace step coordinate, and a reusable `TraceConfig` base. Prioritized plan.
