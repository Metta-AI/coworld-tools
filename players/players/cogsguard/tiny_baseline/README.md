# CogsGuard Tiny Baseline

A small demo policy for the `cogs_vs_clips` Coworld, kept deliberately minimal
so it can be read end-to-end in a single sitting. Each agent picks one
heart-recipe resource, mines it, deposits it, and wanders when there's nothing
useful nearby. It is the smallest complete CogsGuard policy in this repo and
serves as a reading reference for anyone building a new one.

- Class: `players.cogsguard.tiny_baseline.DemoPolicy`
- Policy short name: `tiny_baseline`
- Game: `cogs_vs_clips`

## Strategy

`DemoPolicy` implements `mettagrid.policy.policy.MultiAgentPolicy`. For each
agent it instantiates a `DemoPolicyImpl` wrapped in `StatefulAgentPolicy`, so
per-agent intent persists across ticks.

Per-agent loop (`demo_policy.py`):

1. Parse the egocentric observation into a lightweight state snapshot.
2. If carrying a deposit-worthy resource, walk to the depot and drop it.
3. Otherwise, walk to a known extractor for the assigned heart-recipe resource
   and mine.
4. If neither is in view, take a random step that biases away from walls.

There is no role system, no gear management, no coordination between agents.
That simplicity is the point — read `demo_policy.py` first if you're learning
how the scripted-policy stack fits together, then graduate to
[`baseline`](../baseline/README.md) or [`role`](../role/README.md).

An optional `heart_recipe` argument lets external callers override which
resource each agent prioritizes; by default the policy infers it from
observation-time hints.

## Runtime contract

This player ships as a self-contained Coworld player container:

- Speaks the [`coworld.player.v1`](../../docs/coworld-player-packaging.md#game-specific-player-protocols)
  JSON-over-websocket protocol by hosting `DemoPolicy` inside
  `players.player_sdk.coworld_json_bridge`.
- Reads `COGAMES_ENGINE_WS_URL` (engine endpoint + slot/token) and
  `COGAMES_POLICY_URI` (defaults to `metta://policy/tiny_baseline`).
- Exits when the engine sends `{"type":"final"}` or closes the socket.

## Build & artifacts

```bash
players/cogsguard/tiny_baseline/build.sh
```

Produces:

- A `linux/amd64` Docker image tagged `players-cogsguard-tiny-baseline:dev`
  (override with `--tag`).
- A `coworld_manifest.json` `player[]` snippet on stdout, optionally also
  written to `--manifest-out <path>`.
- `players/cogsguard/tiny_baseline/dist/coplayer_manifest.json`.

Optional flags: `--push <registry-ref>` to re-tag and push, `--no-build` to
render manifests only.

## Layout

```
tiny_baseline/
├── __init__.py         # Re-exports DemoPolicy
├── demo_policy.py      # Single-file implementation, ~250 lines
├── Dockerfile          # linux/amd64 player image
├── build.sh            # Coworld build entrypoint
└── README.md           # This file
```

## See also

- [`docs/coworld-player-packaging.md`](../../docs/coworld-player-packaging.md) — Coworld player contract.
- [`players/player_sdk/coworld_json_bridge.py`](../../player_sdk/coworld_json_bridge.py) — shared protocol bridge.
- [`players/cogsguard/baseline/README.md`](../baseline/README.md) — full role-aware sibling policy.
