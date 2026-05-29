# Crewborg

A [Player-SDK](../../player_sdk/) agent that plays **Crewrift**, a Coworld
social-deduction game (Among Us–style). Crewborg plugs Crewrift-specific
perception, belief, modes, and strategy into the SDK's two-loop runtime and ships
as a Docker image the Coworld runner launches.

- **Design spec:** [`design.md`](./design.md) — the settled architecture.
- **Orientation:** [`AGENTS.md`](./AGENTS.md) — codebases, protocol, source pointers.

## Status

**P3 — meetings / report / flee (current).** On top of P2's crewmate task loop,
the mode selector now follows the full crewmate priority order: during `Voting`
it runs **Attend Meeting** (chat once, then cast a vote — default policy *skip*);
a body in view triggers **Report Body** (navigate to it and report); and an
approaching believed imposter triggers **Flee** (keep-away). The action layer
gained the edge-triggered A-press FSM, the vote cursor → skip → confirm sequence,
chat packets (sent by the bridge during Voting), and the `flee_from` keep-away
primitive. The evidence ledger is a stub, so Flee is wired but dormant until
suspicion reasoning exists. Imposter behaviour (P4) is still to come.

## Layout

```
crewborg/
  __init__.py        build_runtime(): assemble the AgentRuntime + bake the map
  types.py           the six SDK types + perceive/update_belief + phase machine
  action.py          action layer: stateful resolve_action + movement/edge FSMs
  nav.py             nav grid + A* route planning over the walkability mask
  trace.py           stderr-JSON trace & metrics sinks
  modes/             stances: idle, normal, attend_meeting, report_body, flee
  strategy/          rule_based.py: the mode selector (full crewmate priority)
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
