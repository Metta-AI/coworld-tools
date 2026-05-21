# Among Them Grader

Minimal Coworld grader for Among Them episodes.

Graders score how interesting or useful an episode was from the game creator's
perspective. This starter consumes the episode results and emits a scalar JSON
score so tournaments and local tools can rank episodes for review.

## Runtime Contract

Required environment variables:

- `COGAME_RESULTS_URI`: JSON results artifact from the episode.
- `COGAME_GRADE_OUTPUT_URI`: destination URI for the grade JSON.

Optional environment variables:

- `COGAME_REPLAY_URI`: replay artifact for future richer scoring.
- `COGAME_REPLAY_STATS_PARQUET_URI`: reporter-produced stats parquet.

The output is JSON:

```json
{ "score": 0.75 }
```

URI values may be `file://` paths, plain local paths, or `http(s)://` URLs.
HTTP outputs are written with `PUT`.

## Build

```bash
./build.sh
```
