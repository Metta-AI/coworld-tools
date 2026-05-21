# Among Them Diagnoser

Starter Coworld diagnoser for Among Them policies.

A diagnoser is policy-facing: it consumes a target policy plus any useful
episode artifacts and emits advice or assay results for the coding agent
improving that policy. This starter keeps the protocol minimal while giving the
manifest a concrete reference runnable.

## Runtime Contract

Required environment variables:

- `COGAME_POLICY_URI`: target policy or policy workspace URI.
- `COGAME_DIAGNOSIS_OUTPUT_URI`: destination URI for Markdown advice.

Optional environment variables:

- `COGAME_MANIFEST_URI`: Coworld manifest JSON.
- `COGAME_RESULTS_URI`: episode results JSON.
- `COGAME_REPLAY_URI`: episode replay artifact.
- `COGAME_REPLAY_STATS_PARQUET_URI`: reporter-produced stats parquet.
- `COGAME_REPORT_URI`: reporter output bundle.
- `COGAME_TARGET_PLAYER_SLOT`: player slot to diagnose.

URI values may be `file://` paths, plain local paths, or `http(s)://` URLs.
HTTP outputs are written with `PUT`.

## Build

```bash
./build.sh
```
