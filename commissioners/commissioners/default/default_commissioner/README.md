# Default Commissioner

Runnable reference commissioner for game-agnostic Coworld leagues.

## Behavior

- `GET /healthz` returns `200`.
- `WEBSOCKET /round` accepts `round_start`, schedules round-robin episodes, collects `episode_result` messages, and emits `round_complete`.
- Entrants are taken from the current division memberships in their input order.
- Scores are averaged across all reported episode slots for each policy.
- Rankings are sorted by average score descending, then by input order.

## Local run

```sh
uvicorn commissioners.default.default_commissioner.default_commissioner:app --host 0.0.0.0 --port 8080
```

## Build

```sh
./commissioners/default/default_commissioner/build.sh
```
