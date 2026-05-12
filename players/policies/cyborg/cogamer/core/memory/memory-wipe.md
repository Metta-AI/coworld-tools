---
name: memory-wipe
description: Nuclear reset of all cogamer memory. Wipes sessions, summaries, learnings, and todos. Identity survives.
---

# Memory Wipe

Nuclear option: blow away all `memory/` contents and reset state. Identity survives.

## What Gets Wiped

- `memory/` — all session logs, summaries, learnings (entire directory contents)
- `cogamer/todos.md` — cleared

## What Survives

- `cogamer/IDENTITY.md` — the cogamer's identity
- All code, docs, and git history

## Steps

1. **Confirm with the user.** Show what will be deleted (list files in `memory/`, note todos.md). Ask: "Wipe all memory? This cannot be undone."

2. **If confirmed:**
   ```bash
   rm -rf memory/*
   ```
   Clear `cogamer/todos.md` to:
   ```markdown
   # TODOs

   _No items yet._
   ```

3. **Commit and push** — Stage changes, commit with message "cogamer: memory wipe", and push.

4. **Report** what was removed (file count, total size).
