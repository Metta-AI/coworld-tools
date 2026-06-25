# baseline

Thin wrapper around the upstream `winner_bot.ts` from the bitworld repo.
This is our reference agent -- the simplest bot that can actually win a
game of Persephone's Escape.

## Source

`~/coding/bitworld/persephones_escape/bots/winner_bot.ts` and its
dependencies (`bot_common.ts`, `bot_utils.ts`, `belief_state.ts`,
`frame_parser.ts`).

## Policy

Hardcoded, no LLM, no learning:

1. **Playing phase**: approach the nearest visible player on the minimap.
2. **Nearby player**: press A/J to create a whisper, or B/K to request entry.
3. **Inside whisper**: offer a mutual role exchange (R.OFFER) every
   policy tick. If someone else has offered, accept immediately
   (R.ACCPT). Also accept any color offers.
4. **Fallback**: wander randomly when no players are visible.

The bot has no concept of teams, deception, or strategy. It role-exchanges
with everyone it meets, hoping to stumble into its key partner. This works
in test configs where allies are grouped together but is trivially
exploitable by opponents in adversarial settings.

## Perception

Uses the full upstream frame-parsing pipeline:

- **Phase detection**: pixel pattern matching at known HUD positions
- **Role reveal parsing**: OCR of the bordered intro screen
- **Minimap scanning**: reads colored dots from the 20x20 minimap region
- **Position estimation**: combines minimap dot + floor grid dot alignment
- **Whisper status**: detects pending role/color offers via indicator pixels
- **Shout strip**: reads the last global chat message from the overworld

## Usage

```bash
# Start a server first
python scripts/launch_server.py --config simple --seed 42

# Via the universal runner (recommended)
python run_agents.py baseline
python run_agents.py baseline:3

# Standalone
python agents/baseline/policy.py --url ws://localhost:2500/player --name my_bot
```

## Results

*No test results yet.*
