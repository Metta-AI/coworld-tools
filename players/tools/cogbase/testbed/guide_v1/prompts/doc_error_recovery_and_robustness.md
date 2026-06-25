## Document: ERROR_RECOVERY_AND_ROBUSTNESS.md

### Purpose

Document failure modes, error conditions, and recovery strategies. What can go
wrong, how to detect it, and how to recover without crashing or getting stuck.

### Scope (this document OWNS)

- Error catalog (all known error conditions and their symptoms)
- Stuck-state detection (how to detect the agent is stuck in a loop or dead state)
- Recovery strategies (concrete actions to take for each failure mode)
- Timeout handling (what happens when the agent is too slow)
- Desync detection and recovery (agent's model vs actual game state)
- Graceful degradation (how to fall back when something fails)
- Defensive patterns (guards and checks to prevent errors)

### Scope (this document does NOT cover)

- Normal game state transitions (STATE_AND_VIEW_MODEL)
- Connection/disconnection protocol (CONNECTION_AND_EPISODE_LIFECYCLE handles
  the protocol; this doc handles unexpected failures)
- Strategic decisions (STRATEGY_AND_POLICY_GUIDE)
- Interface schema (INTERFACE_CONTRACT)

### Guidance

- Catalog errors by source: network errors, protocol errors, game logic errors,
  agent logic errors
- For each error: symptoms (how to detect), cause (why it happens), recovery
  (what to do)
- Document any watchdog or health-check mechanisms in the source
- Describe stuck-loop patterns: what do they look like and how should an agent
  break out?
- Include timing information: how quickly must recovery happen?
- Note any known bugs or instabilities in the game server
- Think adversarially: what if other players disconnect? What if the server
  sends malformed data? What if game state is impossible?
- Provide concrete defensive patterns an agent should implement

### Dependencies

Read first:
- INTERFACE_CONTRACT.md (for protocol-level error responses)
- STATE_AND_VIEW_MODEL.md (for understanding valid vs invalid states)
