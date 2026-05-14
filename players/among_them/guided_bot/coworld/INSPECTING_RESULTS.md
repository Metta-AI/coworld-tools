# Inspecting Agent Results with the Coworld CLI

Reference for investigating guided_bot performance in the Among Them Daily
league using the `coworld` CLI from the Metta checkout.

## Setup

```sh
cd ~/coding/metta
# Ensure coworld is installed (may need --no-deps if mettagrid build fails)
uv pip install -e "packages/coworld[auth]" --no-deps
```

All commands below assume `~/coding/metta/.venv/bin/coworld` or equivalent.

## Key IDs

| Entity | ID |
|--------|-----|
| Among Them Daily league | `league_494db37d-d046-4cba-a99a-536b1439262f` |
| Daily division | `div_334593c6-da90-4651-98c7-606573ea1474` |
| Among Them game | `game_8a1c0e5c-512b-4b01-86d2-8a152b4b5aa0` |

## Quick Status Check

```sh
# Division leaderboard (rolling 48-round window)
coworld results div_334593c6-da90-4651-98c7-606573ea1474

# Recent rounds (are they completing or failing?)
coworld rounds -l league_494db37d-d046-4cba-a99a-536b1439262f --limit 5

# My submissions
coworld submissions --mine
```

## Inspecting a Specific Round

### 1. Get the full round ID

Table output truncates IDs. Use `--json` to get the full UUID:

```sh
coworld rounds -l league_494db37d-d046-4cba-a99a-536b1439262f \
  --status completed --limit 1 --json 2>/dev/null \
  | python -c "import json,sys; d=json.load(sys.stdin); print(d['entries'][0]['id'])"
```

Note: `--json` for rounds returns `{"entries": [...]}`, not a bare array.

### 2. View round results (leaderboard for that round)

```sh
coworld results round_XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
```

This shows per-player aggregate scores for the round.

### 3. List episodes involving our agent in a round

```sh
coworld episodes --mine -r ROUND_ID --limit 32
```

With `--json`, returns a bare array of episode objects.

## Inspecting a Specific Episode

### 1. Get our actual game slot

The **only reliable way** to determine which game slot our agent occupies is
the `--mine` flag on `episode-logs`:

```sh
coworld episode-logs EREQ_ID --mine --list
```

This shows our log file as `policy_agent_N.txt` — the `N` is our game slot.

> **Warning:** Do NOT try to derive the slot from the `assignments` array in
> the episode JSON. The `assignments` field maps participant list indices to
> something, but the mapping to actual WebSocket slots and `PlayerN` result
> names is non-obvious and unreliable for this purpose.

### 2. View our agent's logs

```sh
# Print to stdout
coworld episode-logs EREQ_ID --mine

# Download to a file
coworld episode-logs EREQ_ID --mine -d /tmp/logs
```

Expected output for guided_bot (three lines when healthy):
```
INFO - guided_bot.coworld - connecting guided_bot policy image to ws://...
[diag] font.height=6 font.spacing=1 sprites.player.w=12 sprites.player.pixels.len=144
INFO - guided_bot.coworld - BitWorld player websocket closed
```

If only `[diag]` appears without the Python INFO lines, the issue is likely
that `grep -v "^INFO"` is filtering them — the Python logging lines start
with `INFO` just like the CLI's httpx noise. Use `-d` to download and inspect
the raw file instead.

### 3. View episode results (per-player scores)

```sh
coworld episode-results EREQ_ID
```

Returns JSON with arrays: `names`, `scores`, `win`, `tasks`, `kills`,
`imposter`, `crew`. Names are `PlayerN` where N = game slot.

To find our score, match `PlayerN` where N comes from step 1.

### 4. View other agents' logs (for comparison)

```sh
# List all available logs
coworld episode-logs EREQ_ID --list

# View a specific slot's log
coworld episode-logs EREQ_ID --agent 5
```

Top-performing agents (ivotewell variants) produce verbose Go-style logs with
position, navigation, and mask data. Our guided_bot only produces the three
Python/Nim lines above — detailed traces go to local files not captured by
the runner.

## Aggregate Performance Analysis

There's no built-in command for per-policy stats. Use this script:

```python
#!/usr/bin/env python
"""Aggregate guided_bot stats for a round."""
import json, re, subprocess, sys

ROUND_ID = sys.argv[1] if len(sys.argv) > 1 else input("Round ID: ")

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout + r.stderr

# Get all our episodes in the round
episodes = json.loads(subprocess.run(
    ["coworld", "episodes", "--mine", "-r", ROUND_ID, "--json"],
    capture_output=True, text=True
).stdout)

wins = losses = crew_w = crew_l = imp_w = imp_l = 0
total_score = total_tasks = total_kills = no_score = 0

for ep in episodes:
    ep_id = ep["id"]

    # Get our slot from --mine --list
    combined = run(["coworld", "episode-logs", ep_id, "--mine", "--list"])
    m = re.search(r"(\d+)\s+policy_agent_\d+\.txt", combined)
    if not m:
        no_score += 1
        continue
    slot = int(m.group(1))

    # Get results
    results = json.loads(subprocess.run(
        ["coworld", "episode-results", ep_id],
        capture_output=True, text=True
    ).stdout)

    player = f"Player{slot}"
    if player not in results["names"]:
        no_score += 1
        continue
    idx = results["names"].index(player)

    score = results["scores"][idx]
    win = results["win"][idx]
    imp = results["imposter"][idx]
    tasks = results["tasks"][idx]
    kills = results["kills"][idx]

    total_score += score
    total_tasks += tasks
    total_kills += kills
    if win:
        wins += 1
        if imp: imp_w += 1
        else: crew_w += 1
    else:
        losses += 1
        if imp: imp_l += 1
        else: crew_l += 1

scored = wins + losses
print(f"Episodes: {len(episodes)}, Scored: {scored}, No-score slots: {no_score}")
if scored:
    print(f"Win rate: {wins}/{scored} ({wins/scored*100:.0f}%)")
    print(f"  Crew: {crew_w}W/{crew_l}L  Imposter: {imp_w}W/{imp_l}L")
    print(f"Avg score: {total_score/scored:.1f}")
    print(f"Tasks/game: {total_tasks/scored:.1f}")
    imp_games = imp_w + imp_l
    if imp_games:
        print(f"Kills/imposter game: {total_kills/imp_games:.1f}")
```

Save as `scripts/round_stats.py` and run:
```sh
cd ~/coding/metta
.venv/bin/python ~/coding/personal_cogs/among_them/scripts/round_stats.py ROUND_ID
```

## Known Gotchas

### Slot mapping (Player0/Player1 produce no scores)

The Among Them game uses 10 internal slots (0-9) but only slots 2-9 produce
game scores. When our agent is assigned to slot 0 or 1, it runs correctly
(connects, processes frames, disconnects cleanly) but gets no score recorded.
This happens in ~25% of episodes (8/32 in a typical round) and is a
server-side assignment issue, not a bot bug.

Symptoms: `episode-results` has 8 entries using Player2-Player9, and our
`--mine` log shows `?slot=0` or `?slot=1`.

### The `[diag]` line is normal

`[diag] font.height=6 font.spacing=1 ...` is a one-shot diagnostic from
the Nim bot on the first processed frame. It confirms the shared library
loaded and perception data is intact. Its presence means the bot is working.

### Round status "failed" with score-count errors

Errors like "results contain 9 scores for 8 stored policy versions" are
server-side bugs in the tournament runner. They resolve on their own when
the next round starts. Check `--status completed` to find the last good round.

### JSON shape reference

| Command | `--json` shape |
|---------|---------------|
| `submissions --mine` | bare array |
| `rounds -l LEAGUE` | `{"entries": [...]}` |
| `episodes --mine -r ROUND` | bare array |
| `episodes EREQ_ID` | single object |
| `episode-results EREQ_ID` | single object with parallel arrays |
| `results DIV_ID` | object with `ladder` array |
| `images` | bare array |

### Log output includes both CLI noise and agent output

`coworld episode-logs EREQ_ID --agent N` prints httpx INFO lines to stderr
and the actual log content to stdout. When using `2>&1` or viewing
interactively, both are mixed. The agent's own Python logging also starts
with `INFO -`, making them easy to confuse with CLI noise.

To separate: redirect stderr (`2>/dev/null`) or use `-d DIR` to download.
