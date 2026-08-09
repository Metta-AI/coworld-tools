# Remaining shared commissioner migrations

This implementation covers the enabled container leagues whose commissioner
source or default configuration is owned by `coworld-tools`, rather than by a
dedicated game repository. Directly postable disabled settings, captured
manifest topology, and retirement gates live under `platform_migrations/`.
Validate all three with `uv run pytest tests/test_platform_migrations.py` from
the `commissioners/` directory. It performs no production mutation.

## Inventory

| League | Competition division | Shared source | Disposition |
| --- | --- | --- | --- |
| Cogtank (`league_b99b668b-29cc-42dc-849e-dd573bf59003`) | `div_7ff13a32-59e9-4bfb-a118-c51eca436bd0` | `configs/cogtank.yaml` | Migrate with `team_pair` + Elo; game repo owns the detailed cutover proof |
| Nomic Fable (`league_33f50eed-02ae-4b80-92d9-536cb900a15a`) | `div_a1784629-d985-4701-8da2-e8496cb992fc` | default ruleset strategy | Migrate directly to fixed-seat round robin + score ranking |
| Proxywar (`league_cb60d526-ecfd-4836-ab3a-81fc6cf7dc42`) | `div_b54268ee-6b2f-4156-9c2a-8542645e31bc` | `configs/proxywar.yaml` | Ready with scaling-rung partitioning and size-specific variant rotation |

Nomic Fable and Proxywar have no dedicated `Metta-AI/coworld-<slug>` source
repository to carry this plan, so this shared owner is their migration surface.

## Cogtank cleanup

The game repository specifies the target: eight seats, two slot-parity teams,
`team_pair`, `do_not_run` below two champions, and fresh Elo standings. After
the live seed is platform-owned and has soaked for several cycles:

1. verify no enabled seed or pinned Coworld still resolves the Cogtank config;
2. retire the catalog/config entry and container image in a separate PR; and
3. retain Git history as the old-standings and rollback audit trail.

Do not delete shared code as part of the ownership flip.

## Nomic Fable target

Nomic Fable's generic three-seat, mean-score round robin needs no uploaded
scheduler logic. Its executable settings are
`platform_migrations/settings/nomic_fable.json`; the important shape is:

```yaml
round_interval_minutes: 30
ladder:
  enabled: false
  scheduler:
    strategy: round_robin
    insufficient_players: multiple_seats
    min_episodes_per_entrant: 8
  ranking:
    algorithm: score
    direction: maximize
    round_scoring_rule: mean
    standing_aggregation: ewma
    half_life_hours: 2
  fulfillment:
    allowed_failures: 0.05
    retry_times: 2
  divisions:
    - division_id: div_a1784629-d985-4701-8da2-e8496cb992fc
      name: Competition
      disqualify_after_consecutive_failures: 3
```

Qualification is the legacy
`div_38221c61-3e74-41ef-b330-f34d6f5201ee`. The settings replace its generic
container crash check with one three-seat self-play episode gated on
`result.turns_played >= 1`; archive the old division only during cutover. Prove
frozen plans for one, two, and at least three champions, including uncredited
duplicate seats. Fresh platform standings are expected.

## Proxywar target

Proxywar's platform target selects the largest legal 2/4/8/12-player rung,
partitions fields above 12, and rotates that rung's Coworld map by round. The
executable settings are `platform_migrations/settings/proxywar.json`; their
size-to-variant mapping is checked against the minimal topology captured from
canonical Proxywar 0.1.27.

The landed typed platform capability provides:

- ordered rungs `[2, 4, 8, 12]` and coverage when the field exceeds one table;
- deterministic, replayable variant rotation frozen into each round plan;
- validation that every selected variant admits the selected seat count;
- one champion per player, duplicate seats uncredited only when a short rung
  explicitly permits them; and
- `score` ranking with a mean round fold and two-hour EWMA, matching the active
  ruleset-strategy config. Existing container standings are not imported.

The legacy `rolling_window` commissioner does not partition fields above 12:
its overlapping windows can give champions unequal appearance counts in one
round. Platform partitioning is an intentional fairness repair, not exact
seating parity; every champion receives eight credited appearances while
duplicate pad seats stay uncredited. Acceptance proves that invariant over
field sizes 1, 2, 3, 4, 7, 8, 11, 12, 13, and 24 across a full rotation cycle,
while preserving the 30-minute cadence, mean score fold, and two-hour EWMA.
After that proof operators can post the already-disabled settings for
Competition, `div_b54268ee-6b2f-4156-9c2a-8542645e31bc`.

## Common cutover and retirement gate

For each league separately: capture the seed and League state; write/read
settings disabled; pause and drain all container rounds; patch the seed's full
overrides to `commissioner_key: platform`; enable/unpause; and prove one
idempotent Temporal cycle with settled results, replays, and standings. Never
run both schedulers.

Rollback drains Temporal, disables the ladder, and restores container ownership
through the seed before unpausing. `retirement_contract.json` keeps Cogtank and
Proxywar artifacts in `rollback_ready`; changing one to `retired` makes the
validator require its old config to be absent. This turns shared cleanup into a
reviewable state transition instead of an untracked deletion.
