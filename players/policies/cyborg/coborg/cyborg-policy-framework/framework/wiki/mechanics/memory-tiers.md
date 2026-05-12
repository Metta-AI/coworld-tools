# Memory Tiers

Technical reference for the three-tier memory architecture.

## Architecture

```
GameMemory
├── WorkingMemory         Tier 1: volatile, replaced every tick
├── EpisodicMemory        Tier 2: ring buffer of timestamped events
├── StrategicMemory       Tier 3: key-value facts with supersession
├── PerfWindow[]          Rolling rate trackers (game-defined)
└── directive_history     Append-only log of all LLM directives
```

## Tier 1: Working Memory

**Class**: `WorkingMemory`
**Lifetime**: One tick. Overwritten by `update_from_snapshot()` every tick.

Contents:
- `snapshot_dict`: the full current snapshot
- `active_directive`: the current LLM directive (as dict)
- `recent_commands`: last 5 commands issued
- `nav_target`: current navigation destination
- `nav_eta`: estimated ticks to reach target

## Tier 2: Episodic Memory

**Class**: `EpisodicMemory`
**Lifetime**: Entire game (ring buffer with max 500 events).

Each event:
- `tick`: when it happened
- `hall`: category string (game-defined, e.g. "economy", "combat")
- `text`: human-readable one-line description
- `landmark`: if True, protected from eviction
- `data`: optional structured data dict

Eviction policy:
1. When count > max_events, scan for first non-landmark event and remove it
2. If all events are landmarks, remove the oldest landmark
3. Landmarks are never evicted before non-landmarks

## Tier 3: Strategic Memory

**Class**: `StrategicMemory`
**Lifetime**: Entire game (no eviction, but facts can expire or be superseded).

Each fact:
- `key`: unique identifier (e.g. "enemy:base:location")
- `fact`: human-readable text
- `category`: game-defined category string
- `tick_created`: when the fact was recorded
- `tick_expires`: optional expiry tick (None = never expires)
- `superseded_by`: if set, this fact has been replaced

Supersession: setting a new fact with the same key marks the old fact
as superseded and archives it in the history. This preserves the audit trail.

## PerfWindow

**Class**: `PerfWindow`
**Lifetime**: Entire game. Configurable window size (default: 100 ticks).

Tracks a cumulative metric over a sliding window and computes the rate of change.
Games register windows via `memory.add_perf_window("name", window_size)`.

## Serialization

`GameMemory.dump()` produces a single JSON dict containing all tiers, the LLM call
log, directive history, and metadata. This is the input to post-game analysis.

## Memory in the LLM Context

The narrator/context builder selects from each tier:
- **Working**: current state summary
- **Episodic**: last 10-20 events, filtered by relevance
- **Strategic**: active facts in relevant categories
- **PerfWindows**: current rates and peak rates

The narrator does NOT dump raw memory — it curates a compact context string.
