# CogsGuard Cranky

A goal-tree scripted policy for the `cogs_vs_clips` Coworld. Cranky is the
sibling fork of [`buggy`](../buggy/README.md): same per-tick architecture, but
tuned for a different role-mix default (`stem=8`) and used as the comparison
target when exploring goal-evaluation parameter changes. The "Cogas brain"
nickname refers to the per-agent `CogasContext`/`CogasAgent` pair that drives
each agent's decision loop.

- Class: `players.cogsguard.cranky.policy.CrankyPolicy`
- Policy short name: `cranky`
- Game: `cogs_vs_clips`

## Strategy

`CrankyPolicy` implements `mettagrid.policy.policy.MultiAgentPolicy`. For each
agent it instantiates a `CogasAgent` whose tick loop runs in three phases:

1. **Sense** — `obs_parser` decodes the egocentric observation, `entity_map`
   tracks remembered entities, and `navigator` updates pathing state.
2. **Decide** — `evaluate_goals(...)` scores every goal in the agent's goal set
   (mine, deposit, get-gear, align-junction, scout, scramble) and picks the
   one with the best priority/utility for the current `StateSnapshot`.
3. **Act** — the chosen goal returns a mettagrid `Action`, which the bridge
   forwards to the engine.

Roles come from URI query parameters, e.g.
`metta://policy/cranky?miner=4&scout=0&aligner=2&scrambler=4`. With no
explicit roles, all agents start as `stem` agents and pick a role from the
goal-evaluation results — this is the difference from `buggy`, which defaults
to `stem=0`.

Tracing is opt-in: `?trace=1&trace_level=2&trace_agent=0`.

## Runtime contract

This player ships as a self-contained Coworld player container:

- Speaks the [`coworld.player.v1`](../../docs/coworld-player-packaging.md#game-specific-player-protocols)
  JSON-over-websocket protocol by hosting `CrankyPolicy` inside
  `players.player_sdk.coworld_json_bridge`.
- Reads `COGAMES_ENGINE_WS_URL` (engine endpoint + slot/token) and
  `COGAMES_POLICY_URI` (defaults to `metta://policy/cranky`; append query
  parameters to override role mix).
- Exits when the engine sends `{"type":"final"}` or closes the socket.

## Build & artifacts

```bash
players/cogsguard/cranky/build.sh
```

Produces:

- A `linux/amd64` Docker image tagged `players-cogsguard-cranky:dev`
  (override with `--tag`).
- A `coworld_manifest.json` `player[]` snippet on stdout, optionally also
  written to `--manifest-out <path>`.
- `players/cogsguard/cranky/dist/coplayer_manifest.json`.

Optional flags: `--push <registry-ref>` to re-tag and push, `--no-build` to
render manifests only.

## Layout

```
cranky/
├── __init__.py
├── policy.py           # CrankyPolicy + CogasAgent (top-level wiring)
├── context.py          # CogasContext, StateSnapshot
├── entity_map.py       # Remembered-entity tracking
├── goal.py             # Goal base class + evaluate_goals(...)
├── goals/              # Per-role goal implementations
├── navigator.py        # Pathing state
├── obs_parser.py       # Egocentric observation decoder
├── trace.py            # Opt-in per-tick tracing
├── Dockerfile
├── build.sh
└── README.md           # This file
```

## See also

- [`docs/coworld-player-packaging.md`](../../docs/coworld-player-packaging.md) — Coworld player contract.
- [`players/player_sdk/coworld_json_bridge.py`](../../player_sdk/coworld_json_bridge.py) — shared protocol bridge.
- [`players/cogsguard/buggy/README.md`](../buggy/README.md) — the sibling fork used for a different tuning track.
