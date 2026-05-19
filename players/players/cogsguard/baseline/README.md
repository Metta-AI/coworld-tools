# CogsGuard Baseline

A scripted multi-agent policy for the `cogs_vs_clips` Coworld. Each agent runs
an independent state machine that picks a role (miner, scout, aligner, or
scrambler), acquires the matching gear, and executes the role's loop. The
policy is the historical baseline against which more sophisticated CogsGuard
policies (`role`, `buggy`, `cranky`) are measured.

- Class: `players.cogsguard.baseline.BaselinePolicy`
- Policy short name: `baseline`
- Game: `cogs_vs_clips`

## Strategy

`BaselinePolicy` implements `mettagrid.policy.policy.MultiAgentPolicy`. For
each agent it instantiates a `BaselineAgentPolicyImpl` wrapped in
`StatefulAgentPolicy[SimpleAgentState]`, so per-agent intent persists across
ticks.

Per-agent loop (`baseline_agent.py`):

1. Parse the egocentric observation and update the simple state vector
   (hunger, inventory, last-known resource locations).
2. If gear is missing, pathfind to the supply depot and acquire it.
3. Execute the role's primary action — mine, scout (move + report), align a
   junction, or scramble an enemy junction.
4. Fall back to `noop` or local exploration if the primary action is blocked.

There is no shared cross-agent state; each agent acts on its own observation
window. Hyperparameters (resource thresholds, movement biases) come from
`BaselineHyperparameters` and may be overridden at construction time.

## Runtime contract

This player ships as a self-contained Coworld player container:

- Speaks the [`coworld.player.v1`](../../docs/coworld-player-packaging.md#game-specific-player-protocols)
  JSON-over-websocket protocol by hosting `BaselinePolicy` inside
  `players.player_sdk.coworld_json_bridge`.
- Reads `COGAMES_ENGINE_WS_URL` (engine endpoint + slot/token) and
  `COGAMES_POLICY_URI` (defaults to `metta://policy/baseline`) from the
  environment at startup.
- Exits when the engine sends `{"type":"final"}` or closes the socket.

## Build & artifacts

```bash
players/cogsguard/baseline/build.sh
```

Produces:

- A `linux/amd64` Docker image tagged `players-cogsguard-baseline:dev`
  (override with `--tag`).
- A `coworld_manifest.json` `player[]` snippet on stdout, optionally also
  written to `--manifest-out <path>`.
- `players/cogsguard/baseline/dist/coplayer_manifest.json`.

Optional flags: `--push <registry-ref>` to re-tag and push, `--no-build` to
render manifests only.

## Local smoke test

```bash
docker run --rm \
  -e COGAMES_ENGINE_WS_URL="ws://host.docker.internal:8080/player?slot=0&token=local" \
  -e COGAMES_POLICY_URI=metta://policy/baseline \
  players-cogsguard-baseline:dev
```

## Layout

```
baseline/
├── __init__.py         # Re-exports BaselinePolicy
├── baseline_agent.py   # All policy logic (single file, ~1000 lines)
├── Dockerfile          # linux/amd64 player image
├── build.sh            # Coworld build entrypoint
└── README.md           # This file
```

## See also

- [`docs/coworld-player-packaging.md`](../../docs/coworld-player-packaging.md) — Coworld player contract.
- [`players/player_sdk/coworld_json_bridge.py`](../../player_sdk/coworld_json_bridge.py) — shared protocol bridge.
- [`players/cogsguard/role/README.md`](../role/README.md) — the more sophisticated descendant of this baseline.
