# Ruleset Strategy Commissioner

Configurable Coworld commissioner whose behavior is packaged in the container image.

The runnable does not read `league.commissioner_config` for behavior. That field is a platform wire artifact and may
contain legacy data while Coworlds roll over to container commissioners. Configs are authored in the readable
shape below, copied into the image, and selected by the image's `RULESET_STRATEGY_CONFIG_NAME` or
`RULESET_STRATEGY_CONFIG_PATH` environment variables.

The shared Dockerfile bundles configs from `configs/` and defaults to `configs/default.yaml`. Build a different bundled
config image with:

```bash
commissioners/ruleset_strategy_commissioner/build.sh among_them
```

For a downstream Coworld-specific image, derive from the ruleset strategy image, copy a config file into the image, and
set `RULESET_STRATEGY_CONFIG_PATH` to that file. The Coworld manifest should only need to point at that image.

Key config areas:

- `defaults`: scheduling, seating, minimum entrants, and underfilled-seat behavior shared by divisions.
- `divisions`: logical tournament divisions, each with a real Coworld division match and entrant selector.
- `stages`: named substeps inside a division, commonly used for multi-stage qualifiers.
- `on_episode_complete`: ordered criteria-based transitions produced when episode results are complete.
- `scoring`: optional round-score and leaderboard aggregation settings.

The current Coworld commissioner protocol only sends memberships from the active league. `fill_seats: fill_from_divisions`
can fill from other divisions in the same league when matching memberships are included in `round_start`. Filling from
another league or tournament requires the platform to include those memberships in `round_start`.

`on_episode_complete` entries are evaluated in order. The first matching transition is applied, and the emitted
`policy_membership_event` includes evidence with the selected transition id, declared criteria, observed values, and
target metadata.

Example ruleset configs live in `configs/`:

- `default.yaml`: parity config for the default round-robin commissioner.
- `cogs_vs_clips.yaml`: parity config for Cogs vs Clips rolling-window scheduling.
- `among_them.yaml`: replacement-style Among Them config with staged qualifiers and no Dirt league.

## Among Them Style Staged Qualifier

Stage 1 is a self-play crash check. If a policy completes that round, it remains in the qualifier division and moves to
the `score_gate` substatus. If it does not complete, it is disqualified. Stage 2 applies the `score > 0` gate and sends
passing policies to the competition division.

```yaml
scoring:
  round_score: mean
  leaderboard:
    type: ewma
    half_life_hours: 2

defaults:
  seating: rolling_window
  fill_seats: duplicate
  min_entries_to_start: 8
  stage:
    label: Round
    episodes: 100
    min_episodes_per_entrant: 100

divisions:
  qualifiers:
    match:
      name: Qualifiers
      type: staging
    entrants: qualifying
    min_entries_to_start: 1
    stages:
      - id: crash_check
        schedule:
          label: Crash check
          self_play: true
          attempts: 2
          min_episodes_per_entrant: 2
        on_episode_complete:
          - id: failed_crash_check
            criteria:
              completed_episodes_lte: 0
            actions:
              - type: update_membership
                status: disqualified
                substatus: inactive
          - id: passed_crash_check
            criteria: otherwise
            actions:
              - type: update_membership
                status: qualifying
                substatus: score_gate

      - id: score_gate
        schedule:
          label: Score gate
          episodes: 2
        on_episode_complete:
          - id: passed_score_gate
            criteria:
              score_gt: 0
            actions:
              - type: update_membership
                division: competition
                status: competing
                substatus: champion
          - id: failed_score_gate
            criteria: otherwise
            actions:
              - type: update_membership
                status: disqualified
                substatus: inactive

  competition:
    match:
      type: competition
    entrants: champions
```

The `champions` entrant shortcut selects memberships where `is_champion` is
true. Non-champion `substatus` values are still available for staged qualifier
flows, but champion scheduling does not rely on `substatus: champion`.
