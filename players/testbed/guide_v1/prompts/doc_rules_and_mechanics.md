## Document: RULES_AND_MECHANICS.md

### Purpose

Define the complete logical rules of the game, independent of how they are
encoded in software. A reader should be able to understand how the game works
as a formal system: what is legal, what causes what, and how the game ends.

### Scope (this document OWNS)

- Complete rule set (all game rules, stated precisely)
- Action legality (what actions are available in what contexts)
- Turn/phase structure (if applicable — how the game progresses through phases)
- Win/loss/draw conditions (formal and complete)
- Scoring mechanics (how points accumulate, if applicable)
- Randomness and hidden information rules (what is random, what is hidden, from whom)
- Special mechanics (voting, trading, abilities, cooldowns, etc.)

### Scope (this document does NOT cover)

- How rules are encoded as observations/actions (INTERFACE_CONTRACT)
- State machine / state graph representation (STATE_AND_VIEW_MODEL)
- Strategic implications of rules (STRATEGY_AND_POLICY_GUIDE)
- How to parse observations of rule outcomes (OBSERVATION_DECODING)

### Guidance

- Write rules as a formal specification, not a tutorial
- Be exhaustive: if a rule exists in the source, it belongs here
- Use conditional language precisely ("if X, then Y" not "X usually leads to Y")
- Group rules by phase or mechanic, not by source file
- Call out edge cases explicitly (ties, timeouts, disconnections)
- Note where the source implements rules that aren't obvious from a game
  description (hidden mechanics, timing quirks)
- Reference source locations for non-obvious rules so a developer can verify

### Dependencies

Read first: GAME_OVERVIEW.md (for vocabulary and entity catalog)
