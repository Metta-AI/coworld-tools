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

### Machine-readable sidecar

After you finish the Markdown, ALSO write a JSON sidecar to:

`{{sidecar_file}}`

This file becomes the authoritative source for the aggregated
`guide_contract.json` used by downstream tooling. Markdown is for humans;
the sidecar is for the toolchain. Both must agree.

The sidecar MUST conform to this shape:

```json
{
  "schema_version": "guide.doc_contract.v1",
  "document": "INTERFACE_CONTRACT.md",
  "observation": {
    "surface_category": "visual_primary | symbolic_primary | mixed_or_alternate",
    "confidence": 0.0,
    "primary": {
      "channel": "/player",
      "transport": "websocket_binary | websocket_json | websocket | http | json | unknown",
      "input_kind": "raw_visual_observation | structured_symbolic | visual_unknown_encoding | unknown",
      "encoding": "packed_4bit_framebuffer | raw_binary | unknown",
      "width": 128,
      "height": 128,
      "byte_length": 8192,
      "bit_depth": 4
    },
    "alternates": [
      { "channel": "/sprite_player", "description": "..." }
    ]
  },
  "actions": {
    "style": "binary_button_mask | move_json | action_name_json | action_index_json | unknown",
    "default_action": "noop",
    "requires_message_type": true,
    "payload_prefix": [0],
    "payloads": {
      "noop": 0,
      "up": 1,
      "down": 2,
      "attack": 32
    },
    "candidates": [
      {
        "action_id": "up",
        "description": "Move player up one tile.",
        "evidence": [
          { "document": "INTERFACE_CONTRACT.md", "line": 213, "text": "..." }
        ]
      }
    ]
  },
  "runtime": {
    "endpoints": [
      { "path": "/player", "transport": "websocket", "description": "Per-player control channel" }
    ],
    "tick_rate_hz": 60
  }
}
```

Rules for the sidecar:

- Emit ONLY fields you can ground in the source. Use `null` for unknown numeric
  fields; omit `alternates`/`candidates`/`endpoints` entirely if there are none.
- For `actions.payloads`, the integer is the EXACT wire byte/mask the agent
  must send (e.g. ButtonA at bit 5 means `"attack": 32`). Do not put action
  indices here — those go in `description` text if relevant.
- For `actions.candidates`, list only action IDs that the live player send
  handler actually accepts on the agent channel. Do not include UI labels,
  prose synonyms, cardinal-direction aliases, or browser-only controls.
- Every candidate's `evidence` must point at a real line in the doc you just
  wrote (or a doc listed above under "Prior Documents") with the exact quoted
  text from that line.
- The Markdown and the sidecar must agree. If you change one, change the other.
- `{{sidecar_file}}` must be valid JSON parseable by `json.loads`; no trailing
  commas, no comments, no markdown fences.
