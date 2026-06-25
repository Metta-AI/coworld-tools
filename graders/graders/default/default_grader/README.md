# Default Grader

Generic starter Coworld grader for episodes that do not yet have a
game-specific grader.

This grader consumes a Coworld episode bundle, reads `results.json`, and emits a
small JSON grade based on final score spread. It is intentionally simple: if the
results artifact does not contain a usable `scores` list, the grade is `0.0`.

## Runtime Contract

Required environment variables:

- `COGAME_EPISODE_BUNDLE_URI`: episode bundle zip. Supports local paths,
  `file://`, `http://`, `https://`, and `s3://`.
- `COGAME_GRADE_URI`: destination URI for the grade JSON. Supports local paths,
  `file://`, `http://`, `https://`, and `s3://`.

For `s3://` reads or writes, the runtime needs `boto3` and AWS credentials in
the environment. The Dockerfile installs `boto3`.

The grader reads `manifest.json` from the bundle and uses
`manifest.files.results` to find the results artifact. If that field is absent,
it falls back to `results.json`.

Output JSON:

```json
{
  "grader_id": "default-grader",
  "score": 0.75
}
```

`score` is a deterministic heuristic in the range `0.0` to `1.0`. It is the
spread between the highest and lowest numeric values in `results.scores`,
normalized by `max(abs(high), abs(low), 1.0)` and clamped to the grade range.
Malformed, missing, boolean, and non-finite score entries are ignored.

## Build

```bash
./build.sh
```

The default image is `default-grader:latest` for `linux/amd64`.

## Local Test

From the repository root:

```bash
python3 -m unittest tests.test_default_grader
```
