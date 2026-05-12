# Strategy

## What Works
- **Chain-building**: Capture junctions near existing friendly junctions to expand the alignment network outward from hub
- **Pressure budgets**: Phase-based role allocation (more miners early, transition to aligners)
- **Heart batching**: Aligners collect 3+ hearts before heading out
- **Sticky targets**: Persist on a target unless a significantly better one appears (threshold 3.0)
- **Claim system**: Agents claim junctions to avoid duplicating effort

## What To Try
- **Hotspot tracking**: Like alpha.0, track scramble events per junction — deprioritize junctions that keep getting scrambled
- **Wider enemy AOE for retreat**: Alpha.0 uses 20, we use 10. May explain survival difference
- **LLM stagnation detection**: Use LLM to detect when agents are stuck and adjust directives
- Dynamic role switching based on game state
- Better junction discovery — agents miss junctions behind walls
- Read teammate vibes for coordination
- Study opponent replays via `cogames match-artifacts <id>` for new strategies

## Dead Ends (Don't Retry)
- Heart batch target changes — 3 for aligners is the sweet spot
- Outer explore ring at manhattan 35 — agents die before reaching targets
- Remove alignment network filter — required by game mechanics
- Expand alignment range +5 — targets unreachable junctions
- Resource-aware pressure budgets — too aggressive scaling
- Spread miner resource bias — least-available targeting is better
- Reorder aligner explore offsets — existing order works better
- Increase claim penalty (12→25) — pushes aligners to suboptimal targets
- More aligners (6) / fewer miners (2) — economy can't sustain
- Wider A* margin (12→20) — slower, wastes ticks
- Emergency mining threshold 50 or 10 — hurts more than helps
- Self-play improvements DON'T predict freeplay improvements — the two are weakly correlated

## Critical Learnings
- **Scrambler is heart-starved**: In self-play with (4,1) budget, the scrambler has 0 hearts for most of the game because 4 aligners consume all team hearts first. The scrambler is effectively useless in self-play, but still matters in freeplay
- **Junction collapse pattern**: Peak at ~7 friendly junctions (step 500), collapse to 0-2 by step 5000 in self-play. Enemy team scrambles faster than we rebuild
- **Early game is critical**: Most score comes from first 500-2000 steps. Late game contributes little
- **LLM may be the structural gap**: Alpha.0's cyborg architecture with LLM stagnation detection is likely the key differentiator
