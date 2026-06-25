# Among Them Common Code

`common/` holds shared implementation code that the active guided_bot policy
imports. It is not a run harness and should not grow new execution scripts.

## Current Contents

| Path | Purpose |
|---|---|
| `perception_kernels/` | Low-level Nim kernels used by guided_bot perception. |

## Ownership

- Keep this directory small and implementation-focused.
- Add shared code here only when guided_bot or another active Coworld policy
  actually needs it.
- Do not add local server launchers, bundle upload helpers, or one-off debug
  scripts here.

Coworld execution belongs under `guided_bot/coworld/` and, after the UV project
is added, through `uv run coworld ...` from this workspace.
