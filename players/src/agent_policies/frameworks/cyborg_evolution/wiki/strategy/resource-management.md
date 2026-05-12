# Resource Management

Universal patterns for acquiring, allocating, and spending resources.

## The Resource Cycle

Every strategy game has a resource loop:

```
Acquire → Store → Convert → Deploy → Acquire...
```

- **Acquire**: Mine, harvest, collect, trade, generate income
- **Store**: Carry in inventory, bank at base, hold in hand
- **Convert**: Craft, build, research, upgrade
- **Deploy**: Spend resources to achieve objectives (capture, attack, defend)

## Prioritization Framework

When multiple resources or tasks compete for attention:

### 1. Bottleneck-First

Identify the **binding constraint** — the one resource that limits everything else.
Focus acquisition on the bottleneck, not the easiest resource.

```
Example: You need 10 wood + 10 stone + 1 diamond to build.
You have 50 wood, 40 stone, 0 diamonds.
→ Mine diamonds, NOT more wood/stone.
```

### 2. Opportunity Cost

Every tick spent on one task is a tick not spent on another. Compare:
- How many ticks does this task take?
- What's the expected payoff?
- What am I giving up by doing this instead of the alternative?

### 3. Time-Value of Resources

Resources acquired early are worth more than resources acquired late because you can
use them longer. This means:

- **Early income > late income** — set up production first
- **Spend early windfalls immediately** — don't save starting bonuses
- **Stockpiling is usually wrong** — resources in inventory aren't generating value

## Deposit Timing

In games with a base/bank mechanic, when to deposit:

- **Deposit when full** — obvious but correct; minimize round trips
- **Deposit when threatened** — better to bank partial cargo than lose it all
- **Deposit on the way** — if your path passes the base anyway, deposit even if not full
- **Don't deposit single items** — the travel time exceeds the value of banking one unit

## Resource Denial

In competitive games, denying opponents resources is as valuable as acquiring them:

- **Contest shared resources** — if both players need gold, mining gold hurts them too
- **Control chokepoints** — hold the positions that gate access to resources
- **Timing attacks** — attack when the opponent is carrying resources (maximum disruption)

## When to Stop Gathering

The brain should recognize when gathering more is wasteful:

- All conversion requirements are met
- Storage is full or near-full
- The game is entering a phase where resources matter less
- You're ahead and should be deploying, not stockpiling
