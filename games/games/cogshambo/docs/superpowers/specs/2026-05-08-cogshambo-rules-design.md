# Cogshambo Influence Ecology Rules Design

## Status

Approved rules direction:

- Endless social-competition sim, not a timed round game.
- Mutable color allegiance, supporting 2-color and 4-color match configs.
- Adjacent cogs can enter debates, then choose `actually`, `vibes`, `lore`, or `talk to the hand`.
- Color pressure converts cogs to the winning color; debate choices are not persistent cog state.
- Tactics are debate choices, not persistent equipment or map pickups.
- Cogs have fixed traits, fixed personal goals, and user-configured behavior prompts.
- Human viewers can inspect hidden cog metadata; cogs only observe public local state plus their own private metadata.

## Goal

Define the first-playable game rules for Cogshambo as an influence ecology. The game should be readable on a shared screen, support variable numbers of cogs arriving over time, and create social competition through color conversion, local speech, personal scoring goals, traits, memetic tactics, charisma, and terrain.

These rules extend the WebGPU first-playable design. The server remains authoritative for all gameplay state. Prompts choose actions, but prompts do not change the physics, scoring, pressure math, or hidden state rules.

## Core Loop

Cogshambo is an endless social-competition simulation. Cogs enter over time with a fully configured identity:

- name
- color
- defensive trait
- active trait
- personal goal
- user-authored behavior prompt field

New cogs spawn on random empty edge tiles. If no edge tile is open, the spawn request fails with a structured error.

Each tick, every cog's controller chooses one legal action from local observation:

- `move north`
- `move south`
- `move east`
- `move west`
- `wait`
- `speak`
- `debate <neighbor>`

Moving into another cog's occupied cell is blocked and does not start a debate or apply pressure.
Moving into terrain applies terrain rules, such as blocked movement from walls or slower movement through sand.

When a cog is already in a debate, its legal actions change to:

- `choose tactic actually`
- `choose tactic vibes`
- `choose tactic lore`
- `talk to the hand`

## Competitive State

Each cog has two mutable competitive states.

`color` is team allegiance. A match config defines the active color list. The first implementation should support both 2-color and 4-color presets, with all pressure meters, scoring, roster displays, and conversion rules using the active color list.

`debate state` is whether the cog is currently debating a neighbor. Debating cogs cannot move or start another debate until the current debate ends.

Debate tactics are Dawkins-style memetic moves. Valid tactic choices are:

- `actually` ☝️
- `vibes` ✨
- `lore` 📚

Tactic choices are simultaneous debate actions. They are not persistent cog state and do not change through color conversion.

## Speech

The `speak` action creates a short speech bubble over the cog for a configured number of ticks. Nearby cogs can see the speech in their local observation while the bubble is visible.

Speech can influence future AI decisions because prompts can react to visible messages. Speech does not directly apply pressure, change score, convert color, pick up objects, start debates, or resolve debates.

The server validates speech length and rate limits speech. Invalid or excessive speech is ignored or replaced with `wait`.

## Color Pressure

Each cog tracks one pressure meter per active color. Pressure toward the cog's current color is treated as reinforcement. Pressure toward other colors accumulates.

When an opposing color's meter reaches the conversion threshold, the cog converts to that color. On conversion:

- the cog's color changes to the winning color
- all pressure meters reset
- the cog's traits, goal, prompt, personal score, and identity stay unchanged
- future goal points are credited to the new current color
- any active debate involving the cog ends

Pressure decays over ticks. Medium first-pass tuning should require roughly 3-4 favorable debate wins to convert a normal cog. Charisma should matter over many ticks in groups.

## Debates

A cog can start a debate with an adjacent visible cog by choosing `debate <neighbor>`. Debate start rules:

- The target must be adjacent.
- Both cogs must be able to act.
- Neither cog can already be in another debate.
- If the debate cannot start, the action resolves as `wait`.

Starting a debate consumes the initiator's action for the tick. Debate choices begin on the next tick so neither participant chooses a tactic before the other knows it is debating.

While a debate is active, both cogs must choose one debate action each tick:

- `choose tactic actually`
- `choose tactic vibes`
- `choose tactic lore`
- `talk to the hand`

Tactic choices are revealed and resolved simultaneously after both participants submit actions or time out. Invalid, impossible, malformed, or timed-out debate actions become `talk to the hand`.

Tactics use this matchup loop:

- `actually` ☝️ beats `vibes` ✨ because a pointed correction punctures fuzzy social mood.
- `vibes` ✨ beats `lore` 📚 because immediate social energy can override background context.
- `lore` 📚 beats `actually` ☝️ because deeper context can reframe a narrow correction.

Debate resolution:

- If both cogs choose tactics and one tactic beats the other, the loser gains pressure toward the winner's color.
- If both cogs choose the same tactic, no pressure applies and the debate continues.
- If one cog chooses `talk to the hand`, that cog concedes a smaller amount of pressure toward the other cog's color and the debate ends.
- If both cogs choose `talk to the hand`, no pressure applies and the debate ends.
- If either cog converts color during debate resolution, the debate ends.

Debate wins are the strong tactical influence action. Traits can modify debate pressure received or applied.

## Charisma

Charisma is color-only social pressure. It ignores tactics.

Every cog emits weak charisma pressure in a small radius each tick:

- Different-color nearby cogs gain weak pressure toward the emitter's color.
- Same-color nearby cogs receive reinforcement that decays other-color pressure.

Charisma is much weaker than debate pressure. Its purpose is to make positioning and color clusters matter over many ticks.

Trait interactions:

- `charismatic` increases emitted charisma pressure.
- `contrarian` reverses emitted charisma against different-color cogs: instead of adding pressure toward the emitter's color, the aura reinforces the target's current color.
- `insular` reduces received different-color charisma pressure.

## Terrain

The map has a terrain layer. First-pass terrain types are open floor, wall, and sand.

Walls:

- Walls block movement.
- A cog cannot move into or through a wall cell.
- A wall collision does not trigger memetic pressure, debate, or other object interactions.
- Walls do not block charisma, observation, or speech visibility.
- Cogs should not spawn on wall cells.

Sand:

- Sand is passable.
- Entering sand adds movement cooldown or otherwise delays the cog's next movement by a configured number of ticks.
- Sand does not block charisma, observation, speech visibility, pressure, or debate choices.
- Sand should be visible on the board because it changes route timing.

## Debate State

`debating` is the first special cog state.

- A debating cog cannot move.
- A debating cog cannot speak.
- A debating cog cannot start another debate.
- A debating cog can only choose a debate tactic or `talk to the hand`.
- Debate duration is measured in ticks.

Debate ends when a participant uses `talk to the hand`, when both participants use `talk to the hand`, or when color conversion happens during debate resolution.

## Traits

Each cog has exactly two fixed traits:

- one defensive trait
- one active trait

Traits affect simulation rules only. They do not directly score points and do not let prompts bypass legal actions.

Defensive traits:

- `stubborn`: reduced direct debate pressure received.
- `insular`: reduced charisma pressure received from other colors.
- `iconoclast`: reduced pressure from the color with the unique highest cog count.
- `conformist`: reduced pressure from the color with the unique lowest cog count.
- `skeptic`: charisma pressure alone cannot convert this cog; direct debate pressure must cross the final threshold.

If multiple colors tie for highest or lowest cog count, `iconoclast` and `conformist` do not apply for that tied category.

Active traits:

- `forceful`: winning debate tactics apply more pressure.
- `charismatic`: emitted charisma pressure is stronger.
- `contrarian`: charisma auras push in the opposite direction against different-color cogs, reinforcing the target's current color instead of adding pressure toward the contrarian's color.
- `provocateur`: starting a debate applies a small immediate pressure toward this cog's color, but using `talk to the hand` concedes extra pressure.
- `zealot`: winning debate tactics apply more pressure while this cog's color is uniquely outnumbered and less pressure while this cog's color is uniquely leading.
- `pedant`: winning with `actually` applies more pressure, but received `actually` pressure is increased.
- `hippie`: winning with `vibes` applies more pressure, but received `vibes` pressure is increased.
- `lorekeeper`: winning with `lore` applies more pressure, but received `lore` pressure is increased.

For tactic-affinity traits, the vulnerability applies only to direct debate pressure from the matching tactic. It does not affect charisma pressure or `talk to the hand` concession pressure.

Suggested next trait candidates:

- `magnetic`: charisma radius is larger, but emitted charisma strength is unchanged.
- `diplomat`: same-tactic debate exchanges reduce both participants' opposing pressure instead of doing nothing.

## Personal Goals And Scoring

Each cog has one fixed personal goal. Goals generate personal points and color score. Points are credited to the cog's current color at the tick or event when the points are earned. Previously earned color score does not move if the cog converts later.

Goals remain fixed across color conversion. A converted cog keeps the same goal, but future goal points benefit its new current color.

Scoring is hybrid:

- status and position goals score over ticks while their condition is true
- event goals score when a relevant event happens

First goal pool:

- `majority`: scores while the cog's current color has the unique highest cog count.
- `underdog`: scores while the cog's current color has the unique lowest cog count.
- `follower`: scores while near same-color cogs with the `leader` goal.
- `leader`: scores while same-color `follower` cogs are nearby.
- `converter`: scores when this cog's pressure converts another cog to this cog's current color.
- `survivor`: scores for ticks since this cog's last color conversion.

Tie behavior should be deterministic. For first-pass readability, `majority` and `underdog` should not score during ties.

## AI Prompting

Each cog is controlled by a direct-action prompt. The prompt receives local observation and chooses a legal action for the current state. Outside debate, legal actions include `move`, `wait`, `speak`, and `debate <neighbor>`. Inside debate, legal actions are `choose tactic actually`, `choose tactic vibes`, `choose tactic lore`, and `talk to the hand`.

The user-authored behavior configuration is a single free-text field embedded inside a fixed prompt template. The fixed template supplies rules, legal actions, current state, local observation, and output format. The user field describes how this cog should behave.

The server validates the returned action. Invalid, impossible, malformed, or timed-out normal actions become `wait`. Invalid, impossible, malformed, or timed-out debate actions become `talk to the hand`.

## Cog Observation

A cog's observation includes:

- its own color, traits, goal, score, prompt field, status, debate state, and pressure meters
- visible nearby cog positions, colors, debate status, and speech bubbles
- nearby terrain
- recent local events involving or visible to the cog
- legal actions for the current tick

A cog's observation does not include other cogs':

- traits
- goals
- hidden scores
- pressure meters
- behavior prompts

## Human Visibility

The game should be watchable without selection UI. The main board should visibly communicate:

- cog color
- active debate pairings and revealed debate tactic choices
- debate status
- coarse pressure or status cues
- walls
- sand
- speech bubbles

Human viewers can inspect all cogs' traits and goals through the roster panel. There is no hover or selection inspection path. Roster visibility is spectator/debug visibility only. It does not imply cogs can observe that hidden metadata.

## Testing Notes

Focused tests should cover:

- color pressure meters convert cogs and reset after conversion
- debate initiation requires an adjacent available neighbor
- movement into occupied cog cells does not apply pressure by itself
- debate tactic choices resolve simultaneously
- `actually`, `vibes`, and `lore` resolve the expected matchup loop
- same-tactic debate choices apply no pressure and continue the debate
- `talk to the hand` ends debate and concedes pressure to the other participant
- two `talk to the hand` choices end debate without pressure
- color conversion during debate ends debate
- charisma pressures different colors and reinforces same colors
- walls block movement without blocking charisma, observation, or speech visibility
- sand slows movement without blocking interaction or visibility
- `insular`, `iconoclast`, `conformist`, `skeptic`, `charismatic`, `contrarian`, `provocateur`, `zealot`, `stubborn`, `forceful`, `pedant`, `hippie`, and `lorekeeper` modify only their intended rule paths
- spawned cogs enter random empty edge tiles and fail when no edge tile is available
- cogs cannot observe other cogs' hidden traits, goals, pressure meters, or prompts
- humans can inspect hidden metadata through roster UI
- invalid normal prompt actions fall back to `wait`
- invalid debate prompt actions fall back to `talk to the hand`
- speech is visible locally for the configured number of ticks and has no direct scoring or conversion effect

## Implementation Boundary

This spec defines rules, data contracts, and expected behavior. It does not require real LLM calls, production auth, hosted infrastructure, or final visual polish in the first playable. Stub and deterministic controllers can exercise all rules before provider-backed prompts are enabled.
