# among_them_summarizer

Per-episode summarizer reporter for the Among Them Coworld. Reads the episode bundle (results, binary `.bitreplay`, optional config); writes a single output zip containing a self-contained HTML summary, a JSON stats file, a per-event Parquet event log, and an in-zip `manifest.json` flagging the HTML as `render` and the Parquet as `event_log` per the canonical Coworld reporter contract. Second concrete reporter in the repo — its inline primitives (HTTP I/O, deterministic-zip writer, shared event-log schema) were extracted alongside [`paint_arena_summarizer`](../../paint_arena/paint_arena_summarizer/) into [`reporter_sdk`](../../reporter_sdk/). See [`DESIGN.md`](DESIGN.md) for the locked-in design.

> **Implementation status (2026-05-23):** the running code matches the canonical Coworld reporter contract (single `COGAME_EPISODE_BUNDLE_URI` in, single `COGAME_REPORT_URI` out, in-zip `manifest.json` flagging `render` and `event_log`, `int64` event-log columns). Episode-level metadata reaches the reporter via the bundle's optional `metadata` token; absent it, the reporter falls back to defaults and reads `episode_id` from the inner manifest's `ereq_id`. The bundle's `replay` token carries binary `.bitreplay` bytes (an Among-Them-specific deviation from the canonical JSON-formatted `replay.json` convention; the SDK's `BundleReader` reads bytes either way). All eight design phases — including phase 6 (determinism + zip-contract assertions) and phase 8 (this README) — have landed.

## Output zip contents

```
report.zip
├── manifest.json       # {reporter_id, render: "summary.html", event_log: "events.parquet"}
├── summary.html        # rendered inline (flagged by manifest.json `render`)
├── stats.json          # auxiliary download (referenced from HTML footer)
└── events.parquet      # canonical event log (flagged by manifest.json `event_log`)
```

| Entry | Role | Contents |
| --- | --- | --- |
| `manifest.json` | render manifest | `{"reporter_id": "among-them-summarizer", "render": "summary.html", "event_log": "events.parquet"}` |
| `summary.html` | `render` target | Self-contained HTML page: header strip with episode + game config; verdict ribbon (Imposters win / Crewmates win / Draw); scoreboard with per-slot color swatch (16-color in-game palette), role badge, Won/Lost, score, kills, tasks-done / tasks-assigned, vote counts, and an activity sparkline SVG; disconnects table (only when any mid-game leaves occurred); footer with episode/reporter info. Inline CSS only — no `<script>`, no `<link>` — safe inside an iframe+CSP sandbox. |
| `stats.json` | auxiliary | `{episode_id, variant_id, duration_seconds, total_ticks, replay_fps, game_version, config, verdict, slots[], slot_to_join_order, disconnects[], activity}`. See [`DESIGN.md`](DESIGN.md) §`stats.json` for the full field set. |
| `events.parquet` | `event_log` target | Per-event log in the canonical `(ts: int64, player: int64, key: string, value: string)` schema. Keys emitted: `game_config` (one row, ts=0), `join` / `leave` (one per replay record), `input_press` (one per 0→1 button-press transition), `activity_bucket` (one per non-empty (slot, 10-second window) aggregate), `player_summary` (one per slot, ts=last_tick), `game_result` (one row, ts=last_tick). `value` is a JSON document; consumers `json.loads` per row. |

The reporter is generalized over slot count (Among Them's `results_schema` allows 1–16 players); the 8-player default-variant config is the common case but nothing assumes it. Zip entries pin `date_time` to `(1980, 1, 1, 0, 0, 0)` so byte-identical reruns over identical inputs produce byte-identical zips (determinism is preferred but not required by the canonical contract; this reporter opts in). Within one pinned `pyarrow` version the Parquet bytes are deterministic too — the `requirements.txt` pin is what makes that hold across reruns of the same image.

### What the reporter intentionally does NOT surface

The artifacts the reporter sees (results JSON + binary `.bitreplay` + bundle-supplied metadata) carry per-slot aggregates and per-tick player inputs, but **not** the rich event stream a viewer of the running game would see. The reporter does not infer:

- Per-player alive/dead state. The results JSON has `won` per slot, not `alive`. A losing crewmate may be dead or alive-when-imposters-won; a losing imposter may be voted out or alive-when-crew-won-by-tasks. We don't guess.
- Meetings held. Per-slot `vote_players` / `vote_skip` / `vote_timeout` counts are in the scoreboard (those are facts from the results JSON), but the reporter does not aggregate them into a "meetings held" total — slots can die before/between meetings, making any aggregate a bounded estimate rather than a fact.
- Per-event detail of kills, votes cast, body reports, chat, task completions, vents, phase transitions. Those exist in the game's stdout text (`logGameEvent` calls in `among_them/sim.nim`), not in the artifacts the reporter sees. See [`DESIGN.md`](DESIGN.md) §Frictions for the v2 path (game writes a structured per-tick `events.jsonl` alongside the replay).

## Inputs

Per the canonical Coworld reporter contract ([`packages/coworld/src/coworld/docs/roles/reporter.md`](../../../../metta/packages/coworld/src/coworld/docs/roles/reporter.md) in metta), the reporter reads one env var and writes one env var:

| Env var | Direction | Use |
| --- | --- | --- |
| `COGAME_EPISODE_BUNDLE_URI` | read | URI of the episode-bundle zip. The reporter opens it, inspects its inner `manifest.json`, and reads the entries it needs: `results.json`, `replay.json` (the binary `.bitreplay` is *the* replay artifact for Among Them; the bundle stores it under the `replay` token), optional `config.json`. |
| `COGAME_REPORT_URI` | write | Write target for the output zip (`Content-Type: application/zip`). |

What the reporter reads out of the bundle:

| Bundle entry | Use |
| --- | --- |
| `results.json` | `scores`, `names`, `win`, `tasks`, `kills`, `imposter`, `crew`, `vote_players`, `vote_skip`, `vote_timeout` (per Among Them's `results_schema`). The reporter's primary source of structured per-player facts. |
| `replay.json` (the `.bitreplay` payload) | Binary `.bitreplay` v3 (`BITWORLD` magic + format-version 3 + game name + game version + timestamp + configJson + record stream of tick-hash / input / join / leave records). Parsed inline by `parse_bitreplay` in `among_them_summarizer.py`. |
| `config.json` (optional) | Variant config for stamping into the HTML header strip when present. |
| Bundle inner `manifest.json` | `ereq_id` (used for log lines and as the `episode_id` fallback when no `metadata` token is supplied) plus the standard bundle metadata. |

The episode bundle's contract is documented in [`EPISODE_BUNDLE_README.md`](../../../../metta/packages/coworld/src/coworld/EPISODE_BUNDLE_README.md) in metta. Episode-metadata fields the reporter populates in `stats.json` (`episode_id`, `variant_id`, `duration_seconds`, per-slot `policy_name`) come from the bundle's `manifest.json` plus the embedded `replay.json` / `results.json`.

## Failure modes

| Situation | Behavior |
| --- | --- |
| All inputs valid, normal episode | Exit 0, valid zip with `manifest.json`, `summary.html`, `stats.json`, `events.parquet` |
| Imposter win | Verdict "Imposters win"; surviving imposters marked Won; other slots Lost |
| Crewmate win (by tasks or by ejection) | Verdict "Crewmates win"; the reporter cannot distinguish task-win from ejection-win without per-event detail |
| Draw — time limit reached | Verdict "Draw"; `verdict.any_winner == false`; all slots' `won` is false |
| Player disconnects mid-game | A `ReplayLeaveRecord` ≥ 5 s before the last hash tick → row in the Disconnects card; `stats.disconnects[]` populated |
| Bundle's inner `manifest.json` reports `status: "failed"` and required artifacts absent | Exit 1; reporter cannot operate on a failed episode |
| Replay magic mismatch or version != 3 | `ValueError`; exit 1; no zip written |
| Replay truncated mid-record | `ValueError` propagates; exit 1 |
| Unknown record-type byte | `ValueError`; exit 1 |
| Results JSON missing required `scores` field | Pydantic `ValidationError`; exit 1 |
| `COGAME_EPISODE_BUNDLE_URI` missing/unreachable, or `COGAME_REPORT_URI` unwritable | Bubble up exception; exit 1 |

See [`DESIGN.md`](DESIGN.md) for the full failure-mode table.

## Running locally

```bash
COGAME_EPISODE_BUNDLE_URI=file:///path/to/bundle.zip \
COGAME_REPORT_URI=file:///path/to/report.zip \
python among_them_summarizer.py
```

Both `file://` and `http(s)://` URIs are supported. HTTP requests retry on 429 and 5xx (5 attempts, exponential backoff).

Assemble a local bundle from a runner workspace via metta's CLI:

```bash
uv run coworld bundle <ereq_id> --output /tmp/bundle.zip --include results,replay,config
```

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

Then pack a single-episode bundle by hand (zip the `.bitreplay` as `replay.json` plus the `scores.json` as `results.json` and a `manifest.json` listing the entries), or use metta's bundling helpers if you have a real `ereq_id`.

## Slot ↔ connection-order mapping

The binary replay's `ReplayJoinRecord` carries both a **slot** field (the tournament/results-JSON slot index, may be `-1` for auto-assign) and a **player_index** field (the position in `sim.players` at join time — i.e. the connection-order index). These usually agree but can differ. The reporter exposes the mapping three ways:

- Per-row, on each slot: `stats.json::slots[i].join_order` — the connection-order index that joined into slot `i`, or `null` if no join record exists.
- Flat top-level: `stats.json::slot_to_join_order` — an array of length N (slot count) with the same values, indexed by slot.
- In the event log: each `join` row in `events.parquet` carries both `slot` and `player_index` in its JSON payload.

Downstream ingesters that need to correlate the results JSON's slot-indexed arrays with the order players connected to the game pick whichever view is convenient.

## Building the image

```bash
./build.sh                              # builds among-them-summarizer:latest for linux/amd64
PLATFORM=linux/arm64 ./build.sh         # local-only experimentation on Apple Silicon
IMAGE=among-them-summarizer:dev ./build.sh
```

`build.sh` defaults to `--platform linux/amd64` because `coworld upload` requires amd64 (hosted episodes run on amd64) and would reject a host-arch build from Apple Silicon. On non-amd64 hosts the build and any subsequent `docker run` happen under emulation, which is slower but keeps the locally tested image byte-identical to the uploadable image.

The Docker build context is `reporters/` (the directory containing `reporter_sdk/` and per-Coworld trees), so the Dockerfile can `COPY` both the shared SDK and the reporter source from one context.

Each reporter ships its own `Dockerfile.dockerignore` (allowlist style) so the build context contains only the SDK plus that reporter's runtime source.

## Tests

```bash
uv run pytest reporters/among_them/among_them_summarizer/tests/ -v
```

Covers env-var loading at the I/O contract boundary; verdict derivation (Imposter / Crewmate / Draw); per-slot stats generalized over 4 / 8 / 16 slots; policy-name fallback (bundle metadata → `results.names` → `Slot N`); the `.bitreplay` v3 parser (header magic / version / game-name rejection paths, all four record types in mixed order, multi-byte UTF-8 names, truncated / unknown record rejection); `tick_from_ms` boundaries; join → `in_game_name` / `joined_tick` / `join_order` wiring; leave → disconnect classification (> 5 s before end); color-from-config vs positional palette fallback; token never written to any output; input edge detection (held key = 1 press, release-and-repress = 2, simultaneous bits = 1 per bit, all 7 buttons); bucket aggregation per (slot, 10 s window); HTML self-containment (no `<script>`, no `<link>`); 16-entry palette aligned with `PLAYER_COLOR_NAMES`; sparkline SVG count / rect count / present-vs-absent dimming. The phase-6 determinism + zip-contract pass asserts byte-identical reruns over identical inputs, in-zip `manifest.json` consistency (`render` extension on the renderable allowlist; `render` and `event_log` paths exist in the zip; `event_log` is Parquet), pinned mtimes, and stable Parquet metadata across runs.

### Containerized smoke test

```bash
./smoke.sh                  # builds + runs the image against smoke/fixtures/
IMAGE=among-them-summarizer:dev ./smoke.sh
```

Builds the image, packs the checked-in synthetic fixtures (`smoke/fixtures/`) into a canonical episode bundle, runs the container against a `mktemp -d` output directory, and asserts the canonical zip contract end-to-end (four expected entries; in-zip `manifest.json` flags `render: summary.html` and `event_log: events.parquet`; both target paths exist in the zip; `render` has a renderable extension; `event_log` is Parquet), pinned mtimes, HTML self-containment, and that `events.parquet` is non-empty for a real bundle. The synthetic `.bitreplay` is regenerated from the test fixture helpers by `smoke/make_fixtures.py` — re-run that script if `tests/fixtures.py` evolves and the smoke fixtures should track it.

## SDK extraction candidates (inline today)

The Among-Them-specific primitives are inline in `among_them_summarizer.py` and stay that way; the cross-reporter primitives have already been extracted into [`reporter_sdk`](../../reporter_sdk/) and are imported from there:

- Bundle reader — opens the bundle zip from `COGAME_EPISODE_BUNDLE_URI`, parses its inner `manifest.json`, exposes typed accessors for the standard bundle tokens. **In the SDK.**
- `read_uri` / `write_uri` / `read_json` (scheme-dispatched `file://` and `http(s)://` with HTTP retry). **In the SDK.**
- `write_deterministic_zip(entries)` — pinned-mtime helper for byte-identical reruns. **In the SDK.**
- In-zip `manifest.json` writer — validates that `render` points at an existing `.md` / `.html` entry and `event_log` points at an existing Parquet entry. **In the SDK** as `OutputManifest` + `build_report_zip`.
- `EVENT_LOG_SCHEMA` + `write_events_parquet(rows)` — canonical `(ts, player, key, value)` schema and pyarrow writer. **In the SDK.**
- `stable_json(obj)` — sort-keys + compact-separator JSON encoder for deterministic payloads. **In the SDK.**

The following parts stay inline — they are Coworld-specific and not promotion material:

- `parse_bitreplay` and the surrounding binary-replay decoders (`_parse_bitreplay_header`, `_read_u8` / `_read_u16` / `_read_u32` / `_read_u64` / `_read_str`, the record-type dispatch). The replay format is **game-owned** by the canonical Coworld contract; the v3 BITWORLD parser is only useful for Among Them, and is explicitly **not** an SDK candidate. It stays in `among_them_summarizer.py` the same way PaintArena's frame-parsing stays in `paint_arena_summarizer.py`.
- `extract_input_presses` and `bucket_presses` — Among-Them-specific edge detection over the 7-bit input bitmask from `common/protocol.nim`.
- `derive_verdict`, `build_slot_stats`, `build_stats`, `build_event_rows` — the shape of the stats blob and the event-log payloads is reporter-specific.
- `render_summary_html` and the `_HTML_CSS` constant — HTML structure is the reporter author's decision; nothing here is shared across reporters.
- The `PLAYER_COLOR_NAMES` / `AMONG_THEM_COLORS` 16-color palette — mirrors `among_them/sim.nim`'s table and is game-specific.
- The `BUTTONS` table — mirrors `common/protocol.nim` and is game-specific.
