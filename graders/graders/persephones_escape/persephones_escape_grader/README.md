# Persephone's Escape Grader

Starter Coworld grader for Persephone's Escape.

It scores `results.json` using decisive winner presence, score spread, elapsed ticks, and populated player results.
The heuristic is intentionally conservative so draws or empty smoke runs do not rank as highly as completed team
outcomes.

Build:

```bash
./build.sh
```
