# Cogisis

Cogisis is a Nemesis-style semi-cooperative survival cogame with a first-party
Python engine. It models the board-game loop as an executable cogame without
using MettaGrid, MettaScope, or copied rulebook text/assets.

## Quickstart

```bash
cd ~/code/cogame-cogisis
uv run pytest -q
uv run cogisis
uv run cogisis --tunnel
uv run cogisis --render none --autorun --max-steps 15
uv run cogisis --cogs 3 --render unicode --autorun --max-steps 6 --policy survivor
uv run cogisis --cogs 2 --render json --autorun --max-steps 3 --policy random
uv run cogisis client --cogs 4 --max-steps 15 --output cogisis-client.html
```

By default `cogisis` starts a paused local browser session and prints the admin,
global, and player URLs. Player clients can submit valid turn actions, including
follow-up choices such as destination rooms. The simulator advances only after an
admin/player step command, or immediately when `--autorun` is passed. The global
viewer header includes a launcher for each cog and shows whether its player
client is connected. Pass `--tunnel` with the GUI/web renderer to create a
Cloudflare quick tunnel and print public `trycloudflare.com` URLs instead of
local URLs.

## Engine Coverage

The current engine includes:

- graph-based ship rooms and numbered corridors,
- hidden objective pairs with first-encounter objective selection,
- player actions for movement, cautious movement, search, rest, shooting,
  melee, room actions, repair, signal, hibernation, escape, and self-destruct,
- noise markers, danger/silence rolls, intruder-bag encounters, and larva
  contamination,
- intruder types, health, attacks, wounds, deaths, first-death escape-pod
  unlock, and queen-kill tracking,
- ship destination, three engine states, time track, hibernation opening, and
  endgame victory checks.
- a dependency-free browser global client export with an SVG ship layout,
  globally visible ship state, per-player observation panels, a turn token, a
  God Mode hidden-info toggle, and frame controls for policy-run replays.
- a local stdlib web interface at `/admin`, `/global`, `/player`, and
  `/state.json` for paused manual play, authenticated player actions, or
  explicit `--autorun` episodes.

## Layout

- `src/cogisis/engine.py` owns the simulator, ship state, actions, events, and
  winner checks.
- `src/cogisis/mission.py` builds the default ship, crew, objectives, engines,
  escape pods, and intruder bag.
- `src/cogisis/policies.py` provides `noop`, `random`, and `survivor` policies.
- `src/cogisis/cli.py` exposes `cogisis`; `cogisis play` remains a
  compatibility alias.
- `RULES.md` documents the gameplay model implemented in this repo.

## Source Boundary

The rules model was derived from publicly available rules references, especially
the official Awaken Realms rulebook PDF. See `docs/RULEBOOK_SOURCES.md`.
The repo intentionally contains a paraphrased implementation contract, not the
rulebook text, card text, board art, or other copyrighted assets.
