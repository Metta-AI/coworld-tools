# Design contract

> Fill in the blanks before writing code. This is the source of truth that
> `cg.game.new-game` and `cg.game.build-game` will work from.

## 1. One-sentence pitch

_TODO(cogame):_ a sentence a human can read to understand what the game is.

## 2. Roles

- _TODO(cogame):_ list each role, the resources they start with, and what
  differentiates them from other roles. If there's only one role, say so
  explicitly.

## 3. Primary feedback loop

- Action agents take: _TODO_
- Intermediate state it produces: _TODO_
- Reward it ultimately yields: _TODO_

## 4. Win / loss conditions

- _TODO(cogame):_ describe termination conditions. For reward-maximization
  games without a hard win/loss, say so.

## 5. Map and spawn layout

- Dimensions: _TODO_
- Number of agents: _TODO_
- Key objects and their approximate positions: _TODO_

## 6. Key resources / inventory

| resource | initial | cap | comes from | consumed by |
|----------|---------|-----|------------|-------------|
| _TODO_   | _TODO_  | _TODO_ | _TODO_ | _TODO_ |

## 7. Actions

- _TODO(cogame):_ enumerate every action and its effect. Include both base
  actions (`move`, `noop`, etc.) and any action extensions / handlers.

## 8. Reward structure

- _TODO(cogame):_ which inventory items contribute rewards, their weights,
  and whether they're per-tick or on-event.

## 9. Variants

- _TODO(cogame):_ list public variants and what each one changes. Separate
  into difficulty, layout, mechanics, timing, etc. Note which variants
  compose (dependencies) and which conflict (mutually exclusive).

## 10. Evaluation & leaderboard targets

- _TODO(cogame):_ what does a "good" policy look like? If there's a baseline
  policy or scrimmage gate, describe it here.
