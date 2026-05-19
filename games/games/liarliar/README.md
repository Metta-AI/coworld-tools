# Liar Liar, Cut the Wire!

A JavaScript Coworld browser game about distributed bomb manuals, direct communication, redundant hints, and lying.

## Local Play

Start a local game with no bots and all player links printed:

```bash
npm run dev -- --bots 0
```

Start a one-human game with five bots; the printed player link is the human slot and the bots wait in the lobby:

```bash
BOT_PROVIDER=bedrock npm run dev -- --bots n-1 --bot-mode llm
```

Start a fully automated bot game and use the global viewer link:

```bash
BOT_PROVIDER=bedrock npm run dev -- --bots n --bot-mode llm
```

Useful local launcher options:

```bash
npm run dev -- --players 6 --bots 0|n-1|n --bot-mode scripted|llm --human-slot 0 --port 8080
```

The dev server writes `.local/session.json`, starts the server, auto-connects the requested bots, and prints the global viewer plus only the human player links. The older split bot commands still work against an existing `.local/session.json`: `npm run bots:scripted` and `npm run bots:llm`.

The LLM adapter is provider-neutral. `BOT_PROVIDER=bedrock` uses the AWS CLI. `BOT_PROVIDER=openai` uses an OpenAI-compatible chat completions endpoint via `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL`.

## Coworld

Build the local image:

```bash
docker build --platform=linux/amd64 -t liarliar-coworld:latest .
```

Certify from a metta checkout with the `origin/main` Coworld CLI:

```bash
uv run coworld certify /Users/kyleherndon/liarliar/coworld_manifest.json
```

Generate a fixed-count manifest for another player count:

```bash
node scripts/generate_manifest.mjs --players 8 > coworld_manifest.8p.json
```

## Protocol

Humans and bots receive the same slot-scoped canonical JSON view. The browser renders it visually; bots consume it directly and respond with action JSON. Hints are private manual pieces; players can relay them only as ordinary direct chat text, so the receiver cannot mechanically verify that a hint was shared truthfully.

V1 has two timed modules, both refreshing at 150 seconds: `wire_cut` is lethal on failure or timeout, and `keypad_calibration` is non-lethal and resets on failure or timeout. The other modules are untimed.

The default hint redundancy is `1.3`: every manual piece is assigned to one eligible player, and a deterministic 30% of pieces get one extra redundant holder.

Communication and hint routing use graph configs. The default is `{ "type": "circle", "radius": 2 }`, meaning players within circular distance two are neighbors. Grid graphs can be generated with `{ "type": "grid", "rows": 3, "cols": 4 }`, `{ "type": "torus", "rows": 3, "cols": 4 }`, or just `{ "type": "grid" }` when the player count factors into `m x n` with `m,n >= 3`.
