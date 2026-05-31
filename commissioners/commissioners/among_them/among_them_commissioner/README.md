# Among Them Commissioner

Runnable reference commissioner for the Among Them Coworld.

## Behavior

- `GET /healthz` returns `200`.
- `WEBSOCKET /round` accepts `round_start`, schedules episodes, collects `episode_result` messages, and emits `round_complete`.
- Entrants rotate through every seat using the current Observatory Among Them schedule: episode `n` starts with entrant `n`, then fills consecutive seats modulo the entrant count.
- Scores are averaged from the game-reported `episode_result.scores`.
- Result metadata uses `score_kind=mean_round_score` and `version=2`, matching the hosted commissioner.
- Dirt/Wood movement is emitted through `graduation_changes`: average score `> 0` moves a policy to Wood, average score `<= 0` moves it to Dirt.

The Coworld commissioner protocol source of truth remains in `Metta-AI/metta` at `packages/coworld/src/coworld/commissioner/protocol.py`.

## Local run

```sh
uvicorn commissioners.among_them.among_them_commissioner.among_them_commissioner:app --host 0.0.0.0 --port 8080
```

## Build

```sh
./commissioners/among_them/among_them_commissioner/build.sh
```
