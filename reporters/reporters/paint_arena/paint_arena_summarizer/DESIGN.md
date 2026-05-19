# paint_arena_summarizer — Design

> **Status:** in design (no implementation yet). This is the first concrete reporter in the repo and is intentionally being built before `reporter_sdk` and `templates/summarizer_template`. See the [root README](../../../README.md) "Build strategy" section for why.

## Purpose

Produce a per-episode human-readable summary and a machine-readable stats artifact for the PaintArena coworld. Pure function of `COGAME_RESULTS_URI` + `COGAME_EPISODE_METADATA_URI` + `COGAME_MANIFEST_URI`; deterministic; no replay or log access in v1.

This document is load-bearing in two directions: it specifies what the implementation must do, and it records the decisions the SDK extraction pass will refer back to.

## Inputs

| Env var | Used? | Why |
| --- | --- | --- |
| `COGAME_RESULTS_URI` | **Yes** | Source of `scores` / `painted_tiles` / `ticks`. |
| `COGAME_EPISODE_METADATA_URI` | **Yes** | Per-slot `policy_name`, `started_at`/`ended_at`/`duration_seconds`, `episode_id`, `variant_id`. |
| `COGAME_MANIFEST_URI` | **Yes** | Look up `variants[].game_config.{width,height}` keyed on `variant_id` → grid total tiles. |
| `COGAME_REPORTER_ID` | Logs only | Stamped into log lines for observability; not used for output content. |
| `COGAME_REPORT_OUTPUT_URI` | **Yes** | Write target for the envelope. |
| `COGAME_REPLAY_URI` | No | v1 summary doesn't need frame-by-frame data. Reserve for a future heatmap/highlight reporter. |
| `COGAME_LOG_URI` | No | Not relevant to PaintArena summary content. |

## Output envelope

```jsonc
{
  "version": "1",
  "artifacts": [
    { "id": "summary", "content_type": "text/markdown", "content": "..." },
    { "id": "stats",   "content_type": "application/json", "content": { ... } }
  ]
}
```

### `summary` (text/markdown) — first artifact by convention

Indicative shape (exact phrasing TBD during implementation):

```markdown
# PaintArena — Episode ep_abc123

**Variant:** default · **Grid:** 12 × 8 (96 tiles) · **Duration:** 19.4 s (100 ticks)

| Slot | Policy | Tiles painted | Share |
| --- | --- | --- | --- |
| 0 | champion-v3 | 47 / 96 | 49% |
| 1 | starter     | 38 / 96 | 40% |
| — | unpainted   | 11 / 96 | 11% |

**Winner:** Slot 0 (champion-v3) by 9 tiles.
```

### `stats` (application/json) — second artifact

```jsonc
{
  "episode_id": "ep_abc123",
  "variant_id": "default",
  "grid": { "width": 12, "height": 8, "total_tiles": 96 },
  "ticks": 100,
  "duration_seconds": 19.4,
  "slots": [
    { "slot": 0, "policy_name": "champion-v3", "painted_tiles": 47, "share_pct": 48.96 },
    { "slot": 1, "policy_name": "starter",     "painted_tiles": 38, "share_pct": 39.58 }
  ],
  "unpainted_tiles": 11,
  "unpainted_share_pct": 11.46,
  "winner_slot": 0,
  "margin_tiles": 9,
  "tie": false
}
```

Generalized over slot count (results schema allows 1–4; iterate, don't hard-code 2). `painted_tiles` is the int from results; `scores` is dropped from output because it's just `painted_tiles` cast to float (no information).

## Decisions locked in

1. **Grid-coverage percentages, not within-painted ratios.** Reading the manifest + variant lookup is worth it: it answers the natural "did you cover the board?" question and demonstrates the manifest-access pattern the SDK will absorb.
2. **`policy_name` from episode metadata for player display**, falling back to `"Slot N"` when null (e.g. certification context with no real policy). `policy_name` is the tournament-meaningful identity; variant-config `player_names` is cosmetic and ignored.
3. **Two artifacts: `summary` (markdown) and `stats` (json). No heatmap PNG in v1.** Embedding a heatmap requires reading the replay and pulls binary-content-type plumbing into the first reporter before we know what the SDK should expose for binary artifacts. Defer to a later iteration or to a separate `paint_arena_highlight_reel` reporter.
4. **Generic-over-slot-count.** Iterate `painted_tiles`; do not hard-code 2 players.

## Failure-mode behavior

| Situation | Behavior | Exit |
| --- | --- | --- |
| All inputs valid, normal episode | Write envelope with both artifacts | 0 |
| `painted_tiles` sums to 0 (no tiles painted) | Write envelope; summary says "no tiles painted; no winner"; stats has `winner_slot: null`, `tie: false`, `margin_tiles: 0` | 0 |
| Tied painted-tile counts | Write envelope; summary says "tied at N tiles"; stats has `winner_slot: null`, `tie: true`, `margin_tiles: 0` | 0 |
| `variant_id` from metadata not found in manifest's `variants[]` | Log error, exit non-zero (`nonzero_exit` per D8) | 1 |
| Results JSON missing required field or unparseable | Log error, exit non-zero | 1 |
| Output URI unreachable | Bubble up exception, exit non-zero | 1 |

Per D8, the platform will surface these as `nonzero_exit` failure records. The reporter does not produce synthetic "I failed" envelopes — it either writes a valid envelope and exits 0, or it exits non-zero.

## Inline primitives (the SDK extraction candidates)

These primitives live inline in `paint_arena_summarizer.py` for v1. The SDK extraction pass will lift what proves general:

- `ReporterInputs` typed-dict / dataclass and `load_reporter_inputs()` reading all `COGAME_*` env vars.
- `read_uri(uri) -> bytes` / `write_uri(uri, payload, content_type)` — scheme-dispatched (`file://`, `http(s)://`) with retries on 429/5xx for HTTP. Stdlib + `requests`.
- `Envelope` / `Artifact` dataclasses with `to_json_bytes()`.
- `validate_envelope(envelope_dict)` — dict-shape D3 check; not full jsonschema.
- `lookup_variant(manifest_dict, variant_id) -> variant_dict` — KeyError-raising if not found.

Anything *not* in that list (PaintArena results parsing, summary phrasing, the per-slot percentage math) stays in this reporter forever.

## Determinism and testing

Output is a pure function of (results JSON, episode metadata JSON, manifest JSON). Test plan:

- Unit tests with hand-crafted fixture JSONs covering the failure-mode table above.
- Determinism check: run summarizer twice on the same fixtures, byte-compare envelope JSON.
- Local end-to-end smoke: `coworld run-episode` against the PaintArena example, point the reporter at the produced artifacts, inspect the envelope.

## Non-goals (v1)

- No replay reading (no heatmap, no per-tick curves).
- No log reading.
- No external network calls beyond input/output URIs (D1 purity).
- No LLM involvement.
- No platform-side schema declaration of the `stats` JSON shape (D7 shelved this).
- No multi-reporter coordination (D4 explicitly forbids cross-reporter pipelining anyway).
