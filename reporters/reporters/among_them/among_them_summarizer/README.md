# Among Them Summarizer

Reference Coworld reporter for Among Them episodes.

This reporter consumes one replay/results pair and emits a zip archive that can
be displayed by surfaces such as Observatory's The Column. The archive contains:

- `index.html`: a small rendered report.
- `index.md`: the same report in Markdown.
- `summary.json`: machine-readable facts extracted from the results file.

## Runtime Contract

Required environment variables:

- `COGAME_RESULTS_URI`: JSON results artifact from the episode.
- `COGAME_REPORT_OUTPUT_URI`: destination URI for the report zip.

Optional environment variables:

- `COGAME_REPLAY_URI`: replay artifact for future richer summaries.
- `COGAME_EPISODE_METADATA_URI`: episode metadata JSON.
- `COGAME_REPORTER_ID`: reporter id for logs and metadata.

URI values may be `file://` paths, plain local paths, or `http(s)://` URLs.
HTTP outputs are written with `PUT`.

## Build

```bash
./build.sh
```
