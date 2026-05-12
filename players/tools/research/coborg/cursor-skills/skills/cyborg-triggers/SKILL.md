---
name: cyborg-triggers
description: >-
  Create or modify game event triggers that subclass BaseEventDetector.
  Use when implementing event detection for LLM consultation, adding new
  trigger types, tuning priorities, or configuring debounce. Triggers on
  "trigger", "event detection", "consult", "LLM scheduling", "when to call LLM".
---

# Implementing Game Triggers

Triggers decide **when** to consult the LLM. They diff consecutive snapshots
and fire when significant game events occur.

## Base Class

Subclass `framework.base_triggers.BaseEventDetector`:

```python
from framework.base_memory import GameMemory, GameEvent
from framework.base_triggers import BaseEventDetector

class MyGameTriggers(BaseEventDetector):
    def get_trigger_priorities(self) -> dict[str, int]:
        return {
            "enemy_spotted": 90,
            "phase_change": 80,
            "resource_found": 60,
            "score_change": 50,
        }

    def detect_game_events(
        self, prev: dict, curr: dict, memory: GameMemory
    ) -> list[tuple[str, GameEvent]]:
        results = []
        tick = curr.get("tick", 0)

        if curr.get("phase") != prev.get("phase"):
            ev = memory.episodic.record(
                tick, "discovery",
                f"phase: {prev.get('phase')} -> {curr.get('phase')}",
                landmark=True,
            )
            results.append(("phase_change", ev))

        return results
```

## Priority Ranges

| Range | Use |
|---|---|
| 90-100 | Critical: death, territory lost, imminent threat |
| 70-80 | Important: phase change, key resource available |
| 50-60 | Notable: objective completed, score change |
| 30-40 | Informational: new discovery, deposit |
| 10-20 | Baseline: periodic check-in, idle detection |

## Built-In Triggers (from BaseEventDetector)

These fire automatically — you don't need to implement them:
- **Periodic** (priority 10): fires every N ticks (default: 200)
- **Idle** (priority 20): fires when agent stuck for N ticks (default: 30)

## Design Rules

1. **Record events to episodic memory** — every trigger should also log the event.
2. **Mark turning points as landmarks** — they survive ring buffer eviction.
3. **Use `prev` vs `curr` diffs** — don't compare to absolute values;
   compare consecutive snapshots.
4. **Keep detection fast** — this runs every tick. No LLM calls, no I/O.
5. **Debounce** — set `consult_debounce` to prevent rapid re-firing
   of the same trigger type.

## Constructor

```python
detector = MyGameTriggers(
    consult_interval=200,   # periodic trigger interval (ticks)
    idle_threshold=30,      # stuck detection threshold (ticks)
    consult_debounce=0,     # min ticks between same trigger type
)
```

## Wiki References

- `framework/wiki/mechanics/trigger-system.md` — full trigger architecture
- `framework/wiki/skills/llm-integration.md` — when/how to consult the LLM
