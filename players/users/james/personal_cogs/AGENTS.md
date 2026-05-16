# AGENTS.md

Workshop repo for Softmax Alignment League Benchmark agents.

## Current Among Them Rule

Among Them is now Coworld-only in this checkout.

- Do not use local server scripts.
- Do not use legacy bundle upload helpers.
- Do not use hosted-play wrappers.
- Do not use deprecated historical bot directories.
- Do not run Coworld through a local Metta checkout for this project.

The intended command surface is:

```sh
uv run coworld ...
```

from the repo-local UV project under `among_them/`.

## Read First

For Among Them work, read:

1. `among_them/README.md`
2. `among_them/guided_bot/README.md`
3. `among_them/guided_bot/coworld/README.md`

`MISSION.md`, `COGAMES.md`, and `COGAMES_CLI.md` have been reset to reflect the
same Coworld-only direction.

## Layout

```text
among_them/
  README.md
  common/
  guided_bot/
    README.md
    coworld/
```

Execution belongs under Coworld. New tooling should be added through the
repo-local UV project, not as ad hoc scripts.

## Validation Expectations

After implementation changes:

- run the narrowest useful static/unit checks available without reviving deleted
  run paths;
- validate end-to-end through Coworld via `uv run coworld ...`;
- inspect Coworld logs and stderr JSONL traces for runtime-sensitive behavior.

If a check cannot be run because the public PyPI dependency set is unavailable
or credentials are missing, say that explicitly in the handoff.

## Documentation Expectations

Keep docs Coworld-only. Do not add instructions for local game servers, raw
frame-capture scripts, hosted-play shims, or legacy bundle upload commands.

Before committing, audit the docs touched by the session and update stale run
instructions in the same change.
