## Document: STRATEGY_AND_POLICY_GUIDE.md

### Purpose

Provide strategic guidance and policy architecture recommendations for building
a strong agent. What should the agent prioritize, what heuristics work, and
how should its decision-making be structured?

### Scope (this document OWNS)

- Strategic principles (high-level strategic priorities for this game)
- Heuristic catalog (useful hand-crafted heuristics and their rationale)
- Policy architecture recommendations (network architecture, action selection
  approaches)
- Phase-specific strategies (what matters most in each game phase)
- Opponent modeling considerations (how to account for other players)
- Risk/reward tradeoffs specific to this game
- Known strong/weak strategies (if discoverable from source or game design)

### Scope (this document does NOT cover)

- Game rules (RULES_AND_MECHANICS)
- Reward signals (REWARDS_AND_PROGRESS_SIGNALS)
- State representation (STATE_AND_VIEW_MODEL)
- Training setup (TRAINING_AND_EVALUATION)
- Error handling (ERROR_RECOVERY_AND_ROBUSTNESS)

### Guidance

- Ground strategic advice in game mechanics: "X matters because of rule Y"
- Rank strategies by complexity: simplest effective strategy first, then
  refinements
- For each heuristic: when to use it, expected improvement, and implementation
  complexity
- Consider multiple agent architectures (rule-based, RL, hybrid) and note
  which strategies apply to which
- Make the recommended baseline architecture Cyborg-compatible: deterministic
  inner-loop modes for fast local control, a slower strategy loop for mode
  directives, explicit belief snapshots, and validated action lowering
- If the game has roles, provide per-role strategic guidance
- Note strategic interactions: how does the presence of other agents change
  optimal strategy?
- Be opinionated: rank approaches, recommend defaults, flag traps
- Think about what a human expert would prioritize and translate that into
  implementable agent behaviors

### Dependencies

Read first:
- RULES_AND_MECHANICS.md (for the game rules being strategized over)
- STATE_AND_VIEW_MODEL.md (for the states where strategies apply)
