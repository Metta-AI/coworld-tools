# Crewborg

A [Player-SDK](../../player_sdk/) agent that plays **Crewrift**, a Coworld
social-deduction game (Among Us–style). Crewborg plugs Crewrift-specific
perception, belief, modes, and strategy into the SDK's two-loop runtime and ships
as a Docker image the Coworld runner launches.

- **Design spec:** [`design.md`](./design.md) — the settled architecture.
- **Orientation:** [`AGENTS.md`](./AGENTS.md) — codebases, protocol, source pointers.

## Status

**P1 — scene decoder + static-map bake (current).** On top of P0's idle
end-to-end loop, crewborg now decodes the binary Sprite-v1 stream into structured
state — the three retained tables, camera recovery, the walkability mask, and
objects resolved to `(label, world xy)` and classified into players / bodies /
task signals / voting / phase — and folds it into belief. The vent / room / task /
emergency-button locations (not in the stream) are baked from the vendored
`croatoan.resources` at startup. Behavior is still idle; modes, nav, and the
action layer arrive in P2 (see `design.md` §11 for the phase plan).

## Layout

```
crewborg/
  __init__.py        build_runtime(): assemble the AgentRuntime + bake the map
  types.py           the six SDK types + perceive/update_belief + phase machine
  action.py          action layer: resolve_action + wire encoding
  trace.py           stderr-JSON trace & metrics sinks
  modes/             behavioral stances (P1: idle)
  strategy/          rule_based.py: the mode selector (P1: always idle)
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
