# Among Them Commissioner

Reference home for the Among Them Coworld commissioner.

The hosted commissioner currently lives in Observatory's backend as
`AmongThemCommissioner`, registered with `commissioner_key="among_them"`.
This directory gives the Coworld manifest a canonical role-repo location while
the platform protocol remains the source of truth for hosted tournament
scheduling, ranking, and division movement.

Metta source:

```text
app_backend/src/metta/app_backend/v2/commissioners.py
```

## Runtime Contract

Commissioners decide what episodes to schedule in a tournament, how rankings
change from completed episodes, and how players move between divisions. Custom
third-party commissioner containers are not yet a public extension point; this
starter emits a descriptor for local tooling and manifest validation.

Required environment variables:

- `COGAME_COMMISSIONER_OUTPUT_URI`: destination URI for the descriptor JSON.

Optional environment variables:

- `COGAME_MANIFEST_URI`: Coworld manifest JSON.
- `COGAME_LEAGUE_STATE_URI`: current league state JSON.

URI values may be `file://` paths, plain local paths, or `http(s)://` URLs.
HTTP outputs are written with `PUT`.

## Build

```bash
./build.sh
```
