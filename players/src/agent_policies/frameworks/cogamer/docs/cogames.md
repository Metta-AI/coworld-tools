# CoGames CLI

## Setup

See `cogamer/skills/cogames.md` for install, auth, and validation steps.

## Running Locally

Play a game and check the "per cog" score:

```bash
source .venv/bin/activate
PYTHONPATH=src/cogamer cogames play -m machina_1 \
  -p class=cvc.cogamer_policy.CvCPolicy \
  -c 8 -r none --seed 42
```

**Test across 5+ seeds** (42–46) and average. Single-seed results are noise.

Without LLM (matches tournament conditions):
```bash
ANTHROPIC_API_KEY= PYTHONPATH=src/cogamer cogames play -m machina_1 \
  -p class=cvc.cogamer_policy.CvCPolicy \
  -c 8 -r none --seed 42
```

## Deploying

### Prerequisites

Run `cogamer/skills/cogames.md` if not already done.

### Upload to Season

Upload a policy to a season. The policy name (`-n`) **MUST start with your cogamer name** from `cogamer/IDENTITY.md` (e.g. if you're "scissors", use "scissors" or "scissors_v2"). Never use another cogamer's name. Must run from `src/cogamer/`:

```bash
cd src/cogamer && PYTHONPATH=. cogames upload \
  -p class=cvc.cogamer_policy.CvCPolicy \
  -n <cogamer-name> \
  -f cvc -f setup_policy.py \
  --setup-script setup_policy.py \
  --season <season> \
  --skip-validation
```

`setup_policy.py` runs on the remote server to install `anthropic[bedrock]` for LLM calls.

### Validate Before Upload

Always test locally across 5+ seeds before uploading:

```bash
for seed in 42 43 44 45 46; do
  ANTHROPIC_API_KEY= PYTHONPATH=src/cogamer cogames play -m machina_1 \
    -p class=cvc.cogamer_policy.CvCPolicy \
    -c 8 -r none --seed $seed
done
```

If average score drops vs baseline, do NOT upload — revert the change first.

## Monitoring

```bash
cogames leaderboard <season> --policy <your-cogamer-name>  # YOUR standings only
cogames matches --season <season>                         # recent matches
cogames match-artifacts <match-id>                        # logs from a match
cogames season progress <season>                          # stage progression
```

**Always use `--policy <your-cogamer-name>`** (from `cogamer/IDENTITY.md`) instead of `--mine`. The `--mine` flag shows all policies from the shared account, including other cogamers.

## Seasons

| Season | Purpose | Format |
|--------|---------|--------|
| `beta-cvc` | **Freeplay** — test against real opponents, low stakes | Self-play qualifier → 20 matches vs random partners |
| `beta-teams-tiny-fixed` | **Tournament** — ranked competition | Multi-stage elimination, team-based scoring |

Freeplay policies qualify via self-play, then play 20 matches against random partners. Use this to validate changes against diverse opponents before committing to tournament.

Tournament format: multi-stage elimination. Policies qualify via self-play, get seeded into teams, teams compete across progressive stages with culling. Final score based on team rank.

## Learnings & Experience

Games write experience to `/tmp/coglet_learnings/{game_id}.json` containing snapshots, LLM logs, and per-agent state.
