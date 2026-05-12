---
name: memory-load
description: Restore Claude auto-memory from the repo. Use on startup to recover memory from a previous session.
---

# Memory Load

Restore your Claude auto-memory from the repository.

## Reference

Read `~/repo/runtime/memory/memory.md` to understand the memory system structure and conventions.

## Steps

1. **Find target** — Determine your Claude auto-memory directory at `~/.claude/projects/*/memory/`. If multiple exist, use the one matching `~/repo`.

2. **Copy from repo** — Copy all `.md` files from `~/repo/memory/` into the auto-memory directory. Create the directory if needed.
