## Document: STATE_AND_VIEW_MODEL.md

### Purpose

Map the complete state space of the game: all possible states, how they connect,
what transitions between them, and what information is visible from each state.
This is the agent's map of the territory.

### Scope (this document OWNS)

- Complete state graph (all game states and transitions between them)
- Phase/mode enumeration (lobby, playing, voting, dead, spectating, etc.)
- Transition triggers (what causes state changes)
- View model (what information is available/visible in each state)
- State invariants (what is always true in a given state)
- State persistence (what carries between phases/rounds)

### Scope (this document does NOT cover)

- How state is encoded in observations (OBSERVATION_DECODING)
- Logical rules that govern transitions (RULES_AND_MECHANICS)
- What to do in each state (STRATEGY_AND_POLICY_GUIDE)
- Connection states and protocol (CONNECTION_AND_EPISODE_LIFECYCLE)

### Guidance

- Draw the state graph explicitly: list every state, list every transition with
  its trigger condition
- Use a table or diagram format — make it scannable
- For each state, document exactly what information the agent has access to
  (the "view" from that state)
- Note which state transitions are agent-initiated vs environment-initiated
- Distinguish between global game state and per-player state
- Call out states where information is asymmetric between players
- If the game has sub-states or nested state machines, document the hierarchy
- Reference the source: where is each state defined? What variables track it?

### Dependencies

Read first: RULES_AND_MECHANICS.md (for game rules and phase structure)
