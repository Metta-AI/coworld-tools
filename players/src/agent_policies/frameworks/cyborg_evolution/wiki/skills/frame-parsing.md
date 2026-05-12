# Frame Parsing

How to interpret raw grid observations into structured game state.

## The Observation Contract

Every game engine delivers a per-tick observation to each agent. The framework does NOT
prescribe the observation format — it could be a flat token list, a 2D grid tensor, a
JSON object, or a sequence of events. Your game plugin's `perceive()` method converts
whatever the engine produces into a **snapshot dict** that the brain and narrator consume.

## Grid-Based Observations

Most spatial games provide an egocentric grid window centered on the agent. Common patterns:

### Token Parsing

```
Raw: ["wall", "empty", "resource:gold", "agent:enemy", "empty", ...]
→ Structured: {
    "walls": [(0,1), (3,2)],
    "resources": [{"type": "gold", "pos": (1,3)}],
    "enemies": [{"pos": (2,4)}],
  }
```

1. **Iterate tokens in scan order** (row-major, left-to-right, top-to-bottom)
2. **Convert grid index to egocentric coordinates** — `row = idx // width - offset`, `col = idx % width - offset`
3. **Classify each token** — wall, empty, entity, unknown
4. **Accumulate entities by type** — resources, agents, structures, hazards
5. **Convert egocentric to absolute coordinates** using the agent's known position

### Key Implementation Notes

- Parse EVERY tick, even if nothing changed — the brain expects a fresh snapshot
- Keep parsing stateless — don't carry over frame-to-frame state in the parser
- Emit a `FrameScan` or equivalent intermediate object before merging into memory
- Handle unknown/fog tokens explicitly — they're not the same as empty

## Non-Grid Observations

Some games provide structured data instead of grids:

- **Card games**: hand contents, discard pile, opponent card count
- **Social deduction**: chat messages, vote results, task completions
- **Board games**: piece positions, available moves, resource counts

The pattern is the same: raw observation → typed snapshot dict. The snapshot should
contain everything the brain needs to make a decision this tick.

## Snapshot Dict Design

A good snapshot dict is:

- **Flat enough** for the brain to read without deep traversal
- **Typed consistently** — positions as `(row, col)` tuples, counts as ints
- **Complete** — contains everything needed for one decision, no external lookups
- **Timestamped** — includes `tick` so the brain knows when this state is from

### Recommended Top-Level Keys

```python
{
  "tick": 150,
  "position": (42, 38),
  "hp": 90,
  "energy": 100,
  "inventory": {...},
  "visible_entities": [...],
  "nearby_threats": [...],
  "resources": {...},
  "score": 450,
  "phase": "midgame",
}
```

Games add their own keys. The framework never inspects the snapshot — only the brain
and narrator know the schema.
