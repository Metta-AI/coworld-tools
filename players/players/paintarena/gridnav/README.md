# paintarena/gridnav — SDK-library demo player

A Paint Arena player whose purpose is pedagogy: the smallest *real, packaged*
consumer of the shared `player_sdk` navigation/bookkeeping libraries, on the
simplest coworld protocol.

What it demonstrates, and where:

| SDK piece | Used for | In |
|-----------|----------|----|
| `player_sdk.nav_grid` (`GridNavConfig`, `observe`, `next_move`) | pathing to the chosen tile with the opponent classified as a *stranger* — its repulsion field bends routes away from contested space | `strategy.py::GridNavPolicy.choose_move` |
| `player_sdk.worldmodel.targets` | sticky tile commitment with progress-based invalidation (no oscillation between equally-near tiles) | `strategy.py::GridNavPolicy._pick_tile` |
| `player_sdk.worldmodel.select` | filter-relaxation choice: prefer *safe* unpainted tiles, relax to any unpainted tile | `strategy.py::GridNavPolicy._pick_tile` |

Also worked through in `strategy.py`'s docstring: the `[x, y]` ⇄ `(row,
col)` frame conversion, the ground-truth-position mode of `nav_grid` (Paint
Arena is fully observable, so no dead-reckoning), and the direction-name →
wire-move mapping.

Transport (`agent.py`) mirrors `players/paintarena/default/agent.py`. Build
like any player (context = repo root):

```bash
docker build -f players/paintarena/gridnav/Dockerfile -t paintarena-gridnav:dev .
```

Tests: `validation/players-tests/test_paintarena_gridnav.py` drives full
episodes through a local simulator of the Paint Arena server (same harness
shape as `test_paintarena_default.py`).

Origin of the libraries: Ron Dahlgren's (swgy) agent stacks — see
`players/player_sdk/nav_grid/README.md`.
