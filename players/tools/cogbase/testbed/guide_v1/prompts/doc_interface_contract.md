## Document: INTERFACE_CONTRACT.md

### Purpose

Define the formal contract between an agent and the game: what the agent
receives (observations), what the agent sends (actions), what it gets back
(rewards/signals), and the timing/sequencing of these exchanges. This is the
most important technical document for agent implementation.

### Scope (this document OWNS)

- Observation schema (structure, types, shapes of what the agent receives)
- Action schema (structure, types, valid values of what the agent sends)
- Reward/signal schema (what feedback the agent receives and when)
- Communication protocol (how messages are exchanged — API calls, websocket
  messages, function calls, etc.)
- Timing contract (when observations arrive, when actions must be sent,
  timeouts, tick rates)
- Message ordering guarantees
- Schema versioning (if applicable)

### Scope (this document does NOT cover)

- How to interpret/decode observations semantically (OBSERVATION_DECODING)
- What actions physically do in the game world (ACTION_SEMANTICS_AND_CONTROL)
- How to connect/disconnect (CONNECTION_AND_EPISODE_LIFECYCLE)
- Logical game rules (RULES_AND_MECHANICS)

### Guidance

- Document the ACTUAL interface as implemented, not an idealized version
- Include exact types: if observations are JSON, show the schema; if tensors,
  show shapes and dtypes; if protocol buffers, reference the .proto
- Show concrete examples of real observation and action payloads
- Be precise about timing: "observation arrives every 100ms" not "observations
  arrive frequently"
- Note any asymmetries (e.g., observations are richer at game start)
- Document error responses and malformed-input handling
- If the interface has multiple channels or message types, catalog all of them
- Separate the player control channel from observer, global-state, replay,
  results, admin, debug, browser UI, and test-helper channels. Include
  non-player channels only in a clearly labeled "not player-admissible" section.
- For every endpoint/path, state the transport from the handler for that exact
  path. A different endpoint using websockets is not evidence that all paths are
  websocket endpoints.
- State negative evidence explicitly when it matters: if the source proves the
  player receives JSON and no framebuffer, screenshot, canvas, or pixel payload,
  write that as a contract constraint.
- This is a contract: an agent developer should be able to implement a working
  agent from this document alone (given the connection doc for bootstrapping)

### Dependencies

Read first: GAME_OVERVIEW.md (for vocabulary and entity catalog)
