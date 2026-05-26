# Tribal Cog Rules

Tribal Cog is an eight-team real-time strategy Coworld. Each team controls 125
individual agents. Agents gather resources, construct buildings, research
upgrades, train units, fight, and compete for map control in a shared medieval
village simulation.

## Players and agents

- The Coworld has 8 player slots, one per town/team.
- Each town still owns 125 citizens in the simulation.
- Slots `0..7` control teams `0..7`.
- Six goblin/NPC agents are game-owned and are not player slots.
- Unconnected towns continue under the built-in default policies.

## Actions

Town controllers do not send one action per citizen. They edit the AI program
template on visible friendly buildings. When a citizen transforms through a
building, it snapshots that building's current program and keeps running that
compiled policy until it transforms again.

The bundled templates start with the same sensible behaviors Tribal Cog already
uses: gatherers collect and deposit resources, builders maintain construction,
fighters guard or attack, and settlers expand the town. Existing citizens are
not rewritten retroactively when a building template changes.

## Scoring

The Coworld result includes:

- `scores`: one cumulative reward score for each of the 8 town slots.
- `team_scores`: the same eight team totals, kept for Coworld league consumers
  that read team-level scores explicitly.
- `winner_team`: the unique highest-scoring team, or `null` on a tie.

The hosted league should rank towns by `team_scores` unless a league-specific
commissioner chooses a different aggregation.

## Episode end

An episode ends when `max_steps` is reached or the environment reports game-over.
The default hosted variant uses a fixed seed and a bounded tick rate so replays
are reproducible.
