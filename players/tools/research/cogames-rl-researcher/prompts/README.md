# AI Researcher Prompt Pack

These prompts are the meta-layer for running competitor workflows through an AI coding agent.

The scripts in `cogames-rl-researcher/scripts/` are tools; these prompt files are the workflow instructions you
paste into Codex/Claude so the agent actually drives those tools.

## Prompts

- `run-neophyte-workflow.md`
  Read CoGames tutorials, create a trainable policy from scratch, train, run neophyte startup, and verify
  submission/leaderboard status.
- `run-experienced-workflow.md`
  Same base flow, but with experienced profile and one additional resume pass for next actions.

## Quick usage

From repo root, copy one prompt into Codex/Claude:

```bash
cat cogames-rl-researcher/prompts/run-neophyte-workflow.md
```

or

```bash
cat cogames-rl-researcher/prompts/run-experienced-workflow.md
```

Or run directly in one line:

```bash
./cogames-rl-researcher/scripts/run_ai_researcher_agent_workflow.py --agent codex --profile neophyte
./cogames-rl-researcher/scripts/run_ai_researcher_agent_workflow.py --agent claude --profile experienced
```
