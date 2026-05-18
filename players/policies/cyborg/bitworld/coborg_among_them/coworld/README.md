# coworld/

Player container assets for the coborg Among Them agent.

## Files

- `Dockerfile` — `python:3.12-slim` based image (linux/amd64). Installs the
  agent-policies package without the mettagrid-heavy `cogames` extra; the
  noop player only needs `numpy`, `pydantic`, and `websockets`.
- `entrypoint.sh` — execs `python -m
  policies.cyborg.bitworld.coborg_among_them.coworld.policy_player`.
- `policy_player.py` — `coworld.player.v1` WebSocket bridge. Reads the
  Coworld runner-supplied `COGAMES_ENGINE_WS_URL`, loops over 8192-byte
  packed frames, and dispatches each through the coborg `AgentRuntime`.

## Build

From the agent-policies repo root:

```bash
docker build --platform linux/amd64 \
  -t coborg_among_them:dev \
  -f policies/cyborg/bitworld/coborg_among_them/coworld/Dockerfile \
  .
```

## Run via Coworld

```bash
cd ~/coding/metta
uv run coworld play ./coworld/coworld_manifest.json \
  --variant default \
  --timeout-seconds 120 \
  --no-open-browser \
  coborg_among_them:dev
```

The one positional `player_images` arg is reused for all 8 player slots.

## Protocol pin

The bridge is implemented against the Coworld player protocol as defined by
`packages/coworld/src/coworld/runner/runner.py` at SHA
`e791117ff1aac01a8ae220c258ab121876511aed` (Metta-AI/metta, 2026-05-13).

Wire format (per PLAN §10 R7):

- **Inbound (server → player)**: one binary WebSocket message per tick,
  exactly 8192 bytes, 4-bit nybble-packed 128×128 frame.
- **Outbound (player → server)**:
  - `bytes([0x00, mask])` — 2-byte input packet, button bitmask in low 7 bits.
  - `bytes([0x01]) + ascii_text` — chat packet (7-bit ASCII payload).
- **Lifecycle**: connect → frame loop → server closes WebSocket on game end
  (handled as a clean exit, not an error).

Verify the pin still holds before each phase boundary; record any deviations
in DESIGN.md.
