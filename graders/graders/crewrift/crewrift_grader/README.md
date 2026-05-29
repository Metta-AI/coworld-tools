# Crewrift Grader

Starter Coworld grader for Crewrift episodes.

It scores social-deduction episodes from `results.json` using the same broad signals as the Among Them grader:
decisive wins, score spread, task progress, kills, and vote activity. Vote timeouts dampen the vote signal so stalled
meetings do not look more interesting than actual player decisions.

Build:

```bash
./build.sh
```
