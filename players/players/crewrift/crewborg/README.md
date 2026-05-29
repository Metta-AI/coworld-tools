# Crewborg

A [Player-SDK](../../player_sdk/) agent that plays **Crewrift**, a Coworld
social-deduction game (Among Us–style). Crewborg plugs Crewrift-specific
perception, belief, modes, and strategy into the SDK's two-loop runtime and ships
as a Docker image the Coworld runner launches.

- **Design spec:** [`design.md`](./design.md) — the settled architecture.
- **Orientation:** [`AGENTS.md`](./AGENTS.md) — codebases, protocol, source pointers.

## Status

**P2 — crewmate Normal mode + nav + action layer (current).** On top of P1's
perception, crewborg now *plays* as a crewmate: during `Playing` the mode selector
runs Normal mode, which picks the nearest incomplete assigned task and emits
`complete_task`; the action layer plans an A\* route over the walkability grid and
drives there with a bang-bang + predictive-stop movement controller, then holds A
on the station to complete it. Meetings/report/flee (P3) and imposter behaviour
(P4) are still to come (see `design.md` §11 for the phase plan).

## Layout

```
crewborg/
  __init__.py        build_runtime(): assemble the AgentRuntime + bake the map
  types.py           the six SDK types + perceive/update_belief + phase machine
  action.py          action layer: stateful resolve_action + movement controller
  nav.py             nav grid + A* route planning over the walkability mask
  trace.py           stderr-JSON trace & metrics sinks
  modes/             behavioral stances (P2: idle, normal)
  strategy/          rule_based.py: the mode selector (P2: Normal during Playing)
  perception/        Sprite-v1 decoder (decoder/tables) + resolution (resolve/entities)
  map/               vendored croatoan.resources + ported parser/bake (§6)
  coworld/           policy_player.py (bridge), scene.py, Dockerfile, entrypoint.sh
  scripts/play_local.sh
  build.sh
  tests/
```

## Develop

From the workspace root (`~/coding/players_checkouts/players`):

```sh
uv sync --extra test
uv run pytest players/crewrift/crewborg/tests
uv run ruff check players/crewrift/crewborg
```

## Run locally

Start a Crewrift dev server (see `AGENTS.md` §"Connecting / running locally"),
then:

```sh
players/crewrift/crewborg/scripts/play_local.sh
```

`COGAMES_ENGINE_WS_URL` defaults to `ws://localhost:2000/player?slot=0&token=`;
override it to point elsewhere.

## Build the image

```sh
players/crewrift/crewborg/build.sh            # build + emit manifest snippet
players/crewrift/crewborg/build.sh --no-build # only render manifests
```

The build context is the repo root; the image installs the local `players`
package (no mettagrid/cogames stack needed). **stdout = protocol channel,
stderr = logs/traces.**
