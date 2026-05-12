---
name: cogamer.play
description: Run a CvC game and capture LLM-Python communication trace for analysis
---

# Play

Run a CvC game and capture trace data for analysis.

**Announce at start:** "I'm using the play skill to run a CvC game and capture the LLM-Python trace."

## Command

```bash
softmax cogames play -m <mission> -p class=cvc_policy.cogamer_policy.CvCPolicy --render=log --save-replay-file /tmp/cvc-replay.json.z
```

Defaults: mission=machina_1, steps=1000. Override via arguments passed to the skill.

## Trace Output

The CvCPolicy writes an LLM-Python communication trace to `/tmp/cvc-trace/`. Each file is a JSON with:
- `agents`: per-agent step count, LLM call count, final resource bias
- `llm_trace`: chronological list of every LLM call with prompt, raw response, parsed fields, latency

Read the trace after play to understand how the LLM and Python code interacted.

## Customization

- `--mission <name>` or `-m` (run `softmax cogames play --help` for options)
- `--steps <n>` or `-s`
- `--render gui` for visual mode, `log` for headless
- `--seed <n>` for reproducibility
- `--save-replay-file <path>` for replay data

## After Play

Read `/tmp/cvc-trace/*.json` for the LLM communication trace. Use `/cogamer.evaluate` for multi-episode scoring or `/cogamer.analyze` to diagnose issues from this run.
