## Document: OBSERVATION_DECODING.md

### Purpose

Bridge the gap between raw observations (what the agent receives) and semantic
game state (what it means). This is the perception layer reference: how to
turn bytes/numbers/JSON into understanding.

### Scope (this document OWNS)

- Field-by-field observation breakdown (what each part of the observation means)
- Decoding procedures (how to extract meaningful information)
- Observation examples with annotations (real examples, explained)
- Derived/computed features (useful features that can be computed from raw obs)
- Observation differences by game state (what changes in different phases)
- Noise, ambiguity, and reliability (which observation fields are noisy or delayed)

### Scope (this document does NOT cover)

- Observation schema/types/shapes (INTERFACE_CONTRACT — that doc defines WHAT
  you receive; this doc explains HOW TO INTERPRET it)
- Game state graph (STATE_AND_VIEW_MODEL)
- What to do with perceived information (STRATEGY_AND_POLICY_GUIDE)
- Hidden information and what's missing from observations (MEMORY_AND_HIDDEN_INFORMATION)

### Guidance

- Work through the observation structure field by field
- For each field or group: what does it represent, what are its possible values,
  what does each value mean in game terms
- Provide at least 2-3 annotated examples of real observations from different
  game states
- Document any encoding tricks (one-hot, normalized values, packed bits, etc.)
- Note which fields are most informative for decision-making
- Call out fields that are confusing, misleading, or require special handling
- If observations change structure between phases, document each variant

### Dependencies

Read first:
- INTERFACE_CONTRACT.md (for observation schema)
- STATE_AND_VIEW_MODEL.md (for game states that observations reflect)
