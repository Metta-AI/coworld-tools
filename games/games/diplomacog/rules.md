# Diplomacy - Rules

## Core Loop
- Generate `power_cell` at `reactor_station`.
- Convert `power_cell -> intel` at `comms_station`.
- Convert `intel -> influence` at `diplomacy_station`.
- During `Fall Orders`, move onto frontier `supply_center` tiles to capture them for your country.
- Submit `influence` or `intel` at country hubs to fill diplomacy/trade queues.
- Respond to telegraphed incidents before they escalate.

## Campaign Calendar
- The game advances through:
  - `Spring Orders`
  - `Spring Retreats`
  - `Fall Orders`
  - `Fall Retreats`
  - `Winter Adjustments`
- `Fall Orders` opens a `capture_window` on supply centers.
- `Winter Adjustments` award stability based on held supply centers.

## Countries
- Choose exactly one country role at a country station (`country_a/b/c_station`).
- Country hubs (`country_a/b/c_hub`) hold `stability`, `crisis`, and queue resources.
- Country hubs also count as home supply centers.
- Role matters:
  - Home-country diplomacy/trade gives immediate stability bonuses.
  - Foreign diplomacy creates cross-country treaty pressure.
  - Rival-country sabotage is stronger than generic sabotage.
  - Home-country agents can spend sabotage kits on counter-ops to reduce crisis.

## Event System
- Each country has periodic `*_crisis_wave` events.
- Queue processors resolve pressure over time:
  - `*_process_diplomacy_queue`
  - `*_process_trade_queue`
- Incident director loop (clips-style pressure queue):
  - `*_incident_telegraph` adds pending incidents and response windows.
  - `*_incident_tickdown` burns down windows over time.
  - `*_incident_escalate` converts unresolved incidents into extra crisis/queue pressure.

## Adversarial Actions
- Craft `sabotage_kit` at `sabotage_station` by spending `intel`.
- Use sabotage kits on hubs to increase crises and reduce stability.

## Scoring Signals
- Positive: treaties signed, queue submissions, global stability.
- Positive: frontier supply centers captured in fall and held through winter.
- Negative: global crisis pressure and queue backlog.
- Positive bonuses for cross-treaties, incident responses, and counter-ops.
- Global observation keys expose:
  - `global.win_score`
  - `global.victory_margin` (win score vs victory threshold)
  - `global.defeat_margin` (pressure vs defeat threshold)
  - `global.campaign_year`
  - `global.phase_orders` / `global.phase_retreat` / `global.phase_adjustment`
  - `global.mission_victory` / `global.mission_defeat` (final-step outcome checks)
