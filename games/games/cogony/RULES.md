# Cogony Rules

Source of truth. Rule changes start here; code and tests follow.

---

## 1. Cogs

Cogs are digital cognitive entities — the agents of the game.

### Stats

| Stat               | Formula / Value          | Notes                    |
|--------------------|--------------------------|--------------------------|
| Max coherence      | `10 + 5 * core_d`        | 0 = disabled             |
| Initial coherence  | 10                       |                          |
| Max energy         | `100 + 25*gen_d`         |                          |
| Cargo cap          | `100 + 25*storage_d`     |                          |
| Creds              | 100 initial              | currency, kept across death, not lootable |
| Hearts             | 1 initial                | victory points, kept across death, not lootable |

### Gear

8 gear types. All combat stats start at 0 — gear is the only source.

| Subsystem  | Attack       | Defense      |
|------------|--------------|--------------|
| Core       | `core_a`     | `core_d`     |
| OS         | `os_a`       | `os_d`       |
| Generator  | `gen_a`      | `gen_d`      |
| Storage    | `storage_a`  | `storage_d`  |

Gear cost = `2^(4 + gear_held)`. First piece costs 16, second 32, etc.

### Coherence and regen

**Coherence regen**: every 10 ticks, `coherence += 1 + core_a`.

**Energy regen**: every 10 ticks, `energy += 1 + gen_a`.

**Disabled state**: at coherence = 0, `reboot` is set to max coherence
(`10 + 5 * core_d`) and counts down by 1 each tick. When `reboot`
reaches 0, the cog reboots: coherence fills to max, one random gear
is lost.

### Combat

Attack resolves all four subsystems at once:

```
damage = sum(max(0, attacker.Dmg[C] - target.Res[C]))
target.coherence -= damage

if target.coherence > 0:
    strike_back = sum(max(0, target.Dmg[C] - attacker.Res[C]))
    attacker.coherence -= strike_back
```

### Bump actions

| Target           | Default bump                | Disabled (coherence = 0)    |
|------------------|-----------------------------|-----------------------------|
| Extractor        | Attack                      | Loot: take elements         |
| Junction         | Attack                      | Align (requires team vibe)  |
| Cog              | Nothing                     | Loot: take elements + gear  |
| Hub              | Claim dividends + heal      | —                           |
| Gear station     | Buy gear: `2^(4+gear)` creds| —                           |
| Market station   | Sell elements for creds     | —                           |
| Heart station    | Buy 1 heart for 100 creds   | —                           |

### Vibes

Override default bump behavior:

| Vibe       | Icon | Effect                                       |
|------------|------|----------------------------------------------|
| `default`  | 😐   | Standard bump table above                    |
| `attack`   | ⚔️   | All bumps resolve as attack                  |
| `patch`    | 🩹   | Heal target 10*core_a coherence, costs 10 energy. Self-heals on tick. Auto-resets at max coherence or no energy. |
| `buy`      | ➕   | Bump hub: mint one stake (bonding curve)      |
| `sell`     | ➖   | Bump hub: burn one stake (refund from curve)  |
| `red`      | 🔴   | Bump disabled junction: align to cogs_red     |
| `blue`     | 🔵   | Bump disabled junction: align to cogs_blue    |
| `green`    | 🟢   | Bump disabled junction: align to cogs_green   |
| `yellow`   | 🟡   | Bump disabled junction: align to cogs_yellow  |

God mode (`--god-mode`) adds testing-only resource-transfer vibes:

| Vibe       | Icon | Effect                                |
|------------|------|---------------------------------------|
| `cred`     | 🪙   | Bump cog: transfer 10 creds to target |
| `heart`    | ❤️   | Bump cog: transfer 1 heart to target  |

## 2. Gear Stations

Compound layout places gear stations in corners:

| Corner     | Stations               |
|------------|------------------------|
| NW         | `core_a`, `core_d`     |
| NE         | `os_a`, `os_d`         |
| SW         | `gen_a`, `gen_d`       |
| SE         | `storage_a`, `storage_d`|
| Above hub  | Heart station          |
| Below hub  | Market station         |

## 3. Resources

* **Elements**: Carbon (C), Oxygen (O), Germanium (G), Silicon (S).
* **Cargo**: total elements carried, capped at `100 + 25*storage_d`.
* **Creds**: universal currency. Kept across death.
* **Hearts**: victory points. Kept across death.
  Per-step reward = `delta_hearts / max_steps`.

### Market

Bump market to sell all carried elements for creds. Dynamic pricing:
rarest element pays 4 creds per unit, most common pays 1. Prices
recalculate after each sale based on last 10 transactions.
10% tax: stays on the market station.

### Heart station

100 creds buys 1 heart.

## 4. Extractors

Stationary nodes. Attack to disable, then loot elements.

### Level system

| Stat              | Value                        |
|-------------------|------------------------------|
| Max coherence     | `10 + 5 * core_d`            |
| Resist (all 4)    | `level` each                 |
| Dmg (all 4)       | `max(0, level - 3)` each     |

Types: carbon, oxygen, germanium, silicon.

### Disable and reboot

At coherence = 0:
1. Death drop: `rand(1, 10*level)` elements of its type.
2. Reboot timer ticks. When `reboot >= 10*level`, restart.
3. On restart: level++, coherence fills, most-damaged subsystem
   gets +1 defense, random subsystem gets +1 offense.

## 5. Teams and Stakes

Teams: `cogs_red`, `cogs_blue`, `cogs_green`, `cogs_yellow`.
Each team has a hub in its compound.

### Stake-based economics

Agents invest in teams by purchasing **stakes** via a bonding curve.
Stakes entitle holders to a share of territory income (dividends).

**Visible stake economics** (per team):
- `{color}_total_stakes` (s) — total stakes minted for that team
- `{color}_stake_buy_price` — current next mint price, `k*(s+1)`
- `{color}_stake_sell_price` — current burn refund, `k*s`

Hubs display all three team-scoped stake economy resources. Stake buy stations
display only `{color}_stake_buy_price`; stake sell stations display only
`{color}_stake_sell_price`. Both station prices must also be visible in the
MettaScope details view. Generic bookkeeping names such as `stake_cost`,
`curve_reserve`, `revenue`, `total_stake`, `stake_buy_price`,
`stake_sell_price`, and `dividend_per_stake` must not appear in object
observations.

**Agent resources** (per team):
- `{color}_stake` — stakes held in this team
- `{color}_invested` — cumulative creds spent on stakes
- `{color}_dividends` — cumulative creds received (dividends + sell refunds)

### Bonding curve

Minting the n-th stake costs `k * n` (k=10). Total reserve at s stakes:

```
C = k * s*(s+1) / 2
```

Burns refund `k * s`. Mints and burns are exact inverses on C.

### Hub operations

| Action                  | Trigger                    | Effect                                        |
|-------------------------|----------------------------|-----------------------------------------------|
| **CLAIM** (default)     | Bump hub                   | Join team + restore coherence/energy          |
| **MINT** (buy station)  | Bump stake buy station     | Charge `k*(s+1)`, +1 stake                   |
| **BURN** (sell station) | Bump stake sell station    | Refund `k*s`, -1 stake                       |

### Territory income

Every 100 ticks: `revenue = 10 * junctions + 50 * observatories + 100 * datacenters`.

- **Champion** (agent with most stakes) receives 30% of revenue.
- Remaining 70% is distributed proportionally to all stake-holders.
- Dividends are paid directly to agents — no hub visit required.

## 6. Research Network

Three types of research nodes, scattered across the map. All have the
same subsystems as cogs and can be hacked. While rebooting, bump with
an aligner to align the node to your CAO.

Revenue per 100 ticks: `10 * junctions + 50 * observatories + 100 * datacenters`.

### Junctions

Scattered across the map. 10 creds/100 ticks revenue when aligned.

* **coherence > 0**: attack to break. Junction strikes back.
* **coherence = 0**: bump with aligner to align to your CAO.
* Alignment requires nearby hub or already-aligned node (radius 25).
* On reboot: +1 random subsystem, +1 random exploit, coherence restored.

### Observatories

Placed near the Heart Altar (2 total). 50 creds/100 ticks revenue when aligned.

Same stats and behavior as junctions.

### Datacenters

Placed between compounds (4 total, one per map edge midpoint).
100 creds/100 ticks revenue when aligned.

Same stats and behavior as junctions.
