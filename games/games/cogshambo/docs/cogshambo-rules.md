# Cogshambo Rules

Cogshambo combat is debate-driven color conversion.

## Core Loop

- Each cog has a color, fixed traits, active achievements, and color-specific doubt meters.
- Cogs of the same color do not debate each other.
- Each tick, the game chooses debate pairings and movement turns. Cogs do not independently decide to start debates.
- The game tries to start at least one valid debate per tick when possible, up to the configured per-tick maximum.
- When two adjacent cogs of different colors can see each other, or two different-color venue cogs share a room, the game may pair them for debate.
- Each tick, the game asks 1-4 eligible cogs to move. Venue cogs choose from offered room destinations.
- A debate lasts up to 5 rock/paper/scissors rounds by default.
- The same two cogs cannot debate again until the pair cooldown expires. The default cooldown is 600 ticks, which is 5 minutes at the normal 500ms server tick.
- After entering a room, a cog cannot leave again until the room movement cooldown expires unless it is alone in that room.

## Debate Rounds

Each debate round resolves simultaneous choices:

- `reason` beats `spin`
- `spin` beats `passion`
- `passion` beats `reason`
- same choices draw

Round outcomes are `win`, `lose`, or `draw` from the first participant's perspective. On a decisive round, the loser gains doubt toward the winner's color. On a draw, no direct doubt changes and the debate continues unless it was the final round.

The debate ends when:

- 5 rounds resolve by default
- a cog converts

Cogs cannot exit a debate early.

## Doubt And Conversion

Doubt is tracked per target color. Doubt toward the cog's current color reinforces that cog and reduces opposing-color doubt. Doubt toward another color makes the cog more likely to flip.

When doubt toward an opposing color reaches 100 by default, the cog converts to that color. After conversion:

- the cog's color flips to the winning color
- the active debate ends
- the cog keeps its name, prompt, traits, achievements, and score
- doubt drops to 50% of the threshold toward the previous color by default

Base doubt does not decay on its own. It changes from debate rounds, witness adjustments, reinforcement, and trait-specific modifiers.

## Witnesses

Every non-debating cog in the same room as both debaters witnesses decisive debate rounds. Witnesses adjust by a smaller amount than the loser:

- witnesses on the winner's color are reinforced, reducing opposing-color doubt
- other witnesses gain a small amount of doubt toward the winner's color

Witness adjustment uses the same trait resistance rules as other non-direct doubt.

## Traits

Each cog has two trait slots drawn from the same trait pool:

- `stubborn`: receives less direct debate doubt.
- `insular`: receives less indirect doubt, including witness doubt.
- `iconoclast`: resists doubt from the unique largest color.
- `conformist`: resists doubt from the unique smallest color.
- `defector`: loses certainty while its team is too large.
- `bandwagoner`: recovers certainty while its team share is above the configured threshold.
- `martyr`: when converted, restores certainty to same-room former teammates.
- `doubter`: loses certainty on drawn debate rounds.
- `diplomat`: loses certainty when witnessing its majority team win nearby.
- `heretic`: loses certainty when entering a room with more than 3 total cogs.
- `zealot`: never converts; certainty clamps at the configured minimum. Zealots are seed-only and cannot be selected in creation/profile controls.
- `forceful`: decisive debate wins add more doubt.
- `charismatic`: applies the trait's configured witness doubt amount after winning debate rounds.
- `contrarian`: flips teams when its team has more than 90% of cogs, shortens repeat-pair debate cooldowns, discounts majority-color pressure, and loses certainty in all-same-team rooms.
- `hippie`: reason wins hit opponents less and reason losses hurt more; passion wins hit opponents more and passion losses hurt less.
- `rationalist`: configurable win and vulnerability multipliers for `reason`.
- `spinner`: configurable win and vulnerability multipliers for `spin`.
- `passionate`: configurable win and vulnerability multipliers for `passion`.
- `avenger`: after a same-room teammate converts, its next win against the converter's color hits harder.
- `insurgent`: while uniquely smallest, wins apply extra witness doubt.
- `polarizer`: wins lower certainty for low-certainty same-team witnesses.

## Achievements

Each cog has active achievement assignments. Completing an achievement awards the achievement's configured points, normalized by that cog's lifetime in ticks. Completed, failed, and currently active achievements are tracked per cog.

## Editable Config

The in-app Config page exposes all rule parameters, trait descriptions, trait modifier inputs, and achievements. Parameter edits are saved through `/api/config` and affect subsequent simulation ticks.
