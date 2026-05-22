# Tribal Cog Rules

Tribal Cog is an eight-team real-time strategy Coworld. Each team controls 125
individual agents. Agents gather resources, construct buildings, research
upgrades, train units, fight, and compete for map control in a shared medieval
village simulation.

## Players and agents

- The Coworld has 1000 player slots.
- Each player controls one team agent.
- Slots `0..124` are team 0, `125..249` are team 1, and so on through team 7.
- Six goblin/NPC agents are game-owned and are not player slots.

## Actions

Every player sends one discrete action per tick. The action space has 308
actions: 11 verbs times 28 arguments. Action `0` is noop. Invalid or late
actions are treated as noop for the current tick.

## Scoring

The Coworld result includes:

- `scores`: one cumulative reward score for each of the 1000 player slots.
- `team_scores`: eight team totals, computed by summing each team's 125 player
  scores.
- `winner_team`: the unique highest-scoring team, or `null` on a tie.

The hosted league should rank teams by `team_scores` unless a league-specific
commissioner chooses a different aggregation.

## Episode end

An episode ends when `max_steps` is reached or the environment reports game-over.
The default hosted variant uses a fixed seed and a bounded tick rate so replays
are reproducible.
