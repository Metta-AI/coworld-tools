# Cogs vs Clips Commissioner

Runnable commissioner for the Cogs vs Clips Coworld.

## Behavior

- `GET /healthz` returns `200`.
- `WEBSOCKET /round` accepts `round_start`, schedules rolling-window episodes, collects `episode_result` messages, and emits `round_complete`.
- Competition entrants are rotated across seats with the same rolling-window scheduling used by the hosted Cogs vs Clips commissioner.
- Qualifier self-play stages isolate each entrant by filling every seat with that entrant's policy.
- Scores are averaged across all reported episode slots for each policy.
- Rankings are sorted by average score descending, then by input order.

## Local run

```sh
uvicorn commissioners.cogs_vs_clips.cogs_vs_clips_commissioner.cogs_vs_clips_commissioner:app --host 0.0.0.0 --port 8080
```

## Build

```sh
./commissioners/cogs_vs_clips/cogs_vs_clips_commissioner/build.sh
```
