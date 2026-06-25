# Paint Arena — default policy

The seeded **default** policy for the Coworld game **paintarena**, and the
worked example for the optimizer-agent `seed-a-new-policy` skill. It is a pure
**scripted** policy: a single deterministic decision function with a websocket
transport around it.

- Policy short name: `paintarena-default`
- Game: `paintarena` (2 players, 12×8 grid, 100 ticks, last-writer-wins)
- Architecture: **scripted** (no LLM, no learned model)

## Why scripted (game-mechanics analysis)

Architecture follows the mechanics. Paint Arena is:

- **Fully observable** — every observation carries the whole board
  (`tile_owners`), both `positions`, and `scores`. Nothing is hidden, so there
  is no belief/estimation problem an LLM or model would help with.
- **Deterministic & low-branching** — five moves (`up/down/left/right/stay`),
  movement is a clamped step, painting is last-writer-wins. The optimal-ish move
  is a short computation over the grid.
- **Tick-budgeted & latency-sensitive** — ~5 ticks/s; a move must be returned
  well within the tick. An LLM round-trip per tick is both unnecessary and too
  slow.

A fully-observable, deterministic, tight-latency game wants a **scripted**
policy. (Contrast: Crewrift is partially observed + social, so its player
`crewborg` is LLM/hybrid with a deterministic fallback; cogs-vs-clips is a
mettagrid token game, so its players host a `MultiAgentPolicy` through
`players.player_sdk.coworld_json_bridge`. Paint Arena needs neither.)

## Strategy: defensible coverage

Each tick, step one square toward the **nearest tile that is not already ours**,
breaking ties toward the tile **farthest from the opponent**. Because painting
is last-writer-wins, tiles deep in our half are safe and frontier tiles are
contested, so this:

1. flood-fills our own Voronoi half first (full coverage, no wasted motion), then
2. contests the shared frontier once safe territory is claimed.

It never collapses into the flip-the-same-tile oscillation that a naive
"chase the opponent" rule suffers (which can leave most of the board unpainted).
See [`strategy.py`](./strategy.py); the whole brain is `choose_move`.

## Layout (structured for long-horizon upgrades)

```
default/
├── __init__.py     # re-exports Observation + choose_move
├── strategy.py     # PURE decision logic — no I/O, unit-tested, where upgrades land
├── agent.py        # websocket transport + per-tick decision artifact upload
├── Dockerfile      # linux/amd64 self-contained player image
└── README.md       # this file
```

The pure/transport split is deliberate: strategy iteration and unit tests never
touch the network, and the agent emits a per-episode artifact
(`metadata.json` + `decisions.jsonl`) for the optimizer's reconstruction step.

## Build, smoke-test, upload

```bash
# from repo root
docker build -f players/paintarena/default/Dockerfile -t paintarena-default:dev .

# local smoke episode (1 game) vs the bundled sweep painter:
coworld run-episode <paintarena_manifest.json> paintarena-default:dev \
  --run python --run -m --run players.paintarena.default.agent

# upload for league play (verify the run attribute exists afterwards):
coworld upload-policy paintarena-default:dev --name paintarena-default \
  --run python --run -m --run players.paintarena.default.agent
```

## Tests

`validation/players-tests/test_paintarena_default.py` runs an exact local
simulator of the game and asserts the default policy (a) only ever emits legal
moves, (b) returns `stay` when it owns the whole board, and (c) beats the
bundled sweep painter from both seats. That simulator is also the fast,
free iteration harness for strategy changes (no Docker, no hosted evals).
