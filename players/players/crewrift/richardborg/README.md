# Richard Borg

Richard Borg is a Crewrift player built on the fixed Crewborg runtime. It keeps
the deterministic movement, task, kill, report, and vote mechanics, but swaps in
a meeting LLM context with canonical observation memory.

The markdown files under `memory/` are part of the player:

- `system.md` is the meeting LLM system prompt.
- `summary.md` describes the memory contract.
- `templates.md` lists the concrete observation templates the LLM should use.

Hosted Bedrock works through the same Coworld path as Crewborg: upload with
`--use-bedrock`, which supplies `USE_BEDROCK=true` and Bedrock-capable AWS
credentials in the player pod. Local direct Anthropic still works with
`CREWBORG_LLM_MEETINGS=1` and `ANTHROPIC_API_KEY`; local Bedrock can be forced
with `CREWBORG_LLM_MEETINGS=1` plus `CLAUDE_CODE_USE_BEDROCK=1`.
