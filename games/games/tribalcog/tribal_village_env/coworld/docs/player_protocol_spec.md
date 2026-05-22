# Tribal Cog Player Protocol

Players connect to:

```text
WEBSOCKET /player?slot=<0-999>&token=<runner-token>
```

Each slot controls exactly one Tribal Cog agent. Slot `0` controls agent `0`,
slot `124` controls team 0's final agent, slot `125` controls team 1's first
agent, and slot `999` controls team 7's final agent. Agent IDs `1000..1005`
are game-owned goblin/NPC agents.

## Server to player

The server sends one JSON observation message per tick:

```json
{
  "type": "observation",
  "slot": 0,
  "agent_id": 0,
  "team_id": 0,
  "team_agent_index": 0,
  "step": 12,
  "max_steps": 1000,
  "started": true,
  "done": false,
  "reward": 0.0,
  "score": 1.25,
  "team_score": 91.5,
  "action_space": 308,
  "observation": {
    "dtype": "uint8",
    "shape": [101, 11, 11],
    "encoding": "base64",
    "data": "..."
  }
}
```

The observation bytes are the existing Tribal Cog per-agent observation tensor
encoded as contiguous raw `uint8` bytes.

The final message has `"type": "final"` and the same shape as an observation.

## Player to server

Players reply with one action for their controlled agent:

```json
{ "action": 17 }
```

The action must be an integer in `[0, 307]`. The server also accepts
`{"action": {"verb": 0, "argument": 17}}`; the action ID is
`verb * 28 + argument`.

Invalid, missing, late, or out-of-range actions become action `0` noop for that
tick. A duplicate active connection for the same slot is rejected.
