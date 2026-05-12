# Adaptation & Meta-Strategy

How to change strategy mid-game and across games.

## Reading the Game State

Before deciding what to do, answer:

1. **Am I winning or losing?** Score comparison, territory control, resource advantage.
2. **What phase is the game in?** Early (explore/setup), mid (execute/contest), late (optimize/close).
3. **What is the opponent doing?** Aggressive, defensive, economic, unknown.
4. **What's my biggest constraint?** Time, resources, information, position.

## Adaptation Triggers

Switch strategy when:

| Signal | Interpretation | Action |
|---|---|---|
| Score falling behind | Current approach not working | Try alternate strategy |
| Score plateau | Diminishing returns on current strategy | Shift to next phase |
| Opponent strategy detected | New information | Counter their approach |
| New area discovered | Map layout changes options | Re-evaluate routes and targets |
| Resource depletion | Primary resource exhausted | Switch to secondary or new source |
| Ally/teammate signaling | Coordination opportunity | Complement their role |

## The OODA Loop

For real-time strategy, the classic military decision cycle applies:

1. **Observe**: Frame parsing, snapshot building
2. **Orient**: Memory update, situation assessment
3. **Decide**: Brain's `decide()` method
4. **Act**: Execute the chosen command

The LLM operates on a slower OODA loop (every ~200 ticks) that sets the strategic
context for the brain's fast loop.

## Cross-Game Learning

The evolution pipeline accumulates patterns across games:

- **What worked?** Strategies that correlated with high scores
- **What failed?** Mistakes that recurred across multiple games
- **Proven rules**: "IF X THEN Y" patterns that appeared in 2+ analyses

This knowledge is injected into the LLM's system prompt as "cross-game intelligence",
giving each new game the benefit of prior experience — even with a different map or seed.

## When NOT to Adapt

Sometimes the best move is to stay the course:

- **The plan is working** — don't fix what isn't broken
- **Noise vs signal** — a temporary setback isn't a reason to abandon strategy
- **Commitment costs** — switching has overhead (time, resources, position)
- **Near completion** — if you're 80% through a plan, finish it
