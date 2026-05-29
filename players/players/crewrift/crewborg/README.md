# Crewborg

A [Player-SDK](../../player_sdk/) agent that plays **Crewrift**, a Coworld
social-deduction game (Among Us–style). Crewborg plugs Crewrift-specific
perception, belief, modes, and strategy into the SDK's two-loop runtime and ships
as a Docker image the Coworld runner launches.

- **Design spec:** [`design.md`](./design.md) — the settled architecture.
- **Orientation:** [`AGENTS.md`](./AGENTS.md) — codebases, protocol, source pointers.

## Status

**P0 — idle end-to-end (current).** The package skeleton, the six SDK type
parameters, an idle mode + rule-based mode selector, stderr-JSON trace/metrics
sinks, and the Sprite-v1 websocket bridge are in place. The agent connects, runs
the `perceive → update_belief → mode.decide → resolve_action` loop once per tick,
and sends the neutral input packet (it holds no buttons). The full Sprite-v1
scene decoder and the static-map bake land in P1 (see `design.md` §11 for the
phase plan).

## Layout

```
crewborg/
  __init__.py        build_runtime(): assemble the AgentRuntime
  types.py           the six SDK types + perceive/update_belief
  action.py          action layer: resolve_action + wire encoding
  trace.py           stderr-JSON trace & metrics sinks
  modes/             behavioral stances (P0: idle)
  strategy/          rule_based.py: the mode selector (P0: always idle)
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
