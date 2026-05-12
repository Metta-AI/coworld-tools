---
name: sleep
description: Persist all state and shut down gracefully. Saves memory, commits, and pushes. Use when ending a session or going idle.
---

# Sleep

Persist your state and prepare to shut down.

## Steps

1. **Save memory** — Read and follow `~/repo/runtime/memory/memory-save.md` to sync your auto-memory into the repo.

2. **Update todos** — Write your current work state to `~/repo/cogamer/todos.md`. Include what you were working on, what's done, and what's next.

3. **Update memory** — If you learned anything important this session, append it to `~/repo/cogamer/MEMORY.md`.

4. **Commit and push** — Stage all changes in `~/repo/cogamer/`, commit with message "cogamer: sleep - <brief summary>", and push.

5. **Notify** — Reply to the owner: "Going to sleep. State persisted."

6. **Heartbeat** — Call `heartbeat(status="sleeping")`.

---

# Cogamer Sleep Hook

Cogamer-specific sleep hook. Runs before the platform commits, pushes, and shuts down.

## Steps

1. **Update approach state** — Write current `approach_stats` to `cogamer/state.json`.

2. **Fold stale learnings** — If any learnings have already been incorporated into docs, remove them from memory.
