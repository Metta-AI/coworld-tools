# among_them_summarizer

Per-episode summarizer reporter for the Among Them coworld. Reads results, episode metadata, and the binary `.bitreplay` (full v3 record stream); writes a zip containing a self-contained HTML summary, a JSON stats file, a per-event Parquet event log, and a `render.txt` manifest per the D12 reporter contract. Second concrete reporter in the repo — its inline primitives (HTTP I/O, deterministic-zip writer, shared event-log schema) are the source material for the upcoming [`reporter_sdk`](../../reporter_sdk/) extraction alongside [`paint_arena_summarizer`](../../paint_arena/paint_arena_summarizer/). See [`DESIGN.md`](DESIGN.md) for the locked-in design and phase plan.

> **Status:** phases 1–5 + a design-correction commit landed on the `among-them-summarizer-phase-1` branch. Phases 6 (determinism + zip-contract tests), 7 (Dockerfile + smoke), and 8 (this README, in expanded form) remain. Validated end-to-end against two real `.bitreplay` captures from `nottoodumb`-vs-`nottoodumb` games.

## Output zip contents

```
report.zip
├── summary.html        # rendered inline (listed in render.txt)
├── stats.json          # download-only (referenced from HTML footer)
├── events.parquet      # download-only; shared (ts, player, key, value) event log
└── render.txt          # single line: "summary.html\n"
```

| Entry | Renderable? | Contents |
| --- | --- | --- |
| `summary.html` | yes (`.html` in D12 allowlist) | Self-contained HTML page: header strip with episode + game config; verdict ribbon (Imposters win / Crewmates win / Draw); scoreboard with per-slot color swatch (16-color in-game palette), role badge, Won/Lost, score, kills, tasks-done / tasks-assigned, vote counts, and an activity sparkline SVG; disconnects table (only when any mid-game leaves occurred); footer with episode/reporter info. Inline CSS only — no `<script>`, no `<link>` — safe inside an iframe+CSP sandbox. |
| `stats.json` | no (download-only) | `{episode_id, variant_id, duration_seconds, total_ticks, replay_fps, game_version, config, verdict, slots[], slot_to_join_order, disconnects[], activity}`. See [`DESIGN.md`](DESIGN.md) §`stats.json` for the full field set. |
| `events.parquet` | no (download-only) | Per-event log in the shared `(ts: int64, player: int16, key: string, value: string)` schema. Keys emitted: `game_config` (one row, ts=0), `join` / `leave` (one per replay record), `input_press` (one per 0→1 button-press transition), `activity_bucket` (one per non-empty (slot, 10-second window) aggregate), `player_summary` (one per slot, ts=last_tick), `game_result` (one row, ts=last_tick). `value` is a JSON document; consumers `json.loads` per row. |
| `render.txt` | n/a (the manifest itself) | `summary.html\n` |

The reporter is generalized over slot count (Among Them's `results_schema` allows 1–16 players); the 8-player default-variant config is the common case but nothing assumes it. Zip entries pin `date_time` to `(1980, 1, 1, 0, 0, 0)` so byte-identical reruns over identical inputs produce byte-identical zips (D12 determinism). Within one pinned `pyarrow` version the parquet bytes are deterministic too — the requirements.txt pin is what makes that hold across reruns of the same image.

### What the reporter intentionally does NOT surface

The artifacts the reporter sees (results JSON + binary `.bitreplay` + episode metadata) carry per-slot aggregates and per-tick player inputs, but **not** the rich event stream a viewer of the running game would see. The reporter does not infer:

- Per-player alive/dead state. The results JSON has `won` per slot, not `alive`. A losing crewmate may be dead or alive-when-imposters-won; a losing imposter may be voted out or alive-when-crew-won-by-tasks. We don't guess.
- Meetings held. Per-slot `vote_players` / `vote_skip` / `vote_timeout` counts are in the scoreboard (those are facts from the results JSON), but the reporter does not aggregate them into a "meetings held" total — slots can die before/between meetings, making any aggregate a bounded estimate rather than a fact.
- Per-event detail of kills, votes cast, body reports, chat, task completions, vents, phase transitions. Those exist in the game's stdout text (`logGameEvent` calls in `among_them/sim.nim`), not in the artifacts the reporter sees. See [`DESIGN.md`](DESIGN.md) §Frictions for the v2 path (game writes a structured per-tick `events.jsonl` alongside the replay).

## Inputs

Per the v1 reporter contract ([`../../../docs/REPORTER_DESIGN.md`](../../../docs/REPORTER_DESIGN.md), D2/D10/D11), all consumed inputs arrive as env-supplied URIs:

| Env var | Read |
| --- | --- |
| `COGAME_RESULTS_URI` | results JSON: `scores`, `names`, `win`, `tasks`, `kills`, `imposter`, `crew`, `vote_players`, `vote_skip`, `vote_timeout` (per `among_them/coworld_manifest.json`'s `results_schema`) |
| `COGAME_EPISODE_METADATA_URI` | `episode_id`, `variant_id`, `duration_seconds`, per-slot `policy_name` |
| `COGAME_REPLAY_URI` | binary `.bitreplay` v3 (BITWORLD magic + format-version 3 + game name + game version + timestamp + configJson + record stream of tick-hash / input / join / leave records). Parsed inline; see `parse_bitreplay` in `among_them_summarizer.py`. |
| `COGAME_REPORTER_ID` | stamped into stderr log lines |
| `COGAME_REPORT_OUTPUT_URI` | write target for the zip (`Content-Type: application/zip`) |

`COGAME_LOG_URI` is **not** consumed today. The Among Them game doesn't post log lines to it (it writes events to stdout, captured separately by hosted runners), and parsing prose log strings is the wrong long-term shape. See [`DESIGN.md`](DESIGN.md) §Frictions for the v2 path.

## Slot ↔ connection-order mapping

The binary replay's `ReplayJoinRecord` carries both a **slot** field (the tournament/results-JSON slot index, may be `-1` for auto-assign) and a **player_index** field (the position in `sim.players` at join time — i.e. the connection-order index). These usually agree but can differ. The reporter exposes the mapping three ways:

- Per-row, on each slot: `stats.json::slots[i].join_order` — the connection-order index that joined into slot `i`, or `null` if no join record exists.
- Flat top-level: `stats.json::slot_to_join_order` — an array of length N (slot count) with the same values, indexed by slot.
- In the event log: each `join` row in `events.parquet` carries both `slot` and `player_index` in its JSON payload.

Downstream ingesters that need to correlate the results JSON's slot-indexed arrays with the order players connected to the game pick whichever view is convenient.

## Failure modes

| Situation | Behavior |
| --- | --- |
| All inputs valid, normal episode | Exit 0, valid zip with all four entries |
| Imposter win | Verdict "Imposters win"; surviving imposters marked Won; other slots Lost |
| Crewmate win (by tasks or by ejection) | Verdict "Crewmates win"; the reporter cannot distinguish task-win from ejection-win without per-event detail |
| Draw — time limit reached | Verdict "Draw"; `verdict.any_winner == false`; all slots' `won` is false |
| Player disconnects mid-game | A `ReplayLeaveRecord` ≥ 5 s before the last hash tick → row in the Disconnects card; `stats.disconnects[]` populated |
| Replay magic mismatch or version != 3 | `ValueError`; exit 1 (`nonzero_exit` per D8 + D12); no zip written |
| Replay truncated mid-record | `ValueError` propagates; exit 1 |
| Unknown record type byte | `ValueError`; exit 1 |
| Results JSON missing required `scores` field | Pydantic `ValidationError`; exit 1 |
| Output URI unreachable | Bubble up exception; exit 1 |

See [`DESIGN.md`](DESIGN.md) for the full failure-mode table.

## Running locally

```bash
COGAME_RESULTS_URI=file:///path/to/scores.json \
COGAME_EPISODE_METADATA_URI=file:///path/to/metadata.json \
COGAME_REPLAY_URI=file:///path/to/run.bitreplay \
COGAME_REPORT_OUTPUT_URI=file:///path/to/report.zip \
COGAME_REPORTER_ID=among-them-summarizer \
python among_them_summarizer.py
```

Both `file://` and `http(s)://` URIs are supported. HTTP requests retry on 429 and 5xx (5 attempts, exponential backoff).

### Capturing a real `.bitreplay` for testing

The Among Them game writes `.bitreplay` when run with `--save-replay`. From the `bitworld` checkout:

```bash
cd ~/coding/bitworld
nim r tools/quick_run.nim among_them \
  --players:0 --bots:nottoodumb:8 --port:2002 \
  --save-replay:/tmp/run.bitreplay \
  --save-scores:/tmp/scores.json \
  '--config:{"seed":679961,"minPlayers":8,"imposterCount":2,"tasksPerPlayer":8,"maxTicks":10000,"maxGames":1,"voteTimerTicks":6000,"killCooldownTicks":900}'
```

The platform-generated episode metadata file is not produced by the game — you'll need to synthesize a minimal `metadata.json` matching the strawman shape in [`docs/REPORTER_DESIGN.md`](../../../docs/REPORTER_DESIGN.md) §7 to drive the reporter locally.

## Building the image

```bash
./build.sh                              # (deferred to phase 7; placeholder for now)
```

The Dockerfile + `build.sh` land in phase 7 of the [`DESIGN.md`](DESIGN.md) implementation plan. The build context will be `reporters/` (matching PaintArena's pattern) so both the SDK and the reporter source are reachable from one `COPY` plane; the platform target is `linux/amd64` (what `coworld upload` requires for hosted episodes).

## Tests

```bash
uv run pytest reporters/among_them/among_them_summarizer/tests/ -v
```

Currently **88 tests** across `test_skeleton.py`, `test_phase2.py`, `test_phase3.py`, `test_phase4.py`, `test_phase5.py`. Coverage by phase:

- **Phase 1 (skeleton).** Env-var loading at the I/O contract boundary.
- **Phase 2 (aggregates).** Verdict derivation (Imposter / Crewmate / Draw), per-slot stats generalized over 4/8/16 slots, policy-name fallback (metadata → results.names → `Slot N`), `.bitreplay` header parser (magic / version / game-name rejection paths, truncation), zip shape (4 entries, `render.txt` correctness, pinned mtimes), HTML self-containment, byte-identical reruns, `events.parquet` schema with `game_config` / `player_summary` / `game_result` keys.
- **Phase 3 (full replay parser).** All four record types in mixed order, multi-byte UTF-8 names, truncated/unknown record rejection, `tick_from_ms` boundaries, last_tick from hash records, join → `in_game_name`/`joined_tick` wiring, leave → disconnect classification (>5s before end), color-from-config vs positional palette fallback, token never written to any output (defensive byte-not-in check), `join` + `leave` events in parquet, slot ↔ connection-order mapping (`SlotStats.join_order`, `stats.slot_to_join_order`, `join` event's `player_index`).
- **Phase 4 (input analytics).** Edge detection (held key = 1 press, release-and-repress = 2, simultaneous bits = 1 per bit), all 7 buttons parametrized, slot mapping survives mid-game leaves, bucket aggregation per (slot, 10s window), `stats.activity` block populated, `input_press` + `activity_bucket` keys in parquet, empty-input-stream graceful degradation.
- **Phase 5 (HTML polish).** Well-formedness via stdlib `html.parser`, self-containment (no `<script>`, no `<link>`), 16-entry palette aligned with `PLAYER_COLOR_NAMES`, one swatch per scoreboard row, swatch hex matches palette, sparkline SVG count equals slot count, rect count per sparkline equals dense bucket count, post-leave buckets marked `bar-absent`, footer carries episode id.

The phase-6 determinism + zip-contract test pass (per the plan) and phase-7 smoke-test harness will add more.

## SDK extraction candidates (inline today)

These primitives are verbatim copies of `paint_arena_summarizer.py`'s inline primitives and slated for promotion to `reporter_sdk` once the API surface stabilizes:

- `ReporterInputs` dataclass + `load_reporter_inputs()`
- `read_uri` / `write_uri` / `read_json` (scheme-dispatched `file://` and `http(s)://` with HTTP retry)
- `write_deterministic_zip(entries)` — pinned-mtime helper for D12 byte-identical reruns
- `EVENT_LOG_SCHEMA` + `write_events_parquet(rows)` — shared `(ts, player, key, value)` schema and pyarrow writer
- `_stable_json(obj)` — sort-keys + compact-separator JSON encoder for deterministic payloads

The Among-Them-specific parts (`parse_bitreplay`, `extract_input_presses`, `bucket_presses`, `build_slot_stats`, `build_stats`, `render_summary_html`, the `PLAYER_COLOR_NAMES` / `AMONG_THEM_COLORS` palette, the `BUTTONS` table, the HTML CSS) stay in this file — replay-shape coupling is coworld-specific by D11 and intentionally not promotion material, and the in-zip file layout is the reporter author's decision under D12.
