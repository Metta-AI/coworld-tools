# Victory Conditions

Date: 2026-02-09
Owner: Docs / Game Systems
Status: Reference

## Overview

Tribal Village supports multiple victory conditions that determine how a game can end. The active victory condition is set via `EnvironmentConfig.victoryCondition` and checked each step in `src/step.nim`.

Key implementation files:
- `src/types.nim` - VictoryCondition enum, VictoryState type
- `src/constants.nim` - Countdown durations and radii
- `src/step.nim` - Victory checking logic (lines 783-980)

## Victory Condition Enum

```nim
VictoryCondition* = enum
  VictoryNone         ## No victory condition (time limit only)
  VictoryConquest     ## Win when all enemy units and buildings destroyed
  VictoryWonder       ## Build Wonder, survive countdown
  VictoryRelic        ## Hold all relics in Monasteries for countdown
  VictoryRegicide     ## Win by killing all enemy kings
  VictoryKingOfTheHill ## Control the hill for consecutive steps
  VictoryAll          ## Any of the above can trigger victory
```

## Per-Team Victory Tracking

Each team has a `VictoryState` object that tracks their progress toward victory:

```nim
VictoryState* = object
  wonderBuiltStep*: int          ## Step when Wonder was built (-1 = no wonder)
  relicHoldStartStep*: int       ## Step when team started holding all relics (-1 = not holding)
  kingAgentId*: int              ## Agent ID of this team's king (-1 = no king)
  hillControlStartStep*: int     ## Step when team started controlling the hill (-1 = not controlling)
```

## Victory Conditions in Detail

### Conquest (VictoryConquest)

**Win condition:** Be the last team with any units or buildings remaining.

**Mechanics:**
- Checked by `checkConquestVictory()` in step.nim:801-813
- Scans all agents and team-owned buildings each step
- If only one team has living agents or structures, that team wins
- Buildings checked include all `TeamOwnedKinds` (TownCenter, Castle, etc.)

**Reward:** Winning team receives `VictoryReward` (10.0) added to each agent's reward.

### Wonder (VictoryWonder)

**Win condition:** Build a Wonder and keep it standing for **600 steps** (countdown).

**Constants:**
- `WonderVictoryCountdown* = 600` (src/constants.nim:320)

**Mechanics:**
- Checked by `checkWonderVictory()` in step.nim:815-832
- Countdown starts when Wonder reaches full HP (construction complete)
- Tracked via `victoryStates[teamId].wonderBuiltStep`
- `updateWonderTracking()` monitors Wonder completion each step
- If Wonder is destroyed before countdown finishes, timer resets to -1
- Wonder victory does NOT require holding the Wonder for 600 consecutive steps - just having it exist for 600 steps total since completion

**Key detail:** The countdown starts when the Wonder is **completed** (hp >= maxHp), not when placement begins. Each step, `wonder.wonderVictoryCountdown` decrements; when it reaches 0, that team wins.

### Relic (VictoryRelic)

**Win condition:** Garrison all relics in Monasteries and hold them for **200 steps**.

**Constants:**
- `RelicVictoryCountdown* = 200` (src/constants.nim:321)
- `TotalRelicsOnMap* = MapRoomObjectsRelics = 18` (src/types.nim:1022, 44)

**Mechanics:**
- Checked by `checkRelicVictory()` in step.nim:834-858
- Monks can pick up Relics scattered on the map
- Monks deposit Relics into Monasteries via the `use` action
- `monastery.garrisonedRelics` tracks count per Monastery
- A team must garrison ALL relics (18 total) to start the countdown
- If relics are lost (Monastery destroyed), timer resets

**Relic collection flow:**
1. Monk moves adjacent to Relic
2. Monk uses `use` action to pick up Relic (stored in `agent.inventoryRelic`)
3. Monk moves to friendly Monastery
4. Monk uses `use` action to deposit Relic

**Bonus:** Garrisoned Relics generate gold for the team every `MonasteryRelicGoldInterval` (20) steps, producing `MonasteryRelicGoldAmount` (1) gold per relic.

**On Monastery destruction:** When a Monastery with garrisoned Relics is destroyed, Relics are dropped on nearby empty tiles (src/combat.nim:270-284).

### Regicide (VictoryRegicide)

**Win condition:** Kill all enemy Kings while your King survives.

**Mechanics:**
- Checked by `checkRegicideVictory()` in step.nim:860-880
- Each team spawns a King unit (UnitKing class) at game start
- King's agent ID stored in `victoryStates[teamId].kingAgentId`
- Requires at least 2 teams with Kings to be active
- Win when only one team's King is alive

**King spawn:** In Regicide mode, the first agent spawned per team (index 0) is converted to a King unit (src/spawn.nim:1228-1231).

### King of the Hill (VictoryKingOfTheHill)

**Win condition:** Control the central ControlPoint for **300 consecutive steps**.

**Constants:**
- `HillVictoryCountdown* = 300` (src/constants.nim:324)
- `HillControlRadius* = 5` (src/constants.nim:323)

**Mechanics:**
- Checked by `checkKingOfTheHillVictory()` in step.nim:882-925
- A ControlPoint structure is placed on the map in this mode
- Control is determined by having the **most living units** within `HillControlRadius` (5 tiles) of the ControlPoint
- Ties = contested, no one controls, all timers reset
- If a team gains unique control, their timer starts/continues
- If a different team takes control, the previous controller's timer resets
- Timer must reach 300 consecutive steps of uncontested control

**Contest rules:**
- Having units present but tied with another team = no control
- Having zero units in range = no control
- Multiple ControlPoints: Each is checked independently

### Combined Mode (VictoryAll)

**Win condition:** Any of the above conditions can trigger victory.

**Mechanics:**
- All victory conditions are checked each step in priority order:
  1. Conquest (checked first)
  2. Wonder
  3. Relic
  4. Regicide
  5. King of the Hill
- First condition met triggers victory

## Configuration

Victory condition is set in `EnvironmentConfig`:

```nim
EnvironmentConfig* = object
  victoryCondition*: VictoryCondition  ## Which victory conditions are active
  # ... other fields
```

Default is `VictoryNone` (time limit only).

## Episode End

When a victory condition is met:
1. `env.victoryWinner` is set to the winning team ID
2. Losing team agents are terminated
3. Winning team agents are truncated and receive `VictoryReward` (10.0)
4. Episode ends

If no victory condition is met:
- Episode ends at `maxSteps` (default 3000)
- Territory scoring and altar rewards applied

## State Tracking Summary

| Condition | Tracking Field | Start Value | Trigger |
|-----------|---------------|-------------|---------|
| Wonder | `wonderBuiltStep` | -1 | Set to currentStep when Wonder reaches full HP |
| Relic | `relicHoldStartStep` | -1 | Set when team holds all 18 relics in Monasteries |
| Regicide | `kingAgentId` | -1 | Set at spawn for first agent per team |
| King of Hill | `hillControlStartStep` | -1 | Set when team has unique unit majority in radius |

## Countdown Durations Quick Reference

| Condition | Countdown | Constant |
|-----------|-----------|----------|
| Wonder | 600 steps | `WonderVictoryCountdown` |
| Relic | 200 steps | `RelicVictoryCountdown` |
| King of the Hill | 300 steps | `HillVictoryCountdown` |
| Hill Control Radius | 5 tiles | `HillControlRadius` |
| Victory Reward | 10.0 | `VictoryReward` |

## See Also

- [Game Logic Overview](game_logic.md) - Core game loop and mechanics
- [Combat](combat.md) - Attack patterns and damage
- [Economy and Respawning](economy_respawn.md) - Resource and population systems
