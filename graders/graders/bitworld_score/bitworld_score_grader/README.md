# BitWorld Score Grader

Starter Coworld grader for score-array BitWorld games that do not yet need a bespoke grader.

It reads the episode bundle from `COGAME_EPISODE_BUNDLE_URI`, loads `results.json`, and writes a grade JSON to
`COGAME_GRADE_URI`. The score combines final score spread, top-player margin, and simple activity signals such as
distance walked, survival ticks, owned ships/planets, Heartleaf day progress, or Stag Hunt stats when present.

Intended initial targets: `asteroid_arena`, `big_adventure`, `heartleaf`, `infinite_blocks`, `jumper`,
`planet_wars`, `stag_hunt`, and `tribal_quest`.

Build:

```bash
./build.sh
```
