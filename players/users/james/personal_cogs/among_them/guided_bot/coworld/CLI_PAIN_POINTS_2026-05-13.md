# Coworld CLI Pain Points — 2026-05-13 Investigation Session

Issues encountered while using the `coworld` CLI (from `~/coding/metta`) to
investigate guided_bot's performance in the Among Them Daily league.

## 1. League/division IDs required in full UUID form — slugs rejected

`coworld divisions -l among-them-daily` returns HTTP 422. You must use the full
`league_494db37d-d046-4cba-a99a-536b1439262f` form. The `leagues` command shows
both slugs and IDs, but nothing indicates that downstream commands won't accept
slugs. Other commands (`submissions`, `episodes`) silently accept the slug in
some places but not others, making the behavior inconsistent.

**Expected:** Slugs and UUIDs both work wherever an ID is accepted.

## 2. Round IDs are truncated in table output and not copyable

`coworld rounds` shows IDs like `round_eebba5bc-…` — truncated. To use a round
ID with `coworld results ROUND_ID`, you need the full UUID. The only way to get
it is `--json` output + manual extraction. The human-friendly table is useless
for follow-up commands.

**Expected:** Either show full IDs in the table, or accept partial-prefix
matching (the way `git` does with short SHAs).

## 3. `--json` output structure is inconsistent across commands

- `coworld submissions --json` returns a JSON **array**.
- `coworld rounds --json` returns a JSON **object** with an `entries` key.
- `coworld episodes --json` returns a JSON **array**.
- `coworld results ROUND_ID --json` had unclear structure.

This makes scripting painful — you can't assume the shape without trial and
error.

**Expected:** Consistent envelope (`{"entries": [...]}`) or consistently bare
arrays across all list commands.

## 4. `episode-logs --mine` agent numbering doesn't match `episodes` participant positions

The `episodes EREQ_ID --json` response has a `participants` list with
`position` fields and an `assignments` array. It's unclear how to map these
to the `--agent N` numbering used by `episode-logs`. The `--agent` number
corresponds to the actual game slot (the WebSocket `?slot=N` parameter), NOT
the participant list index, NOT the `assignments` array index.

To find our agent's actual game slot, you must use `--mine` to filter, which
returns the correct `policy_agent_N.txt` filename. Without `--mine`, you'd
have to cross-reference `assignments`, `participants.position`, and the game's
internal player naming — and the mapping is non-obvious (position ≠ index ≠
slot ≠ PlayerN naming).

**Expected:** The `episodes` detail should include a clear `slot` field per
participant that directly corresponds to the `--agent N` log index. Or the
results should use policy names instead of `PlayerN`.

## 5. Results use opaque `PlayerN` naming with no mapping to policies

`coworld episode-results` returns names like `Player4`, `Player9` etc. These
correspond to internal game slot numbers, but there's no way to map them back
to policy labels without:
1. Getting the episode detail JSON
2. Understanding the `assignments` array mapping (which is participant-index →
   slot, but participant indices aren't contiguous — they use `position` which
   can be 0,1,2,3,6,7,8,9 skipping values)
3. Correlating with log filenames

**Expected:** `episode-results` should include policy names/labels alongside
or instead of `PlayerN`. Or provide a `--resolve-names` flag.

## 6. `episode-logs --agent N` with wrong N gives another player's logs silently

When I used `--agent 1` thinking it was our agent (based on incorrect position
mapping), I got a completely different bot's logs (an ivotewell Go binary with
rich navigation output). There's no warning that "this log belongs to policy X,
not your policy Y." You only realize the mistake by reading the log content.

**Expected:** When `--mine` is available and `--agent N` doesn't match your
membership, show a warning or at minimum include the policy name in the output
header.

## 7. No way to get aggregate per-policy stats from the CLI

To understand a policy's performance across a round, I had to:
1. List all episodes in the round (`--mine`)
2. For each episode, download logs to determine our actual slot
3. For each episode, get results and find our PlayerN entry
4. Manually aggregate wins/losses/tasks/kills

This required ~100 API calls for one round. There's no
`coworld policy-stats POLICY_VERSION_ID --round ROUND_ID` command that gives
win rate, avg score, task completion, kill rate.

**Expected:** A single command that shows per-policy performance breakdown
for a round or division window.

## 8. No stderr/stdout separation in log capture explanation

The `episode-logs` command shows captured container output, but there's no
documentation about what gets captured (stdout? stderr? both? merged?). In
practice it captures both merged, but initially I filtered out lines starting
with "INFO" thinking they were CLI noise — they were actually our agent's
real Python logging output.

**Expected:** The output should clearly delineate "this is the captured
container output" vs CLI metadata, or prefix CLI noise differently (e.g.,
use a different prefix than the captured `INFO -` lines).

## 9. `coworld rounds ROUND_ID` requires exact full ID but errors are unhelpful

Passing a partial or wrong UUID to `coworld rounds ROUND_ID` gives a raw
HTTP 404 traceback with no suggestion. Same for `coworld results ROUND_ID`.

**Expected:** "Round not found. Did you mean round_c847041a-0602-...?"
or at minimum a clean error message instead of a Python traceback.

## 10. No way to understand the slot/scoring model from the CLI

The Among Them game uses 10 slots (0-9) but only 8 produce scores (2-9).
When our agent is assigned to slot 0 or 1, it runs correctly but gets no
score. The CLI shows these episodes as "completed" with 8 scores, giving no
indication that 2 participants were in dead slots. The `assignments` array
in the episode JSON encodes this, but the semantics aren't documented.

This caused significant confusion — it looked like our agent was "missing"
from 25% of games when in fact it was running fine but in a non-scoring slot.

**Expected:** Either the assignments should never place a participant in a
non-scoring slot (server bug), or the CLI should flag when a participant
has no corresponding score entry.

## Summary

The biggest friction points are:
1. **Opaque ID mapping** (slots, positions, PlayerN names, assignments) — the
   single biggest time sink was understanding which agent is which.
2. **No aggregate stats** — every investigation requires N API calls and manual
   scripting.
3. **Inconsistent JSON shapes** — makes ad-hoc scripting error-prone.
4. **Truncated IDs in tables** — forces `--json` for any follow-up command.
