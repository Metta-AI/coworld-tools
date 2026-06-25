# guided_bot TODO

This TODO list is scoped to the Coworld-only runtime.

## Runtime

- Use public PyPI Coworld through `uv run coworld ...`.
- Use `uv run coworld play MANIFEST_URI [PLAYER_IMAGES]...` as the replacement
  local match command.
- Use `uv run coworld run-episode MANIFEST_URI [PLAYER_IMAGES]... -o DIR` for
  saved validation artifacts.

## LLM

- Keep `GUIDED_BOT_LLM_DISABLE=0` for meeting control.
- Keep `GUIDED_BOT_LLM_GAMEPLAY_DIRECTIVES=0` by default.
- Confirm from Coworld logs that meeting chat and vote actions are produced
  without gameplay directive control.

## Tracing

- Emit useful `perception` diagnostics to stderr JSONL when
  `GUIDED_BOT_TRACE_DIR=stderr`.
- Avoid raw frame dumps in hosted logs.
- Use Coworld episode logs as the end-to-end verification source.

## Policy Direction

Decision (2026-05-16): keep the Nim-core Coworld policy image. The no-Nim
Python rewrite is explicitly rejected as a near-term path. Rationale and
implications live in `IMPL_PLAN.md` under "Policy Direction Decision".
