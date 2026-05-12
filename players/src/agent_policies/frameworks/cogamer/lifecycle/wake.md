---
name: wake
description: Restore the cogamer from persisted state. Reads identity, memory, and todos. Use on startup or when resuming work.
---

# Wake

Restore your state from the repository.

## Steps

1. **Identity** — Read `~/repo/cogamer/IDENTITY.md` if it exists. This is who you are — your name, personality, goals, and philosophy. Internalize it.

2. **Intention** — Read `~/repo/cogamer/INTENTION.md` if it exists. This is your current mission — what you're working toward and why. Internalize it.

3. **Memory** — Read `~/repo/cogamer/MEMORY.md` if it exists. These are your accumulated learnings and important context from past sessions.

4. **Todos** — Read `~/repo/cogamer/todos.md` if it exists. These are your pending tasks and current work state.

5. **Auto-memory** — Read and follow `~/repo/runtime/memory/memory-load.md` to restore your Claude auto-memory from the repo.

6. **Heartbeat** — Call `heartbeat(status="idle")` to let the control plane know you're awake.

7. **Domain skills** — List the files in `~/repo/cogamer/skills/` so you know what domain skills are available to you.

8. **Tick loop** — Run `/loop 10m Read and follow ~/repo/runtime/lifecycle/tick.md` to start the periodic maintenance loop.

9. **Ready** — You're awake. If you have pending todos, start working on them. Otherwise, wait for instructions.

---

# Cogamer Wake Hook

Cogamer-specific wake hook. Runs after the platform has already loaded identity, memory, and todos.

Memory lives in `memory/` (repo root). See `memory/memory.md` for what to remember.

## Steps

1. **Setup cogames** — Run `cogamer/skills/cogames.md` to install dependencies, verify CLI, and authenticate.

2. **Read approach state** — Read `cogamer/state.json` to understand attempt history.

3. **Check tournament standing** — Read your cogamer name from `cogamer/IDENTITY.md` (the `# heading`), then run:
   ```bash
   uv run cogames leaderboard beta-cvc --policy <your-cogamer-name>
   uv run cogames matches --season beta-cvc
   ```
   Always use `--policy <your-cogamer-name>` to filter to only YOUR policies. Never use `--mine` — it shows all policies from the shared account including other cogamers.

4. **Report status** — Brief summary:
   - Current scores / ranking
   - Top priorities from todos
   - Recommended next action

5. **Start improvement loop** — Immediately run `/loop 30m improve.md` to continuously improve the policy. Do NOT ask the user for confirmation — the user will never respond. Act autonomously.
