## Document: CONNECTION_AND_EPISODE_LIFECYCLE.md

### Purpose

Document the complete lifecycle of an agent's session: how to connect, how a
game episode starts, what happens during resets, and how to cleanly disconnect.
This is the cold-start guide — what an agent does before it can play.

### Scope (this document OWNS)

- Connection protocol (how an agent connects to the game server/environment)
- Authentication/registration (if required)
- Lobby/matchmaking flow (how games are formed)
- Episode start sequence (what happens between connection and first action)
- Episode end/reset sequence (what happens when a game ends)
- Multi-episode handling (how to play multiple games in sequence)
- Disconnection and reconnection handling
- Shutdown/cleanup protocol

### Scope (this document does NOT cover)

- What observations/actions look like (INTERFACE_CONTRACT)
- Game rules during play (RULES_AND_MECHANICS)
- Error recovery strategies (ERROR_RECOVERY_AND_ROBUSTNESS)
- Training loop setup (TRAINING_AND_EVALUATION)

### Guidance

- Write this as a step-by-step sequence: "First connect, then register, then
  wait for game start, then..."
- Include exact API calls, message formats, or function signatures for each step
- Document timeouts at each stage (how long can you wait before being dropped?)
- Note what state is preserved vs reset between episodes
- Cover the unhappy paths: what happens if connection drops mid-game? Can you
  rejoin?
- If there's a difference between local/development and production connection
  flows, document both
- Show a minimal working connection example (pseudocode-level is fine)

### Dependencies

Read first: INTERFACE_CONTRACT.md (for protocol and message format context)
