# Crewborg

A [Player-SDK](../../player_sdk/) agent that plays **Crewrift**, a Coworld
social-deduction game (Among Us–style). Crewborg plugs Crewrift-specific
perception, belief, modes, and strategy into the SDK's two-loop runtime and ships
as a Docker image the Coworld runner launches.

- **Design spec:** [`design.md`](./design.md) — the settled architecture.
- **Orientation:** [`AGENTS.md`](./AGENTS.md) — codebases, protocol, source pointers.

## What it does

Crewborg plays **both roles** end-to-end. As a crewmate it does tasks, attends
meetings, votes, reports bodies, and flees believed imposters. As an imposter the
role-aware selector runs a priority order during `Playing`: **Hunt** (kill ready →
navigate to the nearest isolated crewmate and kill in range), **Evade** (just
killed → vanish via a vent or move off the body), and **Pretend** (otherwise →
loiter near task stations to blend in); meetings reuse **Attend Meeting**. The
action layer covers the `kill` (edge-A in KillRange) and `vent` (level-B in
VentRange) intents. The LLM strategy seam (`design.md` §10) remains in place but
unused.

## Layout

```
crewborg/
  __init__.py        build_runtime(): assemble the AgentRuntime + bake the map
  types.py           the six SDK types + perceive/update_belief + phase machine
  action.py          action layer: stateful resolve_action + movement/edge FSMs
  nav.py             nav grid + A* route planning over the walkability mask
  trace.py           stderr-JSON trace & metrics sinks
  events.py          CrewborgEventTracer: on_step_complete hook → domain.* events
  modes/             idle/normal/attend_meeting/report_body/flee + hunt/pretend/evade
  strategy/          rule_based.py: role-aware mode selector (crewmate + imposter)
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
