# orpheus_test

Minimal Orpheus agent used to exercise the framework end to end.

## Strategy

The outer loop is rule-based, not LLM-driven:

- Non-gameplay views use `idle`.
- Gameplay views use `approach_nearest` when belief has any known player
  positions.
- Otherwise gameplay uses `wander`.

The modes intentionally stay small. `WanderMode` returns the framework
`WanderTask`; `ApproachNearestPlayerMode` returns `FollowTask` for the closest
known player and falls back to `IdleTask` when no target is usable.

## Usage

Start a server first, then run:

```bash
python agents/orpheus_test/policy.py \
    --url ws://localhost:2500/player \
    --name orpheus_test \
    --log-level events
```

It can also be launched through the universal runner:

```bash
python run_agents.py orpheus_test
```

## Live Test Script

The documented live harness can launch a server, start this agent, optionally
add upstream filler bots, and verify that Orpheus logs include view
transitions:

```bash
python scripts/orpheus_live_test.py \
    --duration 30 \
    --launch-server \
    --seed 42 \
    --fillers 9
```

The script is not a pytest test; it is a manual smoke test for a local
Persephone server environment.

