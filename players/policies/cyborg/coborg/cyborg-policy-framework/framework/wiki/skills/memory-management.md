# Memory Management

How the three-tier memory system works and how to use it effectively.

## The Three Tiers

### Tier 1: Working Memory (volatile)

Replaced every tick. Contains the current snapshot, active directive, and recent commands.
Think of it as the agent's "screen" — what it sees right now.

**Best for**: Current-tick decisions, immediate context for the LLM.

### Tier 2: Episodic Memory (ring buffer)

A capped log of game events, categorized by "hall" (topic). Events have a tick, text
description, and optional landmark flag. Landmarks are protected from eviction.

**Best for**: "What happened?" — reviewing recent history, detecting patterns,
informing the LLM about the game's trajectory.

**Hall categories** are game-defined. Common ones:
- `economy` — resource gains, trades, builds
- `territory` — area control changes
- `combat` — damage, kills, deaths
- `discovery` — new map features, new information
- `decisions` — LLM directives, role changes

**Tips**:
- Mark turning points as `landmark=True` — they survive ring buffer eviction
- Keep event text concise (one line) — the LLM reads these in bulk
- Include relevant numbers in text: "deposited 15 gold (cargo 15 → 0)"
- Don't record every tick — only meaningful state changes

### Tier 3: Strategic Memory (key-value facts)

Persistent facts with temporal supersession. When you learn something new that contradicts
an old fact, the old fact is marked superseded. Facts can expire after N ticks.

**Best for**: "What do I know?" — map knowledge, opponent behavior patterns,
resource locations, strategic state.

**Examples**:
```python
memory.strategic.set_fact("base:enemy:location", "enemy base at (75, 20)", "map", tick)
memory.strategic.set_fact("resource:gold:depleted", "gold mine at (30, 40) is empty", "economy", tick, expires=tick+500)
memory.strategic.set_fact("opponent:strategy", "opponent is rushing military", "strategy", tick)
```

**Tips**:
- Use structured keys: `{topic}:{subject}:{property}`
- Set expiry for facts that decay (opponent positions, resource availability)
- Category strings are game-defined — use them for filtered lookups

## Performance Windows

Rolling rate trackers for measuring throughput. Track any metric that matters:

```python
memory.add_perf_window("resources_per_tick", window_size=100)
memory.add_perf_window("kills_per_minute", window_size=300)

pw = memory.get_perf_window("resources_per_tick")
pw.record(tick, total_resources)
rate = pw.current_rate()
peak_rate, peak_tick = pw.peak()
```

**When to use**: Detecting slowdowns, triggering strategy shifts, informing the LLM
about performance trends.

## Memory Dump

At game end, `GameMemory.dump()` serializes everything to JSON:
- All episodic events
- All current + superseded strategic facts
- Working memory final state
- Performance window stats
- Directive history
- LLM call log

This dump feeds the post-game analysis (Opus) and the evolution agent.

## Spatial Memory (game-specific)

If your game has a 2D map, you'll likely need spatial memory on top of the three tiers:
- Incrementally discovered terrain (walls, open, unknown)
- Entity positions with staleness tracking
- Territory control regions

This lives in your game plugin, not the framework. The framework's strategic memory
can store derived facts ("enemy last seen at (50, 30) tick 200") but not raw map grids.

## Memory Budget

For a 2500-tick game with LLM consultations every ~200 ticks:
- Episodic: ~500 events max (ring buffer handles eviction)
- Strategic: ~100-200 active facts (superseded facts archived)
- Working: 1 snapshot (overwritten every tick)
- Memory dump: ~50-200KB JSON

The LLM context builder (narrator) selects what to include from each tier. It does NOT
dump everything — it summarizes episodic events, picks relevant strategic facts, and
formats working memory compactly.
