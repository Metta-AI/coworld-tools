# Cogs Vs Clips Grader

Starter Coworld grader for Cogs vs Clips episodes.

This grader consumes a Coworld episode bundle, reads `results.json` and the
MettaScope replay artifact, and emits a small JSON grade that estimates how much
performance divergence occurred inside the episode.

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
  "grader_id": "cogs-v-clips-grader",
  "score": 0.75
}
```

`score` is a deterministic heuristic in the range `0.0` to `1.0`. It combines
spread in final scores/rewards, per-agent resource and heart inventory
differences, role/survival differences, and team-level junction activity. It is
an episode-interest signal, not a formal CogsGuard skill score.

The replay does not reliably expose exact per-agent mined totals, hearts made,
or junction-capture attribution, so those behaviors are approximated from the
saved replay object histories.

## Build

```bash
./build.sh
```

The default image is `cogs-v-clips-grader:latest` for `linux/amd64`.

## Local Test

From the repository root:

```bash
python3 -m unittest tests.test_cogs_v_clips_grader
```
