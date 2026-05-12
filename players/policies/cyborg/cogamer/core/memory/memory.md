---
name: memory
description: Describes the cogamer memory system — structure, conventions, and cleanup rules. Referenced by memory-load and memory-save lifecycle prompts.
---

# Cogent Memory

The `memory/` directory (at `~/repo/memory/`) is the cogamer's persistent memory across sessions. It stores what the cogamer has learned from working, experimenting, and iterating — things that aren't captured in code or git history.

## Domain Extensions

If `~/repo/memory.md` exists, read it for domain-specific memory structure, session log formats, and cleanup rules that extend or override the defaults below.

## Structure

```
memory/
├── sessions/          # Per-session logs
│   └── YYYYMMDD-NNN.md
├── summaries/         # Periodic rollups
│   └── weekly-YYYYMMDD.md
└── learnings.md       # Running list of insights
```

## Sessions

Each work session writes a log to `memory/sessions/YYYYMMDD-NNN.md`:

```markdown
# Session YYYYMMDD-001

- **Focus**: what was analyzed or attempted
- **Change**: what was modified (file, function, parameter)
- **Result**: improved | regressed | neutral
- **Submitted**: version name or "reverted"
- **Notes**: anything surprising or worth remembering
```

Number sessions sequentially within each day (001, 002, ...).

## Learnings

`memory/learnings.md` is a running list of insights discovered through work. Add entries when something surprising or non-obvious is learned. Each entry should be actionable — not just "X happened" but "X means Y for future decisions."

Don't duplicate what's already in project docs. Learnings are for fresh, session-specific discoveries that haven't been folded into docs yet.

## Summaries

Periodically (every ~5 sessions or weekly), write a summary to `memory/summaries/weekly-YYYYMMDD.md`:

```markdown
# Week of YYYY-MM-DD

## Sessions: N

## What moved the needle
- ...

## What didn't work
- ...

## Next priorities
- ...
```

Summaries compress session logs into actionable context. After writing a summary, old session logs can be archived or trimmed — the summary carries the signal forward.

## Cleanup

- **Sessions older than 2 weeks** with a covering summary can be deleted
- **Learnings** that have been folded into project docs should be removed from `learnings.md`
- **Summaries** accumulate indefinitely — they're compact enough to keep
- Before each work session, read the most recent summary and `learnings.md` to avoid repeating past work

## Principles

- **Write after every session** — even failed attempts produce useful signal
- **Be specific** — include concrete numbers and details
- **Keep learnings actionable** — each entry should change future behavior
- **Compress aggressively** — summaries exist so you don't have to read 50 session logs
