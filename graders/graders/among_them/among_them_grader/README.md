# Among Them Grader

Starter Coworld grader for Among Them episodes.

This grader consumes a Coworld episode bundle, reads the episode results, and emits a small JSON grade that ranks how
interesting the episode is likely to be for review.

## Runtime Contract

Required environment variables:

- `COGAME_EPISODE_BUNDLE_URI`: episode bundle zip. Supports local paths, `file://`, `http://`, `https://`, and `s3://`.
- `COGAME_GRADE_URI`: destination URI for the grade JSON. Supports local paths, `file://`, `http://`, `https://`, and
  `s3://`.

For `s3://` reads or writes, the runtime needs `boto3` and AWS credentials in the environment. The Dockerfile installs
`boto3`.

The grader reads `manifest.json` from the bundle and uses `manifest.files.results` to find the results file. If that
field is absent, it falls back to `results.json`.

Output JSON:

```json
{
  "grader_id": "among-them-grader",
  "score": 0.75
}
```

`score` is a heuristic in the range `0.0` to `1.0`. Higher values mean the episode had more review-worthy signals:
non-trivial win distribution, score spread, task progress, or kills. The score is not comparable with other graders
unless their descriptions explicitly define compatible scales.

## Build

```bash
./build.sh
```

The default image is `among-them-grader:latest` for `linux/amd64`.

## Local Test

From the repository root:

```bash
python3 -m unittest tests.test_among_them_grader
```
