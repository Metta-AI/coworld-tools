# Trigger System

How the event detection and LLM consultation scheduling works.

## Overview

The trigger system decides **when** to consult the LLM. It runs every tick, comparing
the current snapshot to the previous one, and fires when significant events occur.

## Built-In Triggers

The framework provides two universal triggers:

### Periodic Trigger (priority: 10)
Fires every N ticks (default: 200) as a baseline check-in. Ensures the LLM sees the
game state even if no events fire.

### Idle Trigger (priority: 20)
Fires when the agent has been doing the same thing for N ticks (default: 30). Detects
stuck agents, broken pathfinding, or strategies that aren't making progress.

## Game-Specific Triggers

Games define their own events by subclassing `BaseEventDetector`:

```python
class MyGameEventDetector(BaseEventDetector):
    def detect_game_events(self, prev, curr, memory):
        results = []
        if curr["score"] > prev["score"]:
            ev = memory.episodic.record(tick, "economy", "scored points")
            results.append(("score_increase", ev))
        return results

    def get_trigger_priorities(self):
        return {"score_increase": 60, "enemy_spotted": 90}
```

Each `detect_game_events()` call receives the previous and current snapshot dicts
and the game memory. It returns a list of `(trigger_name, GameEvent)` pairs.

## Priority System

When multiple triggers fire in the same tick, the highest-priority one wins.
The winner determines the trigger name sent to the LLM.

| Range | Typical Use |
|---|---|
| 90-100 | Critical: death, territory lost, imminent threat |
| 70-80 | Important: phase change, key resource available |
| 50-60 | Notable: objective completed, score change |
| 30-40 | Informational: new discovery, deposit |
| 10-20 | Baseline: periodic check-in, idle detection |

## Debounce

After a trigger fires, it won't fire again for a configurable number of ticks.
This prevents rapid re-consultation on the same event type.

Default debounce is 0 (no debounce — every firing triggers consultation).
Games can increase this per trigger type.

## Evaluation Flow

Each tick:
1. Take the latest snapshot from the `LatestSlot`
2. Call `detect_game_events(prev, curr, memory)` → game events
3. Check idle detection → idle trigger
4. Check periodic timer → periodic trigger
5. Collect all triggered names
6. Filter by debounce
7. Select highest priority → winner
8. If winner exists: build context, call LLM, issue directive
