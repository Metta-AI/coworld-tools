# CogsGuard Buggy

A goal-tree scripted policy for the `cogs_vs_clips` Coworld. Buggy is a fork of
the historical Planky policy kept as a stable sibling so experimental tuning
can happen on `buggy` without disturbing the canonical `baseline`/`role`
policies. The implementation favours composable goals over a monolithic state
machine: each agent evaluates a forest of `Goal` objects every tick and
executes the highest-scoring one.

- Class: `players.cogsguard.buggy.policy.PlankyPolicy`
- Policy short name: `buggy`
- Game: `cogs_vs_clips`

## Strategy

`PlankyPolicy` implements `mettagrid.policy.policy.MultiAgentPolicy`. For each
agent it instantiates a `PlankyAgent` whose tick loop runs in three phases:

1. **Sense** — `obs_parser` decodes the egocentric observation, `entity_map`
   tracks remembered entities, and `navigator` updates pathing state.
2. **Decide** — `evaluate_goals(...)` scores every goal in the agent's goal set
   (mine, deposit, get-gear, align-junction, scout, scramble) and picks the
   one with the best priority/utility for the current `StateSnapshot`.
3. **Act** — the chosen goal returns a mettagrid `Action`, which the bridge
   forwards to the engine.

Roles are assigned at startup from URI query parameters, e.g.
`metta://policy/buggy?miner=4&scout=0&aligner=2&scrambler=4`. When the URI
omits role counts and `stem > 0`, every agent starts as a stem (general-purpose)
agent that picks a role from the goal-evaluation results.

Tracing is opt-in: `?trace=1&trace_level=2&trace_agent=0` activates the
`trace` module's per-tick decision log for the named agent.

## Runtime contract

This player ships as a self-contained Coworld player container:

- Speaks the [`coworld.player.v1`](../../docs/coworld-player-packaging.md#game-specific-player-protocols)
  JSON-over-websocket protocol by hosting `PlankyPolicy` inside
  `players.player_sdk.coworld_json_bridge`.
- Reads `COGAMES_ENGINE_WS_URL` (engine endpoint + slot/token) and
  `COGAMES_POLICY_URI` (defaults to `metta://policy/buggy`; append query
  parameters to override role mix).
- Exits when the engine sends `{"type":"final"}` or closes the socket.

## Build & artifacts

```bash
players/cogsguard/buggy/build.sh
```

Produces:

- A `linux/amd64` Docker image tagged `players-cogsguard-buggy:dev`
  (override with `--tag`).
- A `coworld_manifest.json` `player[]` snippet on stdout, optionally also
  written to `--manifest-out <path>`.
- `players/cogsguard/buggy/dist/coplayer_manifest.json`.

Optional flags: `--push <registry-ref>` to re-tag and push, `--no-build` to
render manifests only.

## Layout

```
buggy/
├── __init__.py
├── policy.py           # PlankyPolicy + PlankyAgent (top-level wiring)
├── context.py          # PlankyContext, StateSnapshot
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
- [`players/cogsguard/cranky/README.md`](../cranky/README.md) — the sibling fork used for a different tuning track.
