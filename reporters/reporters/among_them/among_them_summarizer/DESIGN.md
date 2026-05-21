# among_them_summarizer — Design

> **Status:** v1 design (not yet implemented). Built against the D12 zip +
> `render.txt` reporter contract (see
> [`../../../docs/REPORTER_DESIGN.md`](../../../docs/REPORTER_DESIGN.md)).
> Mirrors the shape of
> [`paint_arena_summarizer`](../../paint_arena/paint_arena_summarizer/DESIGN.md),
> the first concrete reporter in the repo — the SDK-extraction candidates
> (`ReporterInputs`, `read_uri`/`write_uri`, `write_deterministic_zip`,
> `EVENT_LOG_SCHEMA`, `write_events_parquet`) are still inline in PaintArena
> and will be inlined again here until the SDK lands. This is reporter #2;
> pain points discovered here feed back into the eventual SDK.

## Purpose

Produce a per-episode human-readable summary, a machine-readable stats blob,
and a per-event event log for the Among Them coworld. Pure function of
`COGAME_RESULTS_URI` + `COGAME_EPISODE_METADATA_URI` + `COGAME_REPLAY_URI`
(plus `COGAME_LOG_URI` if present and well-formed); deterministic within one
pinned `pyarrow` version; no external network access.

The hard constraint that shapes this entire design: the Among Them replay
artifact at `COGAME_REPLAY_URI` is a **binary input-only format**. It records
joins, leaves, per-tick player input bitmasks, and per-tick game-state
hashes — and that is all. It does **not** record kills, votes, meetings,
chat, task completions, bodies, or phase transitions. The rich event stream
exists only as `logGameEvent(...)` text printed to the game container's
stdout; the game does not post to `COGAME_LOG_URI`, so the reporter does not
see it in v1.

The design below is honest about that. It builds a strong summary from
**aggregated per-slot counts** (`COGAME_RESULTS_URI`), **header and join
metadata** (binary replay), and **lightweight derived metrics from the input
stream** (button-press counts, activity profile, disconnect timing). It does
*not* attempt to reconstruct per-event detail (which kill, which vote, which
meeting) — that path requires either a game-side `events.json` artifact or a
Python port of the Nim simulator, and both are out of scope for v1. The gap
is documented in §"Frictions and obstacles" with a concrete path to close it
in a v2.

## Inputs

| Env var | Used? | Why |
| --- | --- | --- |
| `COGAME_RESULTS_URI` | **Yes** | Per-slot aggregates: `names`, `scores`, `win`, `tasks`, `kills`, `imposter`, `crew`, `vote_players`, `vote_skip`, `vote_timeout`. The reporter's primary source of structured per-player facts. |
| `COGAME_REPLAY_URI` | **Yes** | Binary `.bitreplay` (`BITWORLD` magic, format version 3): header with `gameName`/`gameVersion`/timestamp/`configJson`, then records of types `ReplayJoinRecord` (0x03), `ReplayLeaveRecord` (0x04), `ReplayInputRecord` (0x02), `ReplayTickHashRecord` (0x01). Source of player slot/name/color/join-tick/leave-tick, game config (imposter count, kill cooldown, vote timer, map, seed, …), total tick count (last hash tick), and per-player per-tick input bitmasks. |
| `COGAME_EPISODE_METADATA_URI` | **Yes** | `episode_id`, `variant_id`, `started_at`/`ended_at`/`duration_seconds`, `players[].policy_name`. `policy_name` overrides the replay-join `name` for display; the join `name` is the in-game color/address, `policy_name` is the tournament-meaningful identity. |
| `COGAME_LOG_URI` | **No** (v1) | Not consumed. Reporter contract permits it being unset; for Among Them it currently *is* unset because the game does not post log lines to it (it just `echo`s to stdout, and the hosted runner captures container stdout separately). See §"Frictions and obstacles". |
| `COGAME_REPORTER_ID` | Logs only | Stamped into reporter stderr for observability. |
| `COGAME_REPORT_OUTPUT_URI` | **Yes** | Write target for the zip. |

## Output zip (D12)

```
report.zip
├── summary.html        # rendered inline (listed in render.txt)
├── stats.json          # download-only; full per-slot detail
├── events.parquet      # download-only; per-event log (shared schema)
└── render.txt          # single line: "summary.html\n"
```

The renderable-extension allowlist in D12 is `.md`/`.txt`/`.html`/`.htm`;
`stats.json` and `events.parquet` are intentionally outside that allowlist
and stay download-only. Zip-entry mtimes are pinned to
`(1980, 1, 1, 0, 0, 0)` for byte-identical reruns.

### `summary.html` (rendered)

A single self-contained HTML page — inline CSS only, no `<script>` and no
`<link>` — so it renders safely inside Observatory's iframe+CSP sandbox
without external fetches. Sections, top to bottom:

1. **Header.** Episode id, variant, started/ended timestamps, duration
   (`duration_seconds` from metadata; falls back to `last_tick / ReplayFps`
   where `ReplayFps = 24` from `sim.nim`), and a compact config strip:
   imposter count, tasks per player, kill cooldown (seconds, derived from
   `killCooldownTicks / ReplayFps`), vote-timer seconds, map name, seed,
   game version.

2. **Verdict band.** One of:
   - **"Imposters win"** — derived as `any(imposter[i] == 1 and win[i] == 1)`.
   - **"Crewmates win"** — `any(crew[i] == 1 and win[i] == 1)`.
   - **"Draw — time limit reached"** — no `win[i] == 1` (the sim sets every
     `win[i] = false` when `timeLimitReached` is true at finishGame time).
   The badge carries a colored ribbon (red-tinted for imposter win,
   teal-tinted for crew win, gray for draw).

3. **Scoreboard.** One row per player slot with:
   - Color swatch (from the join's slot color config; falls back to the
     PaintArena-style positional palette when the replay didn't assign one).
     The mapping uses Among Them's own `PlayerColorNames`/`PlayerColors`
     table from `sim.nim:105` (16 entries: red, orange, yellow, light blue,
     pink, lime, blue, pale blue, gray, white, dark brown, brown, dark
     teal, green, dark navy, black).
   - Display name: `policy_name` from metadata when present, otherwise the
     replay-join `name` (which is the player's in-game color/address),
     otherwise `"Slot N"`.
   - Role badge: "Imposter" (with dark-red tint) or "Crewmate" (with teal
     tint), from `imposter[i]` / `crew[i]`.
   - Outcome badge: "Won" / "Lost". The reporter intentionally does
     **not** infer whether a losing player died vs. survived without
     a win — that signal is not in the artifacts the reporter sees,
     and any inference would be guess-work. See §Frictions for the
     full rationale.
   - Numeric columns: score, kills, tasks-done / tasks-assigned (assigned
     is `0` for imposters and `config.tasksPerPlayer` for crewmates, both
     read from the replay's `configJson`), votes cast on players, skip
     votes, timeout votes.
   - A per-row activity sparkline: one rect per N-tick bucket
     (default bucket = `ReplayFps * 10`, i.e. 10 seconds), height
     proportional to that bucket's press count normalized to the
     busiest bucket across all slots. Buckets outside the slot's
     `[joined_tick, left_tick]` presence window are dimmed.

4. **Disconnects** (only shown when any leaves occurred before game over).
   Per-disconnect row: player, leave tick, leave time, how many ticks
   remained when they left. The `ReplayLeaveRecord` timestamps come
   straight from the binary replay.

5. **Footer.** Reference to `stats.json` and `events.parquet`,
   episode/reporter id.

The reporter does **not** render a Meetings summary card. While
`results.json` carries per-slot `vote_players` / `vote_skip` /
`vote_timeout` counts (which appear in the scoreboard's numeric
columns), any attempt to aggregate them into a "meetings held" count
is a best-effort inference (every slot may vote once per meeting they
attend, but slots can die before/between meetings) that the reporter
cannot validate without the per-meeting events the game does not
emit. See §Frictions for the full rationale.

Module-level rendering constants (slot color hex map, activity-bucket
size, role-tint hex, bar geometry) live next to the rendering code as
named constants — same style as `paint_arena_summarizer._SLOT_COLORS`.

### `stats.json` (download-only)

```jsonc
{
  "episode_id": "ep_abc123",
  "variant_id": "default",
  "duration_seconds": 412.5,
  "total_ticks": 9903,
  "replay_fps": 24,
  "game_version": "1",
  "config": {
    "min_players": 8,
    "imposter_count": 2,
    "auto_imposter_count": false,
    "tasks_per_player": 8,
    "kill_cooldown_ticks": 900,
    "vote_timer_ticks": 6000,
    "max_ticks": 10000,
    "seed": 679961,
    "map_path": "map.json"
  },
  "verdict": {
    "winner_side": "Crewmate",        // "Imposter" | "Crewmate" | "Draw"
    "time_limit_reached": false,
    "any_winner": true
  },
  "slots": [
    {
      "slot": 0,
      "join_order": 0,                  // connection-order index this slot was assigned at join time
      "policy_name": "evidencebot_v2",  // from episode metadata
      "in_game_name": "red",            // from replay join
      "color_index": 0,
      "color_name": "red",
      "role": "Crewmate",               // null when neither imposter nor crew flag set
      "won": true,
      "score": 108,
      "kills": 0,
      "tasks": 8,
      "tasks_assigned": 8,
      "vote_players": 3,
      "vote_skip": 1,
      "vote_timeout": 0,
      "joined_tick": 0,
      "left_tick": null,
      "input_press_total": 1452,
      "input_press_per_kind": { "up": 312, "down": 290, "left": 188, "right": 201, "select": 102, "attack": 287, "b": 72 }
    }
  ],
  "slot_to_join_order": [0, 1, 2, 3, 4, 5, 6, 7],  // flat slot → connection-order mapping; null entries when no join
  "disconnects": [
    { "slot": 5, "leave_tick": 7124, "leave_seconds": 296.83 }
  ],
  "activity": {
    "bucket_ticks": 240,                // 10s at 24 fps
    "buckets_per_slot": [
      { "slot": 0, "presses_per_bucket": [12, 18, 21, ...] }
    ]
  }
}
```

The order of slots follows the results-JSON slot order (0..N-1). When the
results JSON omits `names` (it's an optional field in
`results_schema`), `in_game_name` falls back to the join-record name and
then to `"Slot N"`. `tasks_assigned` is `0` for imposters and
`config.tasks_per_player` for crewmates; we read this from the
`configJson` embedded in the replay header rather than from any external
source.

**Slot ↔ connection-order mapping.** The `slot` field is the
tournament/results-JSON slot index. `join_order` is the
connection-order index (the index into `sim.players` at the moment of
join — what the replay's `ReplayJoinRecord.player` field carries).
The two often agree but can differ when the game auto-assigns slots
or when players join out-of-order. Downstream ingesters get the
mapping three ways: row-by-row via `slots[i].join_order`, flat via
the top-level `slot_to_join_order`, or by filtering `join` events in
`events.parquet` (which carry both `slot` and `player_index`).

### `events.parquet` (download-only)

Same shared `(ts, player, key, value)` schema as PaintArena
(`EVENT_LOG_SCHEMA` in `paint_arena_summarizer.py`):

| Column | Type | Meaning |
| --- | --- | --- |
| `ts` | int64 | Tick (Among Them ticks; replay records timestamps in ms but the reporter converts to ticks via `tick = ms * ReplayFps / 1000` for parity with PaintArena's `ts = tick`). |
| `player` | int16 | Slot index, or `-1` for global / episode-level facts. |
| `key` | string | Event kind. v1 emits the keys listed below. |
| `value` | string | JSON-encoded payload; structure depends on `key`. |

`key` kinds emitted in v1, with their JSON payload shape:

- **`game_config`** — one row, `ts=0`, `player=-1`. Payload: the
  parsed subset of `configJson` from the replay header — exactly the
  fields the reporter consumes (`seed`, `min_players`, `imposter_count`,
  `auto_imposter_count`, `tasks_per_player`, `kill_cooldown_ticks`,
  `vote_timer_ticks`, `max_ticks`, `map_path`, `slots`). The raw
  configJson the game writes has more fields (motion constants,
  rendering toggles, etc.) which the reporter intentionally drops.
  Included in the parquet so cross-episode aggregators can read the
  per-episode config without fetching `stats.json` separately.
- **`join`** — one row per `ReplayJoinRecord`, `ts=join_tick`,
  `player=slot` (the resolved slot id, not the raw `join.player`).
  Payload: `{"slot", "player_index", "name", "token_present"}`.
  `player_index` is the connection-order index this join was assigned
  to at join time (= the raw `ReplayJoinRecord.player`), so consumers
  can reconstruct the slot ↔ connection-order mapping from the
  parquet alone. The `token` value itself is **not** included (per
  the reporter contract, tokens are episode-scoped secrets and
  reporters that incidentally observe them should not surface them).
- **`leave`** — one row per `ReplayLeaveRecord`, `ts=leave_tick`,
  `player=slot`. Payload: `{"ticks_remaining": int}`.
- **`input_press`** — one row per *button-press transition* (0→1 edge) per
  player per button. `ts=tick`, `player=slot`. Payload:
  `{"button": "up"|"down"|"left"|"right"|"select"|"attack"|"b"}`.
  This is the firehose representation; consumers that want bucketed
  intensity can `GROUP BY (player, ts // bucket_ticks)` in DuckDB / Pandas.
- **`activity_bucket`** — one row per (player, bucket) with non-zero
  presses. `ts = bucket_start_tick`, `player = slot`. Payload:
  `{"bucket_ticks", "presses_total", "presses_by_button":
  {"up":..., "down":..., ...}}`. Redundant with `input_press` but cheap to
  materialize and removes the per-row JSON-parse cost for the common
  "intensity over time" query.
- **`player_summary`** — one row per slot, `ts=last_tick`, `player=slot`.
  Payload: `{"role", "won", "score", "kills", "tasks", "tasks_assigned",
  "vote_players", "vote_skip", "vote_timeout", "policy_name",
  "join_order", "joined_tick", "left_tick", "in_game_name",
  "color_name"}`. Mirrors `stats.json::slots[i]`; included in parquet
  for downstream consumers that want all of episode-level state in
  one columnar source.
- **`game_result`** — one row, `ts=last_tick`, `player=-1`. Payload:
  `{"winner_side", "time_limit_reached", "any_winner", "total_ticks",
  "duration_seconds"}`.

Notably **not** emitted (these are exactly the events that would
require either game-side instrumentation we don't have or
re-simulation — both out of scope; see §Frictions for the v2 path):

- `kill` / `body_reported` / `meeting_called` / `vote_cast` /
  `vote_result` / `vote_chat` / `task_complete` / `vent` /
  `phase_change` / `meetings_held` (any aggregate inference) /
  `likely_dead` (any inference about per-player alive/dead state).

These are listed in §"Frictions and obstacles" with a concrete path to
add them in a v2.

Determinism note (carried over from PaintArena): `pyarrow` stamps a
`created_by` field in the file footer that includes its own version. The
Docker image pins `pyarrow` in `requirements.txt`; two runs of the
*same image* over identical inputs produce byte-identical parquet bytes.
The pytest determinism check exercises this within one process.

## Frame-derived analytics (input-stream only)

### Replay parser

Inline Python parser for the BITWORLD format-version-3 binary, per
`among_them/sim.nim:9-18` and `among_them/replays.nim:148-291`:

```
header := b"BITWORLD"            # ReplayMagic
          u16  format_version    # ReplayFormatVersion == 3
          u16+utf8  game_name    # "among_them"
          u16+utf8  game_version # "1"
          u64       creation_ms
          u16+utf8  config_json  # JSON string

record  := u8 record_type
           ( case 0x01 ReplayTickHashRecord: u32 tick, u64 hash
           | case 0x02 ReplayInputRecord:    u32 time_ms, u8 player, u8 keys
           | case 0x03 ReplayJoinRecord:     u32 time_ms, u8 player, u16+utf8 name, i16 slot, u16+utf8 token
           | case 0x04 ReplayLeaveRecord:    u32 time_ms, u8 player
           )
```

`time_ms` is converted to ticks via `tick = (ms * ReplayFps) // 1000`
with `ReplayFps = 24`. `keys` is the 7-bit input bitmask
(`ButtonUp`=0x01, `ButtonDown`=0x02, `ButtonLeft`=0x04, `ButtonRight`=0x08,
`ButtonSelect`=0x10, `ButtonA` ("attack")=0x20, `ButtonB`=0x40) from
`common/protocol.nim:18-24`. The parser refuses any header where
`game_name != "among_them"` or `format_version != 3`, both of which
should match the existing on-disk constant in `sim.nim`.

Parser implementation lives inline in `among_them_summarizer.py`
(matches PaintArena's "inline primitives" pattern). The parser is the
one piece of this reporter that is *only* useful for Among Them; it is
**not** an SDK-extraction candidate.

### Per-player input metrics

Walk the input records in order, tracking per-player previous bitmask:

```
for record in inputs:
    prev = mask_prev[record.player]   # default 0 before first record
    cur  = record.keys
    edges = cur & ~prev                # bits that just turned on
    for button_bit, button_name in BUTTONS:
        if edges & button_bit:
            press_count[record.player][button_name] += 1
            emit Event(input_press, ts=record.tick, player=record.player,
                       value={"button": button_name})
    mask_prev[record.player] = cur
```

`input_press_total` per slot is the sum across buttons. The
`activity_bucket` events are emitted by bucketing the per-press events
into `bucket_ticks`-wide windows (default 240 ticks = 10 seconds) and
counting per button. Empty buckets are not emitted.

Why edges (0→1) rather than "tick has the bit set": holding a direction
key for 30 ticks shouldn't count as 30 presses. Edge-counting matches
what `sim.nim:4101-4105` already does for menu navigation
(`input.up and not prev.up`) — one transition = one decision.

### Disconnect / present-ticks

For each slot, `joined_tick` is the tick of its first `ReplayJoinRecord`
(slots that never receive a join record have `joined_tick = 0` and the
slot is treated as present from the start of the recording). `left_tick`
is the tick of the slot's `ReplayLeaveRecord`, if any; otherwise `null`.
`present_ticks = (left_tick or last_tick) - joined_tick`. A disconnect
event is "any leave record whose tick is more than `ReplayFps * 5` ticks
before the last hash tick" — we want to flag genuine mid-game
disconnects, not the natural cleanup at episode end.

### Tradeoffs

- **Why count input *transitions* not *ticks-held***: transitions are the
  decision count; a directional hold of 30 ticks is one decision. The
  game itself uses edge detection for menu interactions.
- **Why expose both `input_press` (firehose) and `activity_bucket`
  (rolled-up) in the parquet?** Different downstream queries want
  different shapes. The firehose lets you grep for a specific button at
  a specific tick; the buckets let you draw a heatmap without scanning
  every row.
- **Why a 10-second bucket?** A vote-timer at the default config is
  `voteTimerTicks / ReplayFps = 250 s`; 10-s buckets give ~25 buckets
  per voting window and ~40 over a full 10000-tick game. Tunable as
  `ACTIVITY_BUCKET_TICKS` (module constant) if the default proves wrong.
- **Why not infer phases from inputs?** It's tempting (no movement for
  N consecutive ticks across all live players ≈ meeting) but unreliable:
  bots running idle policies look identical to a paused meeting, and a
  meeting with movement (cursor navigation) also has inputs. We don't
  infer phases; we emit raw counts and let the consumer correlate.
- **Why no `likely_dead` inference?** Whether a losing slot died
  mid-game vs. survived without a win is not in the artifacts the
  reporter sees, and any rule we'd write ("crewmate, lost, team won
  → killed") would be a guess that breaks in edge cases. We don't
  surface what we can't prove. The data that *is* available — `won`,
  `tasks`, `kills`, `vote_players`, `vote_skip`, `vote_timeout`,
  per-slot `input_press_total` — is enough for a reader to form
  their own judgement.
- **Why no aggregate meetings count?** Same reason. The per-slot
  vote counts in `results.json` *do* appear in the scoreboard (those
  are facts), but turning them into "N meetings were held" is an
  inference: every alive slot votes once per meeting they attend, but
  slots can die before or between meetings. The reporter doesn't
  emit a meetings-held count, a meetings card, or any field that
  aggregates across the per-slot vote totals.

## Decisions locked in

1. **Aggregates-first, no event reconstruction.** v1 builds the entire
   summary from `results.json` per-slot aggregates plus the binary
   replay's header + joins/leaves + input streams. Per-event detail
   (kill victims, vote ballots, meeting transcripts) is **out of scope**
   for v1 because the binary replay does not carry it and the game does
   not post the rich event log to `COGAME_LOG_URI`. Closing that gap is
   a v2 question handled in §"Frictions and obstacles".
2. **Inline binary replay parser.** Same approach as PaintArena's inline
   primitives: the `.bitreplay` v3 reader lives in
   `among_them_summarizer.py`, not in `reporter_sdk`. Rationale: the
   format is Among Them-specific (per D11, replay format is game-owned),
   and the SDK-extraction rule from the root README is "wait for a real
   second consumer." Even if `among_them_highlight_reel` becomes a real
   consumer later, two callers is the right time to lift, not now.
3. **Generic over slot count.** Among Them runs 1–16 slots
   (`results_schema.minItems = 1`, `maxItems = 16`). Iterate every
   array; do not hard-code 8.
4. **`policy_name` ⟶ display, replay `name` ⟶ in-game identity.**
   The episode-metadata `policy_name` is what humans recognize at the
   tournament level (e.g. `"evidencebot_v2"`); the replay-join `name` is
   what the running game called them (typically the player's connection
   address). Show both, with `policy_name` prominent.
5. **Color from join slot config, with a fallback palette.**
   `configJson.slots[i].color` may set a fixed color per slot; when
   absent, the game-side auto-assigns from `PlayerColors`. The reporter
   mirrors that order and uses the 16-entry palette directly, so the
   colors in the HTML match what a viewer of `among_them`'s
   `/clients/global` would have seen.
6. **HTML, not Markdown.** Same rationale as PaintArena: once the
   summary needs colored swatches, role badges, and small per-player
   activity sparklines, raw HTML with inline SVG is the simpler
   primitive than fighting Markdown's renderer. Page is
   self-contained for the iframe+CSP sandbox.
7. **Shared event-log schema.** `events.parquet` uses the same
   `(ts, player, key, value)` schema as
   `paint_arena_summarizer::EVENT_LOG_SCHEMA`. Cross-coworld aggregation
   is a future possibility; sharing the schema now is cheap. `player =
   -1` for global facts (`game_config`, `game_result`).
8. **Pinned mtime for zip determinism.** All zip entries use
   `date_time = (1980, 1, 1, 0, 0, 0)`, matching D12.
9. **`token` is parsed but never written.** The reporter reads each
   `ReplayJoinRecord.token` string (because the format requires it),
   then drops it from every output. The `join` parquet event emits
   `"token_present": true|false` only.
10. **`COGAME_LOG_URI` is not consumed in v1**, even when set. The
    only thing we'd parse out of it is the `logGameEvent` text stream,
    and the brittleness of grepping prose ("`red killed by blue
    (imposter)`") for canonical event data is enough to defer to a v2
    that takes a structured input. See §"Frictions and obstacles".

## Failure-mode behavior

| Situation | Behavior | Exit |
| --- | --- | --- |
| All inputs valid, normal episode | Write zip with `summary.html`, `stats.json`, `events.parquet`, `render.txt`. | 0 |
| Imposter team wins | Verdict: "Imposters win"; ribbon red-tinted; surviving imposter rows marked "Won". | 0 |
| Crewmate team wins by tasks | Verdict: "Crewmates win"; ribbon teal-tinted; HTML notes "tasks completed" when total tasks across crew equals `crew_count * tasks_per_player`. | 0 |
| Crewmate team wins by vote (all imposters ejected) | Verdict: "Crewmates win"; HTML cannot distinguish task-win from vote-win without per-event detail and labels the win condition "tasks or ejection" with a footnote. | 0 |
| Draw — time limit reached | Verdict: "Draw — time limit reached"; `verdict.any_winner == false`. All slots' `won` is false. | 0 |
| Single-slot certification fixture (`tasksPerPlayer:1`, `maxTicks:300`) | Writes a valid zip; activity strip will be short but well-formed; no disconnects shown. | 0 |
| Player disconnects mid-game | A `ReplayLeaveRecord` ≥ 5 s before the last hash tick → row in §Disconnects; their activity strip dims at the leave tick. | 0 |
| Player never receives a join record (rare; happens when the replay starts mid-episode) | Treated as present from tick 0; activity strip starts at 0. A future revision could detect this and warn, but it does not crash the reporter. | 0 |
| Replay magic mismatch (not `BITWORLD`) or version != 3 | `ValueError("unexpected replay format")` propagates; the reporter exits 1 (`nonzero_exit` per D8); no zip is written. | 1 |
| Replay truncated mid-record | Parser raises `EOFError`; exit 1. | 1 |
| Results JSON missing the required `scores` field, or any present array shorter than the slot count derived from join records | `ValidationError`; exit 1. | 1 |
| Output URI unreachable | Bubble up exception; exit 1. | 1 |

Per D8, the platform surfaces these as `nonzero_exit` records. The
reporter never writes a synthetic "I failed" zip — it either writes a
valid zip and exits 0, or exits non-zero.

## Inline primitives (extraction candidates)

Same shopping list as PaintArena, plus one Among-Them-specific item that
is **not** an extraction candidate:

- `ReporterInputs` + `load_reporter_inputs()` — SDK candidate.
- `read_uri` / `write_uri` / `read_json` — SDK candidate.
- `write_deterministic_zip(entries)` — SDK candidate.
- `EVENT_LOG_SCHEMA` + `write_events_parquet(rows)` — SDK candidate.
- `parse_bitreplay(bytes) -> BitReplay` — **not** an SDK candidate
  (game-owned format per D11). Stays in `among_them_summarizer.py`
  forever, the same way PaintArena's frame-parsing stays in
  `paint_arena_summarizer.py`.

When the SDK extraction pass happens, all five PaintArena candidates
should also serve this reporter unchanged. If something doesn't (likely:
a tweak to how `EVENT_LOG_SCHEMA` is built when a reporter has a lot of
JSON-payload events), that pain point feeds back into the SDK.

## Determinism and testing

Output is a pure function of (results JSON, episode metadata JSON,
binary replay bytes) within one pinned `pyarrow` version. Test plan:

- **Replay parser unit tests** with hand-crafted byte fixtures covering:
  the four record types in mixed order, multi-byte UTF-8 names, the
  v3-only format-version check, magic-mismatch, truncated-record,
  empty-replay (header only, no records).
- **Input-edge detection** tests: a held key for N ticks counts as one
  press; release-and-re-press counts as two; multiple simultaneous
  buttons each generate one transition.
- **Disconnect classification**: leave at last_tick → not flagged;
  leave at last_tick - 6 s → flagged.
- **Slot ↔ connection-order mapping**: `SlotStats.join_order` is the
  `ReplayJoinRecord.player` index that joined into that slot;
  `stats.slot_to_join_order[i]` matches; the `join` parquet event
  payload carries both `slot` and `player_index`.
- **Verdict derivation** against hand-crafted results JSONs (imposter
  win, crewmate win, draw, plus the rare "no slot has `crew == 1` and
  no slot has `imposter == 1`" malformed-results case).
- **Zip-shape assertions**: entries are exactly
  `{summary.html, stats.json, events.parquet, render.txt}`;
  `render.txt` is `summary.html\n`; pinned mtimes; no duplicates;
  `render.txt` does not list itself.
- **Determinism**: two runs over the same inputs produce byte-identical
  zip bytes.
- **Containerized smoke** (`smoke.sh`, mirrors PaintArena): build the
  image, run against checked-in `smoke/fixtures/` (a small real `.bitreplay`
  + results + metadata), assert the four-entry contract and that the
  HTML page contains every player's display name.

## Frictions and obstacles

Surfaced explicitly so a future reader (human or coding agent) knows
what made this design shape the way it did, and which of them are worth
investing in to unlock a v2.

### 1. The binary replay carries no per-event data

This is the dominant constraint. `.bitreplay` is an *input-replay*
format — joins, leaves, per-tick input bitmasks, and tick hashes. The
game's actual events (kills, votes, meetings called, votes cast,
meeting outcomes, tasks completed, bodies reported, vents used, chat
messages, role reveals, phase transitions) exist as derived state
inside the running simulator, not as records in the replay.

Reconstructing per-event detail from `.bitreplay` alone requires
**re-executing the Among Them simulator** with the recorded inputs.
That simulator is ~4000 lines of Nim
(`among_them/sim.nim`) coupled to a custom map format, framebuffer
rendering, and sprite-collision logic. Porting it to Python for the
reporter would be a large project, fragile (every Nim sim change would
silently break the reporter unless caught by hash-mismatch tests), and
philosophically dubious — we'd be duplicating the game.

**v2 path A — Game writes a structured events file alongside the replay.**
Cheapest path to per-event detail. Add a `--save-events <uri>` flag to
`among_them.nim` and a `COGAME_SAVE_EVENTS_URI` env var; emit one
JSON-line per `logGameEvent` call site, structured rather than prose:

```jsonc
{"tick": 4123, "kind": "kill", "killer_slot": 3, "victim_slot": 5}
{"tick": 4197, "kind": "vote_called", "caller_slot": 0, "reason": "body", "body_color": "red"}
{"tick": 4198, "kind": "vote_chat", "speaker_slot": 2, "text": "red sus"}
{"tick": 4451, "kind": "vote_cast", "voter_slot": 0, "target_slot": 5}
{"tick": 4480, "kind": "vote_result", "ejected_slot": 5, "tied": false, "skip_won": false}
{"tick": 4612, "kind": "task_complete", "player_slot": 0, "task_index": 2}
{"tick": 9903, "kind": "game_over", "winner": "Crewmate", "time_limit": false}
```

The reporter would consume that file (via a new `COGAME_EVENTS_URI`
input env, or by detecting an `events.jsonl` inside the existing replay
artifact) and emit the rich `kill`/`vote_cast`/`vote_result`/`task_complete`
keys into `events.parquet`, plus a meetings-by-meeting breakdown in the
HTML summary. **This is the recommended v2 path.** Estimated game-side
cost: < 1 day of work in `among_them/sim.nim` (one new file, sprinkled
emit calls next to the existing `logGameEvent` sites).

**v2 path B — Reporter parses container stdout.**
The platform-side hosted runner captures container stdout. If the
runner is willing to write captured game stdout to a URI the reporter
sees (e.g. populate `COGAME_LOG_URI` from container logs even when the
game itself didn't post there), the reporter could parse the
`logGameEvent` prose. Brittle (the strings are not stable contract:
"`red killed by blue (imposter)`" could trivially become "`Red was
killed by Blue`"), but no game-side change required. Recommended only
if path A is blocked.

**v2 path C — Port the sim.** Last resort. Not recommended.

### 2. Player identity has three names

`policy_name` (episode metadata, tournament-meaningful), replay-join
`name` (in-game address/color, e.g. `"red"`), and `slots[i].name` from
the config JSON (rarely set). The HTML prefers `policy_name`, then the
join name, then `"Slot N"`. The stats.json carries all three so a
downstream consumer can pick. This is annoying but unavoidable; the
PaintArena reporter has a similar `policy_name` + `"Slot N"` fallback.

### 3. Color assignment is partial

Among Them assigns colors at game start time based on `slots[i].color`
in the config (when set) plus auto-assignment from `PlayerColors`
otherwise. The auto-assignment order is deterministic given the seed,
but the reporter doesn't run the sim, so it can only show a color when
the config explicitly set one. Practical mitigation: use the positional
default palette (`PlayerColors[i % 16]`) when the config didn't set a
color. The HTML's swatch then matches the *probable* in-game color in
the common configured-roster case and is a reasonable visual proxy
otherwise.

### 4. "Was this player killed?" — not surfaced

The results JSON carries `win` per slot but not `alive` per slot. A
losing crewmate could be dead or alive-when-imposters-won; a losing
imposter could be voted out or alive-when-crewmates-won-by-tasks.
**The reporter does not infer.** Earlier drafts surfaced a
`likely_dead` boolean derived from team outcome ("crewmate, lost,
crew won → killed"); that rule was removed because (a) the inference
fails for crew-by-tasks wins where imposters lose but aren't
ejected, and (b) the reporter shouldn't claim per-slot facts it
can't prove. The data that *is* available — `won`, `tasks`,
`kills`, vote counts, input-press totals — is enough for a reader
to form their own judgement; we don't pre-bake it.

Closing this gap would require either path A from §1 (game writes
a structured per-tick events.jsonl) or an `alive` array added to
the results schema.

### 5. Meetings count — not surfaced

For the same reason: every alive slot votes once per meeting they
attend, but slots can die before or between meetings. An aggregate
"meetings held" count derived from per-slot `vote_players +
vote_skip + vote_timeout` is a bounded estimate, not a fact. Earlier
drafts surfaced this as a meetings card; it was removed for the same
reason as `likely_dead`.

The per-slot `vote_players` / `vote_skip` / `vote_timeout` counts
remain in the scoreboard — those are facts from the results JSON.
What's *not* in any output is any field that pretends to know how
many meetings the game held overall.

Closing this gap also requires path A from §1.

### 6. The replay format is version 3 today, with no compatibility guarantees

`sim.nim:13` sets `ReplayFormatVersion = 3'u16`. Earlier replays would
not load. The parser checks the version up-front and refuses
non-`v3` replays with a clear error; when v4 lands, the reporter will
have to track it explicitly. Practical mitigation: a version-bump in
the game is a coordinated change that should ship a reporter PR in the
same window.

### 7. The metadata `players[].slot` may or may not align with the replay's `slot`

Episode metadata's `players[]` carries `slot` + `policy_name` per the
v1 strawman in `REPORTER_DESIGN.md`; the replay's `ReplayJoinRecord`
carries an `i16 slot` field per `replays.nim:191`. These are intended
to be the same numbering, but PaintArena's experience suggests
defensive lookup keyed on slot: build a `metadata_by_slot[s]` dict and
fall through `None` rather than indexing, in case a future Among Them
change reorders slots.

### 8. We can't compare or rank policies fairly from a single episode

Among Them rewards depend heavily on which side you got assigned to
(imposter scoring caps at fewer events than crewmate scoring,
empirically). A per-episode reporter inherently shows one game; any
"who's the best policy" judgement requires cross-episode aggregation,
which is explicitly out of scope per `REPORTER_DESIGN.md`'s D1 and §3.
The HTML therefore does **not** include any leaderboard-style ranking
across slots; it surfaces per-slot outcome, score, and role, and lets
the reader form judgements. This is mostly a *content* friction, not a
*technical* one — but worth calling out so the reporter doesn't grow a
"score / kills" sort that implies a ranking we can't justify.

## Non-goals (v1)

- No reading of `COGAME_LOG_URI` (Among Them doesn't post to it, and
  parsing prose log lines is the wrong long-term shape — see §1 path B).
- No external network calls beyond input/output URIs (D1 purity).
- No simulator re-execution. No Python port of Among Them's `sim.nim`.
- No LLM-based narrative synthesis. (The repo's `among_them_highlight_reel`
  scaffold is a candidate for that work; this reporter is the deterministic
  twin.)
- No interactive replay scrubber in HTML. The parquet exists for tools
  that want to do that.
- No platform-side schema declaration of `stats.json` (D7 shelved this).
- No cross-episode aggregation (D1 / §3 of `REPORTER_DESIGN.md`).
- No leaderboard / policy-ranking surfaces in HTML — see §Frictions item 8.

## Open questions

*None blocking for v1. Items that may surface during implementation:*

- Does the activity-bucket size of 10 s look right on a real 8-player
  Among Them episode? Tune `ACTIVITY_BUCKET_TICKS` after the first
  rendered fixture. (Initial validation against a real 10000-tick
  game produced ~40 buckets — feels right; revisit if visual density
  is off.)
- When `COGAME_EVENTS_URI` lands (path A of §Frictions item 1), do we
  push the rich `kill`/`vote_*`/`task_complete` keys into this reporter
  or fork a `among_them_summarizer_v2`? Default: extend in place,
  guarded on URI presence. Add when the input exists.

## Implementation phases

Eight phases. Each phase is independently reviewable (small enough to
land as one PR) and ends with a concrete verification step. Earlier
phases do not depend on later ones — if a later phase is descoped or
delayed, the work before it still produces a usable reporter. Phases
1–2 alone already ship something the platform will accept as a valid
reporter; everything after that is depth.

The order is chosen so that **the binary replay parser doesn't block
the aggregate-driven scoreboard**: phase 2 produces a useful HTML
summary using results-JSON only, before the binary format work
starts.

> **Current status (2026-05-20):** phases 1–5 are landed on the
> `among-them-summarizer-phase-1` branch (not yet on `main`), plus
> one design-correction commit that removed the `likely_dead` and
> meetings inferences described in §Frictions #4 and #5 and added
> the explicit slot ↔ connection-order mapping (`SlotStats.join_order`,
> `AmongThemStats.slot_to_join_order`, `join` event payload's
> `player_index`). Validated end-to-end against two real
> `.bitreplay` captures from `nottoodumb`-vs-`nottoodumb` games.
> Phases 6 (determinism + zip-contract tests), 7 (Dockerfile +
> smoke), and 8 (README) remain.

### Phase 1 — Skeleton: I/O contract round-trip

**Goal.** A reporter that loads its env URIs, reads no input content,
writes a valid D12 zip containing only `render.txt`, and exits 0.

**Scope.**
- Fill in `among_them_summarizer.py` with the inline-primitives shopping
  list from PaintArena (verbatim copy is fine; SDK extraction comes
  later): `ReporterInputs`, `load_reporter_inputs`, `read_uri`,
  `write_uri`, `read_json`, `write_deterministic_zip`.
- A no-op `run(inputs)` that writes `write_deterministic_zip([
  ("render.txt", b"")])` to the output URI.
- `pyproject.toml`/`requirements.txt` pinning at parity with
  `paint_arena_summarizer/requirements.txt` (`pydantic`, `requests`,
  `pyarrow` — pyarrow gets used in phase 4 but pinning it now avoids a
  later dependency churn).
- `tests/test_skeleton.py`: invokes `run()` with a tmpdir-backed
  `file://` URI and asserts the output is a readable zip with one
  `render.txt` entry.

**Deliverable.** `uv run pytest reporters/among_them/among_them_summarizer/tests/`
passes with the skeleton test.

**Dependencies.** None.

### Phase 2 — Aggregates path: usable HTML and stats.json from results.json alone

**Goal.** Open the zip and see a readable scoreboard, derived purely
from `COGAME_RESULTS_URI` + `COGAME_EPISODE_METADATA_URI`. No binary
replay parsing yet. The replay URI is read but treated opaquely (we
peek only at its `configJson` header for `imposterCount` /
`tasksPerPlayer` / `voteTimerTicks` etc. — see phase 2 sub-task).

**Scope.**
- Pydantic models: `AmongThemResults` (all results-schema fields:
  `names`, `scores`, `win`, `tasks`, `kills`, `imposter`, `crew`,
  `vote_players`, `vote_skip`, `vote_timeout`), `EpisodeMetadata`,
  `AmongThemStats`, `SlotStats`, `GameConfig` (the subset we consume),
  `VerdictBlock`.
- **Replay header-only parser.** A trimmed version of the full parser
  that reads the BITWORLD magic, version, game name/version, timestamp,
  and `configJson` — and stops. Total LOC ≈ 30. Returns `GameConfig`
  parsed from `configJson`. Full record parsing is phase 3.
- `derive_verdict(results)` → `VerdictBlock` covering Imposter/Crew/Draw.
- `build_slot_stats(results, metadata, config)` → `list[SlotStats]`
  with `policy_name`, `in_game_name=None`, `joined_tick=0`,
  `left_tick=None`, role/won/score/kills/tasks/votes filled.
  (`in_game_name`, `joined_tick`, `left_tick`, `join_order` remain
  placeholders until phase 3.)
- Minimal HTML rendering: header, verdict band, scoreboard table.
  Inline CSS (~80 lines). **No** color swatches, **no** activity bars
  yet — those need the full palette and the per-slot input metrics
  from phase 4. Use plain badges and a CSS background-color for role
  tinting so the page still looks reasonable.
- `stats.json` written with everything we have so far (slot rows have
  null `joined_tick`/`left_tick`/`input_press_total`/`buckets`).
- `events.parquet` written with just three keys: `game_config`,
  `player_summary` (one per slot, without input metrics),
  `game_result`. `tick` for `game_result` is `0` for now (phase 3 fills
  in `last_tick`).
- `render.txt` lists `summary.html`.

**Tests.**
- Verdict derivation: 3 fixtures (imposter win, crew win, draw),
  asserting the right `winner_side`.
- Slot stats: generalized over slot count (4 slots, 8 slots, 16 slots).
- Zip-shape: 4 entries (`summary.html`, `stats.json`,
  `events.parquet`, `render.txt`); `render.txt` is `summary.html\n`;
  every listed path exists and has a renderable extension.
- HTML contains every player's display name (smoke-grade assertion).

**Deliverable.** A user can run the reporter against a real
results.json + metadata.json + (any valid v3 .bitreplay header),
open the zip's `summary.html`, and see who won and a scoreboard.

**Dependencies.** Phase 1.

### Phase 3 — Full binary replay parser

**Goal.** Parse every record type in the `.bitreplay` v3 format,
populate `joined_tick` / `left_tick` / `in_game_name` /
`color_index` per slot, populate `total_ticks`, and emit `join` /
`leave` events into `events.parquet`.

**Scope.**
- Promote the phase-2 header-only parser to a full `parse_bitreplay`
  returning a `BitReplay` dataclass with `header`, `joins: list[Join]`,
  `leaves: list[Leave]`, `inputs: list[Input]`, `hashes: list[Hash]`.
  Strict on magic and version (refuse anything that isn't
  `BITWORLD` / version 3).
- `tick_from_ms(ms) = ms * REPLAY_FPS // 1000` helper with
  `REPLAY_FPS = 24` as a named constant. `last_tick = hashes[-1].tick`.
- Wire join records into `SlotStats.in_game_name` / `joined_tick` /
  `color_index` / `color_name` (from the `PlayerColorNames` table
  literal — 16 entries copied verbatim from `among_them/sim.nim:123`).
- Wire leave records into `SlotStats.left_tick` and the disconnect
  list (only flagged when `last_tick - leave_tick > REPLAY_FPS * 5`).
- `events.parquet` gains the `join` and `leave` keys; `game_result`'s
  `ts` becomes `last_tick`; `game_result.value.total_ticks` and
  `duration_seconds` populate properly.
- `token` is parsed (the format requires reading it) and immediately
  dropped — never written into any output. The `join` event payload
  carries `token_present: bool` only.

**Tests.**
- Magic mismatch raises; version != 3 raises; truncated record raises.
- All four record types in mixed order — round-trip-style fixture.
- Multi-byte UTF-8 names in `name` strings.
- `tick_from_ms` boundaries (24 ms → 0, 42 ms → 1, etc.).
- `last_tick` from the last hash record.
- Disconnect classification: leave ≥ 5 s before end → flagged;
  leave at last_tick → not flagged.
- Slot 7 leaves while slots 0-6 don't → only slot 7's `left_tick`
  populates.

**Deliverable.** `stats.json::slots[i].joined_tick` / `left_tick` /
`in_game_name` / `color_name` are populated; the disconnects section
of the HTML shows real values when a disconnect occurred; the parquet
has `join` / `leave` rows.

**Dependencies.** Phase 2.

### Phase 4 — Input-stream analytics: presses, activity buckets, intensity bars

**Goal.** Per-player input metrics drive (a) the per-slot `input_press_*`
fields in `stats.json`, (b) the `input_press` and `activity_bucket`
keys in `events.parquet`, and (c) the activity sparkline in the HTML.

**Scope.**
- `extract_input_presses(replay)` — walk inputs in time order, track
  `mask_prev[player]`, detect `edges = cur & ~prev` per record, emit
  `(tick, player, button_name)` for each set edge bit. The 7 button
  names mirror `common/protocol.nim:18-24`:
  `up`/`down`/`left`/`right`/`select`/`attack`/`b`.
- `bucket_presses(presses, bucket_ticks)` — group by
  `(player, tick // bucket_ticks)`, count total + per button, emit one
  `activity_bucket` row per non-empty bucket. `ACTIVITY_BUCKET_TICKS`
  is a module constant defaulting to `REPLAY_FPS * 10` (= 240; 10 s
  buckets).
- Wire `input_press_total` and `input_press_per_kind` into
  `SlotStats`.
- `events.parquet` gains `input_press` and `activity_bucket` keys.
- Module constant `BUTTONS = (("up", 0x01), ("down", 0x02), ...)`
  copied from `protocol.nim`.

**Tests.**
- Held key for N ticks → one press; release-and-re-press → two.
- Multiple simultaneous button transitions in one record → one press
  per set edge bit.
- Activity bucket aggregation: a known input stream produces the
  expected counts.
- `input_press_total` matches `sum(input_press_per_kind.values())`.
- Empty input stream → no `input_press` rows, no `activity_bucket`
  rows, `input_press_total == 0`.

**Deliverable.** `stats.json::slots[i].input_press_total` is non-zero
on a real fixture; `events.parquet` has `input_press` + `activity_bucket`
rows; the HTML scoreboard's activity column shows differentiated bars
across slots.

**Dependencies.** Phase 3.

### Phase 5 — HTML polish: palette, role badges, activity SVG, disconnects, footer

**Goal.** The HTML matches the §`summary.html` (rendered) section of
this design. Inline CSS only; no `<script>`, no `<link>`.

**Scope.**
- Inline `AMONG_THEM_COLORS` constant: the 16-entry palette with hex
  values. Map from the `PlayerColorNames` index to a CSS hex string.
- Color swatch component (mirrors PaintArena's `_slot_swatch`).
- Role badges: "Imposter" / "Crewmate", tinted via inline style.
- Outcome badge: "Won" / "Lost" only — no per-slot alive/dead
  inference (see §Frictions #4).
- Verdict ribbon: red/teal/gray tinting per `winner_side`.
- Per-row activity sparkline: small `<svg viewBox>` with one `<rect>`
  per bucket, height proportional to that bucket's count normalized
  to the busiest bucket across all slots. Dimmed segments before
  `joined_tick` and after `left_tick`.
- Disconnects table (only rendered when `disconnects` is non-empty).
- Footer with episode/reporter id and references to `stats.json` /
  `events.parquet`.
- `_HTML_CSS` constant (lift the PaintArena structure; rewrite the
  scoreboard / activity / disconnects rules).

**Tests.**
- `summary.html` parses as well-formed HTML (use `html.parser` or
  `lxml` if added to requirements — prefer stdlib).
- No `<script` and no `<link` substrings (self-containment).
- Contains every slot's display name.
- Contains a swatch element for every slot.
- Verdict ribbon contains the right text for known fixtures.

**Deliverable.** Visual review by opening `summary.html` in a browser
from a real fixture; the verdict, scoreboard, and (if any)
disconnects cards are clearly distinguishable, and per-row activity
sparklines show meaningful per-slot variation.

**Dependencies.** Phases 2, 3, 4 (palette needs phase 3; activity SVG
needs phase 4).

### Phase 6 — Determinism + zip contract assertions

**Goal.** Byte-identical reruns over identical inputs; render.txt is
valid per D12 (no self-reference, every path exists, every extension
on the allowlist).

**Scope.**
- All zip entries already use `write_deterministic_zip` from phase 1,
  so mtime pinning is in place. This phase is largely tests.
- `_stable_json` everywhere we serialize JSON-in-parquet (cribbed from
  PaintArena).
- `render.txt` validation helper: every line is a path inside the zip;
  every path's extension is in `{.md, .txt, .html, .htm}`;
  `render.txt` does not list itself.

**Tests.**
- Two-run byte-identical determinism over identical inputs (matches
  PaintArena's `test_run_is_byte_identical_on_rerun`).
- `render.txt` consistency assertions (no self-reference, allowlist).
- Pinned mtime check on every zip entry.
- `events.parquet` parquet metadata is stable across runs (same
  pyarrow version → same `created_by` footer).

**Deliverable.** Determinism + render.txt tests green.

**Dependencies.** Phases 1–5 (all the output writers must exist).

### Phase 7 — Container: Dockerfile, build.sh, smoke.sh, smoke fixtures

**Goal.** A buildable image that runs end-to-end against a checked-in
fixture set and asserts the four-entry contract.

**Scope.**
- `Dockerfile` and `Dockerfile.dockerignore` cribbed verbatim from
  PaintArena (build context is `reporters/`, allowlist style
  dockerignore).
- `build.sh` cribbed from PaintArena; default tag
  `among-them-summarizer:latest`, default platform `linux/amd64`.
- `smoke/fixtures/`:
  - `results.json` — a real 8-player results blob (can be synthesized
    by hand or captured from a local `among_them.nim` run).
  - `metadata.json` — synthesized to match.
  - `replay.bitreplay` — a small real binary replay; the simplest
    source is to run `among_them.nim` with `tasksPerPlayer:1`,
    `maxTicks:300` (the certification fixture) against the
    `nottoodumb` baseline player and capture
    `COGAME_SAVE_REPLAY_URI`. Commit the resulting bytes.
- `smoke.sh` mirrors PaintArena's: build the image, mount fixtures +
  a `mktemp -d` output dir, run the container, assert the four-entry
  zip contract, assert `render.txt` lists `summary.html`, assert HTML
  self-containment.

**Tests.**
- `smoke.sh` exits 0 on a clean clone.

**Deliverable.** `./smoke.sh` passes; the produced
`summary.html` is human-readable when opened.

**Dependencies.** Phases 1–6.

### Phase 8 — README

**Goal.** Per-reporter README in the same shape as
`paint_arena_summarizer/README.md`.

**Scope.**
- What artifacts are produced (the 4-entry table, copied from the
  Output zip section of this design).
- Inputs table (env vars + which are consumed).
- Failure modes table (copied from this design).
- Local-run command (`COGAME_*=file://... python
  among_them_summarizer.py`).
- Build / smoke / test invocations.
- SDK-extraction-candidates section (same list as PaintArena, with the
  added note that the `parse_bitreplay` parser is **not** a candidate).

**Tests.** None — docs only. A spot-check that the commands shown
actually run.

**Deliverable.** README parses, all links resolve.

**Dependencies.** Phases 1–7 (the README documents the shipped
behavior).

### Phase ordering and parallelism

The hard ordering is **1 → 2 → 3 → 4 → 5 → 6 → 7 → 8**. Phases 2
and 3 are tempting to do in parallel since the parser is independent
of the aggregates pipeline, but the parser's output is consumed by
phase 2's slot rows (the `in_game_name` field), so keeping them serial
keeps the integration cost on the parser PR rather than spreading it.

Phases 7 and 8 can land in either order after phase 6. Phase 6 has the
smallest LOC budget (mostly tests) and may sensibly fold into the tail
end of phase 5's PR if the determinism work is small.

### Out-of-band: when to extract `reporter_sdk`

Not a phase of this reporter. The repo-level rule (`README.md`,
"Build strategy") is: extract the SDK after a *second* concrete
reporter exists. This reporter is reporter #2 (PaintArena was #1), so
**the SDK extraction is the work to schedule immediately after phase
8 lands** — not before, not interleaved. The inline primitives lifted
to the SDK should be exactly the ones marked SDK-candidates in this
file's §"Inline primitives" section.
