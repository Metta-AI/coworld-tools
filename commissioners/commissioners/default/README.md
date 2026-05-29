# Default Commissioner

A reference Coworld commissioner container. It implements the platform's
per-round WebSocket contract, schedules a round-robin batch of episodes per
division, ranks policies by mean episode score, and can optionally promote and
relegate policies between divisions.

This is the simplest useful commissioner: a starting point for league operators
who don't yet need custom scheduling logic, and a worked example for authors
writing their own.

## What a commissioner is

If you don't already know the role, read the authoritative public docs in the
Coworld package before this one:

- **Role contract & round lifecycle** —
  [`COMMISSIONER.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/roles/COMMISSIONER.md)
- **Protocol message models** —
  [`protocol.py`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/commissioner/protocol.py)
- **What a Coworld is** —
  [`docs/README.md`](https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/README.md)

## Contract

The container follows the same conventions the platform expects of every
commissioner:

- listens on `0.0.0.0:8080`;
- serves `GET /healthz` → `200` once ready;
- serves `WEBSOCKET /round`, the round channel.

Round flow (one round per container lifetime):

1. Platform connects and sends `round_start` (divisions, memberships, variants,
   prior `state`).
2. Server schedules round-robin matchups and sends one `schedule_episodes`.
3. Platform streams `episodes_accepted` / `episodes_rejected`, then
   `episode_result` / `episode_failed` as episodes finish.
4. Once every scheduled episode resolves, the server sends `round_complete`
   with per-division rankings, optional graduation changes, and the (unchanged)
   `state`.
5. On `round_abort`, the server closes without sending `round_complete`.

## Policy

- **Scheduling** — `round_robin`: every size-`num_agents` combination of a
  division's policies plays `--episodes-per-pair` episodes on the first declared
  variant. `num_agents` is the length of the variant's `game_config.tokens`
  array (the agent-count convention in the current
  [commissioner schema](https://github.com/Metta-AI/coworld/blob/main/src/coworld/commissioner/protocol.py)).
- **Ranking** — each policy's score is the mean of its episode scores; rankings
  are best-first with `rank` starting at 1.
- **Graduation** — `none` (default) or `percentile` (promote the top
  `--promote-top-pct`% to the next-higher division by `level`, relegate the
  bottom `--relegate-bottom-pct`% to the next-lower).
- **State** — this commissioner is stateless across rounds; it echoes the
  inbound `state` back unchanged.

## Configuration

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `0.0.0.0` | Bind host |
| `--port` | `8080` | Listen port |
| `--strategy` | `round_robin` | Matchup strategy (only `round_robin` today) |
| `--episodes-per-pair` | `1` | Episodes per matchup |
| `--graduation` | `none` | `none` or `percentile` |
| `--promote-top-pct` | `0` | Top percent promoted (percentile graduation) |
| `--relegate-bottom-pct` | `0` | Bottom percent relegated (percentile graduation) |

## Build

```bash
docker build -t softmax/commissioners-default:latest commissioners/default
```

## Run locally

```bash
# Install deps into a 3.13 venv, then:
python commissioners/default/cli.py --round-robin --episodes-per-pair 2

# Health check:
curl localhost:8080/healthz
```

To exercise the full `/round` protocol without Kubernetes, drive it with a
WebSocket client that sends `round_start` and streams `episode_result`
messages back (the in-repo tests in `tests/` do exactly this with FastAPI's
test client).

## Tests

```bash
pip install -r commissioners/default/requirements.txt pytest httpx
pytest commissioners/default/tests
```

`test_strategies.py` and `test_graduation.py` cover the pure scheduling and
graduation logic and need no extra dependencies. `test_server.py` drives the
full WebSocket round and requires `fastapi` + `httpx`.

## Not yet implemented

The role doc advertises additional default strategies (Swiss, single/double
elimination, win-streak graduation). They are not implemented here yet; only
round-robin scheduling and percentile graduation are. Contributions welcome.
