# Adaptive ladder commissioner — design

*Target: `ruleset_strategy_commissioner`, two-team leagues (CTF first). 2026-07-22.*

## Current behavior (what we're changing)

- Every `schedule_interval_minutes` (CTF: 30) the platform opens a round. The commissioner
  schedules the whole episode list up front (`schedule_entries` in
  `common/ruleset_strategy/scheduling.py`), the server drips it out through the dispatch
  throttle (CTF: 16 in flight, ~5.5 min/episode).
- CTF uses circle-method round-robin (`_two_team_round_robin_pair`) with
  `min_episodes_per_entrant: 10`: with N entrants that's `ceil(10·N/2)` episodes,
  ~1 episode per pair when N ≈ 11. Every entrant gets the same 10 episodes regardless of
  whether its score has been flat for a day or it joined an hour ago.
  (There is no separate per-round episode cap today; `min_episodes_per_entrant` drives the
  count and the throttle only limits concurrency.)
- Round score = per-episode win rate (`round_score: win`). Board score = **weighted mean**
  of a player's round scores with a wall-clock 2 h half-life EWMA
  (`BaselineCommissioner.rank_division`). Two consequences that shape this design:
  1. A player's first round in the window IS their board score — there's no warm-up from
     zero. Settling speed = per-round score accuracy × rounds per hour.
  2. Board history is keyed by *player*, so a new champion version inherits the player's
     EWMA and needs ~2–4 h of rounds to pull the board to its true level.

**Problem:** compute is spent uniformly, but information isn't uniform. Stable policies'
round scores barely move the EWMA (their history already says the same thing); new or
trending policies are exactly where per-round noise delays the board, and they get no
extra sampling. Also, because rounds are 30 min apart and ~40 min long, the EWMA gets at
most 2 samples/hour for everyone.

## Goals

1. Policies that are **new or moving** settle to their true board score in ~1 h
   (today: ~2–4 h).
2. Spend materially fewer episodes on **settled** policies without letting their board
   entry go stale or noisy.
3. Preserve the win-EWMA leaderboard semantics and score comparability: every entrant's
   round score must remain an unbiased estimate against the same opponent distribution.
4. Commissioner-only change: no platform or protocol changes, no mid-round scheduling
   (the round contract stays "one `ScheduleEpisodes` batch at round start").

Non-goal (v1): changing the leaderboard type, half-life, or round-completion /
DQ machinery.

## Design: uncertainty-weighted episode budgets over a rotating round-robin

Everything below runs at round start from data already in `RoundStart.recent_results`
(per-round `policy_version_id, round_number, rank, score`).

### 1. Per-entrant uncertainty `u_i ∈ [0, 1]`

Three cheap, explainable signals, combined with `max`:

- **Newness** — rounds on record for the entrant's *current policy version*:
  `u_new = max(0, 1 − rounds_on_record / settle_rounds)` (`settle_rounds ≈ 6`).
  A freshly promoted champion ⇒ 1.0.
- **Volatility** — std of the player's last `k` round scores (win rate, so already on
  [0,1]): `u_vol = clamp(std / volatility_scale)` (`volatility_scale ≈ 0.15`, `k ≈ 6`).
- **Trend** — `|mean(last 3) − mean(prior 3)| / trend_scale` clamped
  (`trend_scale ≈ 0.10`). Catches "same version, field changed around it"
  (game updates, new rival) even when variance is low.

`u_i = max(u_new, u_vol, u_trend)`. Fewer than `k` rounds on record ⇒ treat missing
history as uncertainty (u_new dominates anyway).

### 2. Episode budget `d_i`

`d_i = round(d_min + u_i · (d_max − d_min))`, with:

- `d_min` = existing `min_episodes_per_entrant` (drop CTF's to **4**): the freshness
  floor. Win-rate granularity at d=4 is 0.25, which the EWMA smooths over rounds.
- `d_max` = new `max_episodes_per_entrant` (CTF: **16**), effectively capped at `N−1`
  so within one round no pair meets more than ~once (small fields: allow wrap cycles
  when `N−1 < d_max` is configured explicitly).
- Safety cap: new `max_round_episodes` bounds `Σd_i / 2` (an all-new field — e.g. after a
  game update requalifies everyone — degrades to a uniform dense round, not an unbounded
  one).

### 3. Pairing: budget-constrained circle round-robin

Keep the circle method — it already gives per-cycle perfect matchings with rotating
opponents — and filter it by budgets:

```
remaining[i] = d_i
for cycle in offset, offset+1, ...:            # circle-method cycles
    for (a, b) in cycle_pairs(cycle):
        if remaining[a] > 0 or remaining[b] > 0:
            emit episode(a, b)
            remaining[a] -= 1; remaining[b] -= 1   # floor at 0
    stop when all remaining == 0 (or cycle guard d_max + N)
```

- **Movers** stay in nearly every cycle ⇒ face ~the whole field ⇒ their single-round win
  rate is computed against the same opponent population as today's full round-robin —
  unbiased, and with up to `d_max` samples instead of 10.
- **Settled** entrants play their `d_min` cycles plus incidental episodes when a mover's
  cycle drafts them. With `d_max ≤ N−1`, a settled entrant meets any given mover at most
  ~once per round, so incidental load spreads evenly (~`Σ extra/(N−1)` each) and their
  opponent mix stays close to uniform. Residual per-round bias averages out across rounds
  because the EWMA aggregates several rounds and the ring rotates (next point).
- **Ring offset rotates per round** (seeded like `shuffled_window`'s
  `_round_shuffle_seed`, i.e. wall clock — never reused on reschedule). Today
  `job_index` restarts at 0 every round, so every round replays cycles 0..9 in the same
  entry order: with N > 21 some pairs would literally *never* meet, and even at current N
  the repeat pairing is always the same. The rotation fixes this independently of
  adaptivity and should apply to the non-adaptive path too.
- Seat layout is unchanged: this plugs in where `_two_team_round_robin_pair` is called
  today; `team_interleaved` / `team_blocks` seating code is reused as-is.

All episodes count toward both participants' round scores, exactly as today — no
"exhibition" episodes, nothing new for the scorer, DQ transitions
(`completed_episodes_*`, `bench_scoreless_after`) see the same shapes.

### 4. Cadence: turn the savings into settling speed

With today's CTF field (N ≈ 10, ~2 movers): current rounds are 50 episodes; adaptive
rounds are ~30 (movers 9 each, settled ~5–6 including incidentals) — **~40 % fewer
episodes**, finishing in roughly half the wall time at the same concurrency. Spend that
directly on cadence: drop `schedule_interval_minutes` 30 → **15**. Net effect at
unchanged cluster load:

- movers: ~9 accurate episodes/round × 4 rounds/h (vs 10 × 2 today) ⇒ EWMA converges
  roughly **2× faster** in wall-clock terms;
- settled: ~5 episodes/round × 4 rounds/h ≈ the same 20 episodes/h they get today, just
  sliced into more, smaller EWMA samples.

Cadence stays a plain config constant in v1 (adaptive intervals would need platform
scheduling changes — out of scope).

### Config sketch (`ctf.yaml`)

```yaml
schedule_interval_minutes: 15      # was 30 — step 2 of rollout, after budgets soak

defaults:
  seating: team_interleaved        # unchanged
  team_count: 2
  stage:
    label: CTF round
    episodes: 2
    min_episodes_per_entrant: 4    # was 10 — now the settled-entrant floor
    max_episodes_per_entrant: 16   # new — mover ceiling (effective: min(16, N-1))
  adaptive:                        # new block; absent ⇒ exactly today's behavior
    enabled: true
    settle_rounds: 6
    volatility_rounds: 6
    volatility_scale: 0.15
    trend_scale: 0.10
    max_round_episodes: 160
```

Backwards compatibility: no `adaptive` block (or `enabled: false`) ⇒ current uniform
scheduling, all other leagues unaffected. `max_episodes_per_entrant` without `adaptive`
is a validation error.

### Observability

Per round, emit the budget table (policy, rounds_on_record, u_new/u_vol/u_trend, d_i,
episodes actually played) via the existing `CommissionerCalcStep` mechanism so the
allocation is auditable from the platform UI, plus a log line per entrant. This is the
first thing we'll want when someone asks "why did my policy only get 4 episodes?".

### Gaming / fairness review

- *Sandbagging to farm episodes*: deliberately varying your score raises `u_vol` ⇒ more
  episodes, but episodes aren't a resource — the board only rewards winning, and extra
  samples make the EWMA track your (worse) true level faster. No incentive.
- *Version churn*: resubmitting daily keeps `u_new` high ⇒ more episodes but, again, just
  faster convergence to truth. The board's player-keyed EWMA already prevents
  score-reset abuse.
- *Opponent selection*: entrants don't influence pairing; budgets derive from public
  round history. Stratification keeps expected opponent strength equal for all entrants,
  which is the invariant that keeps win rates comparable (goal 3).

### Risks

- **Settled-entrant quantization**: d=4 makes single-round scores coarse (0/0.25/…/1).
  Mitigated by 4 rounds/h feeding the EWMA; if the board jitters, raise `d_min` to 6.
- **Trend detector lag**: `u_trend` needs ~3 rounds to fire after a regime change. A
  game-update canonical retarget already requalifies the field (crash check), which
  resets `u_new` via new versions in practice; accept the lag otherwise.
- **`recent_results` window**: uncertainty math assumes the platform's window covers
  ≥ `settle_rounds + volatility_rounds` rounds per entrant. Verify at implementation
  time; if short, clamp horizons to the window.

## Alternatives considered

1. **MMR (OpenSkill) board with sigma-targeted matchmaking** — the "principled" version:
   schedule pairs that maximize information, stop when σ settles. Rejected for v1: it
   changes leaderboard semantics mid-season (the board identity is win-EWMA, and the
   ranking change would relitigate every league's standings), and `mmr_neighbors`
   machinery only orders entries — the full design is a much bigger blast radius for the
   same "sample the uncertain ones more" effect.
2. **Two-tier rounds** (active pool dense RR + stable pool light refresh) — a special
   case of this design with binary `u`; simpler mental model but cliff effects at the
   tier boundary and a second scheduling code path. The continuous budget subsumes it.
3. **Uniform-but-smaller rounds at higher cadence** (drop everyone to 5 episodes, run
   every 15 min) — half the win: movers' per-round scores stay noisy, so their EWMA
   still needs many rounds. No targeting.
4. **Mid-round adaptive scheduling** (successive halving inside a round as results
   stream back over the websocket) — the server already streams results mid-round, so
   this is feasible, but it breaks the "schedule once at round start" contract in
   `server.py`, complicates reschedule/crash recovery, and v1's between-round adaptation
   already captures most of the value. Revisit only if 15-min rounds prove too coarse.

## Implementation plan

1. `common/ruleset_strategy/uncertainty.py`: pure `recent_results → {pvid: (u, parts)}`
   + budget mapper. Unit tests: new entrant, flat veteran, trending veteran, sparse
   history, empty history.
2. `scheduling.py`: budget-filtered circle-RR generator + per-round ring offset
   (offset applies to the existing non-adaptive two-team path as well). Tests in
   `tests/test_commissioner_strategies.py`: budgets honored, `d_max ≤ N−1` pair-repeat
   bound, odd fields/byes, all-settled and all-new fields, `max_round_episodes` cap,
   pinned-seed determinism, opponent-distribution balance (χ² -ish sanity), transition
   observation shapes unchanged.
3. `config.py`: `AdaptiveConfig` block + `max_episodes_per_entrant` + validation;
   `scoring_mechanics` description gains a sentence so players see the rule.
4. Calc-step/logging observability.
5. Rollout (CTF first): ship image via `uv run coworld patch-commissioner ctf …` with
   budgets on and interval still 30 min; watch 3–4 rounds' budget tables and board
   continuity; then drop the interval to 15. Other leagues opt in by config only.
