# Among Them

This directory is a Coworld-only workspace for the Among Them bot. The old
local run harnesses, legacy bundle path, hosted-game shim, and deprecated
historical bot tree have been removed.

## Current Boundary

- Coworld is the only supported execution surface.
- Do not start local Among Them servers from this repo.
- Do not use deleted local helpers, legacy bundle upload paths, or hosted-play
  wrappers.
- Use this repo-local UV project and run `uv run coworld ...` from this
  workspace. The workspace intentionally installs `coworld` as an editable path
  dependency from `/Users/jamesboggs/coding/metta/packages/coworld`, so local
  Metta Coworld source changes are visible through `uv run`.

The remaining Nim files are the current guided_bot implementation, not a local
server harness. The run path should be Coworld image/CLI driven; a future
rewrite can remove the Nim implementation if we decide to make the bot pure
Python.

## Layout

| Path | Role |
|---|---|
| `guided_bot/` | Active Among Them policy implementation and design notes. |
| `guided_bot/coworld/` | Coworld image entrypoint, policy-player adapter, and Coworld operational docs. |
| `common/` | Shared perception kernels used by guided_bot. |

The deletion inventory for this cleanup is in the session handoff, not in the
living docs. The living docs should point only at the Coworld path.

## UV Runtime

This directory is a standalone UV project:

```sh
uv run coworld --help
uv run coworld leagues
uv run coworld download among_them --output-dir ./coworld
uv run coworld play "$COWORLD_ID" "$IMAGE" --no-open-browser
uv run coworld run-episode "$COWORLD_ID" "$IMAGE"
```

`coworld download` writes `./coworld/<coworld-id>/coworld_manifest.json` and
prints the `<coworld-id>` plus a suggested `coworld play` command. Pass that
bare id to `play` / `run-episode`, or use the full manifest path if needed.

Use `coworld play` as the replacement for the deleted local match scripts.
Use `coworld run-episode` when you want saved episode artifacts for validation.
All match, upload, submission, and inspection commands should use this
workspace's editable Coworld install through `uv run`.

Verify the active source with:

```sh
uv run python -c "import coworld; print(coworld.__file__)"
```
