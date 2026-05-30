# Cogs vs Clips Summarizer

Coworld reporter for Cogs vs Clips episodes.

Input: a canonical episode bundle at `COGAME_EPISODE_BUNDLE_URI` containing:

- `results`: Cogs vs Clips result JSON (`scores`, `steps`, `mission`)
- `replay`: MettaScope replay JSON written by the Coworld runtime
- `metadata`: optional episode/player metadata

Output: a report zip at `COGAME_REPORT_URI` with:

- `manifest.json`
- `summary.md`
- `behavior_summary.json`
- `trace.jsonl`
- `events.parquet`

`trace.jsonl` is the primary machine-readable artifact. It contains one JSON
object per agent tick with policy name, location, action, reward, and inventory
state decoded from the compact replay format.
