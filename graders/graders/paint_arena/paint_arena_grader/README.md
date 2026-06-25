# PaintArena Grader

Starter Coworld grader for PaintArena episodes.

This grader consumes a Coworld episode bundle, reads `results.json` and
`replay.json`, and emits a small JSON grade that ranks how decisive the final
paint score was.

## Runtime Contract

Required environment variables:

- `COGAME_EPISODE_BUNDLE_URI`: episode bundle zip. Supports local paths,
  `file://`, `http://`, `https://`, and `s3://`.
- `COGAME_GRADE_URI`: destination URI for the grade JSON. Supports local paths,
  `file://`, `http://`, `https://`, and `s3://`.

For `s3://` reads or writes, the runtime needs `boto3` and AWS credentials in
the environment. The Dockerfile installs `boto3`.

The grader reads `manifest.json` from the bundle and uses
`manifest.files.results` and `manifest.files.replay` to find the artifacts. If a
field is absent, it falls back to `results.json` or `replay.json`.

Output JSON:

```json
{
  "grader_id": "paint-arena-grader",
  "score": 0.75
}
```

`score` is a deterministic heuristic in the range `0.0` to `1.0`. It is the
winner's final-score margin over the runner-up, divided by the board area from
`replay.config.width * replay.config.height`. Higher values mean a more
decisive PaintArena episode.

## Build

```bash
./build.sh
```

The default image is `paint-arena-grader:latest` for `linux/amd64`.

## Local Test

From the repository root:

```bash
python3 -m unittest tests.test_paint_arena_grader
```
