# Prompt Templates

Each `.md` file in this directory is a prompt template used by `generate_guides.py`.

## Structure

- `_preamble.md` — Shared context prepended to every runner prompt
- `_synthesizer.md` — Template for the synthesis step (merging two drafts)
- `doc_*.md` — One runner prompt per document (e.g., `doc_game_overview.md`)

## Template Variables

Templates use `{{variable}}` syntax. The pipeline substitutes these at runtime:

| Variable | Description |
|----------|-------------|
| `{{game_source_path}}` | Path or URL to the game source |
| `{{output_dir}}` | Directory where generated docs are written |
| `{{output_file}}` | Full path for this document's output |
| `{{prior_docs}}` | Formatted list of previously generated docs with paths and descriptions |
| `{{draft_a}}` | Path to runner A's draft (synthesizer only) |
| `{{draft_b}}` | Path to runner B's draft (synthesizer only) |
| `{{doc_name}}` | Name of the document being generated |

## Iteration

Edit these files directly to tune output quality. No code changes required.
The script reads them fresh on every run.
