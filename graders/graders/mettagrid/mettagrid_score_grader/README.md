# MettaGrid Score Grader

Starter Coworld grader for simple MettaGrid-style game manifests whose results expose `scores` and `steps`.

It combines final score spread, top-player margin, score magnitude, and episode length. This is intentionally simple:
it gives `amongcogs`, `diplomacog`, `hungercog`, `overcogged`, and `werecog` an initial grader until each game has
domain-specific outcome fields.

Build:

```bash
./build.sh
```
