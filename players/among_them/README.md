# Among Them

[Among Them](https://softmax.com/alignmentleague) is the BitWorld
social-deduction game in the cogames Alignment League Benchmark. An 8-player
Among-Us clone running over the same 128x128 4-bit palette interface as the
rest of BitWorld, with 2 imposters and 8 tasks per player by default.

Current season: `among-them` (verify with `cogames season list`).

## Agents in this directory

| Agent | Status | Strategy |
|---|---|---|
| [`modulabot/`](modulabot/README.md) | v0, local tests passing | Modular scripted bot ported from the Nim `modulabot` architecture — state and pixel perception paths, crewmate task play, imposter fake-task/kill/flee, evidence-based voting. |
| [`guided_bot/`](guided_bot/README.md) | phase 0 scaffold (no-op) | Modular Nim hybrid: fast scripted inner loop (perceive/update/decide/act) driven by a slow asynchronous LLM guidance loop that sets active `mode` + structured params. LLM takes direct control during meetings. See `guided_bot/DESIGN.md`. |

## Conventions

- One agent per subdirectory. Each has its own `README.md` answering:
  what strategy, current status, leaderboard score once submitted, what's
  next.
- Shared helpers between agents go in a `shared/` or `common/`
  subdirectory once they actually exist — don't speculatively build one.
- Submission bundle root is the agent directory (e.g. `modulabot/`). The
  cogames `ship` command gets `-f <agent_dir>`; everything the policy
  imports must live inside that directory.

## Reference material

Prior art lives outside this repo and should be cited explicitly rather
than copied unless we need to:

- `~/coding/bitworld/among_them/players/` — canonical Nim bots
  (`nottoodumb.nim`, `modulabot/`, `evidencebot_v2.nim`), the battle-tested
  submission guide (`how_to_submit_to_cogames.md`), and the deep bot-making
  guide (`how_to_make_a_bot.md`). Read `modulabot/DESIGN.md` before making
  any architectural decisions here.
- `~/coding/metta/cogames-agents/src/cogames_agents/policy/bitworld_among_them.py` —
  Softmax's own scripted Python policies (`BitWorldAmongThemScoutPolicy`,
  `BitWorldAmongThemCyborgPolicy`). Good prior art for the BitWorld action
  space, state-observation layout, and the LLM-chat optional extra.
- `cogames docs amongthem_policy` — official walkthrough.
- `cogames tutorial make-policy --amongthem -o template.py` — up-to-date
  starter policy template.

## Running tests

Each agent ships its own tests. For modulabot:

```bash
cd among_them
PYTHONPATH=. python -m unittest discover -s modulabot/tests -v
```

## Running a local episode

The project-level `.venv` has cogames + mettagrid + bitworld installed.
The `scripts/play_local.py` harness boots a real Nim server, fills the
lobby with `nottoodumb` bots, and connects a Python policy via the same
`BitWorldRunner` code path the tournament uses:

```bash
cd /Users/jamesboggs/coding/personal_cogs
source .venv/bin/activate
PYTHONPATH=among_them python among_them/scripts/play_local.py --duration 20
```

Use this for:

- Verifying observation shape, dtype, and palette usage.
- Watching action distributions evolve as we add perception.
- Getting a replay-style trace (add `--log-frame-shapes` for more verbose).

The binary paths are looked up at:

- `~/coding/bitworld/out/among_them` — the server.
- `~/coding/bitworld/out/nottoodumb` — the filler bot.

Override with `AMONG_THEM_BINARY=/path/to/binary` if needed.

## Game constants (from `mettagrid.bitworld`)

- Screen: 128 × 128, 4-bit indexed palette (PICO-8).
- Players: 8 (2 imposters).
- Tasks per player: 8.
- Vote timer: 600 ticks.
- Imposter kill cooldown: 1200 ticks.
- Action space: 27 discrete actions (directional + A/B combinations).

If the tournament configuration differs from these defaults for a given
season, check `cogames season show among-them` for the exact config.
