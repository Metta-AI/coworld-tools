---
name: memory-save
description: Sync Claude's auto-memory into the repo so it survives container restarts. Commits and pushes.
---

# Memory Save

Sync your Claude auto-memory into the repository.

## Reference

Read `~/repo/runtime/memory/memory.md` to understand the memory system structure and conventions.

## Steps

1. **Find auto-memory** — Look for memory files in `~/.claude/projects/*/memory/`. These are the memories Claude Code automatically maintains.

2. **Copy to repo** — Copy all `.md` files from the auto-memory directory into `~/repo/memory/`. Create the directory if it doesn't exist.

3. **Commit and push** — Stage all changes in `~/repo/memory/`, commit with message "cogamer: memory save", and push.
