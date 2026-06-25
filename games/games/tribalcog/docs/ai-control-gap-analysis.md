# AI Coordination & Agent Control Surface: Gap Analysis

Date: 2026-01-28 (updated 2026-02-08)
Owner: Engineering / AI
Status: Active

## Current State

### Fully Implemented Control APIs (with FFI + Nim API)

All high-priority control APIs from the original gap analysis have been implemented
in `agent_control.nim` and exported via `ffi.nim`.

| Command | Nim API (`agent_control.nim`) | FFI Export (`ffi.nim`) | Status |
|---------|------------------------------|----------------------|--------|
| Attack-Move | `setAgentAttackMoveTarget`, `clearAgentAttackMoveTarget`, `getAgentAttackMoveTarget`, `isAgentAttackMoveActive` | `tribal_village_set_attack_move`, `tribal_village_clear_attack_move`, `tribal_village_get_attack_move_x/y`, `tribal_village_is_attack_move_active` | Done |
| Patrol | `setAgentPatrol`, `clearAgentPatrol`, `getAgentPatrolTarget`, `isAgentPatrolActive` | `tribal_village_set_patrol`, `tribal_village_clear_patrol`, `tribal_village_get_patrol_target_x/y`, `tribal_village_is_patrol_active` | Done |
| Stance | `setAgentStance`, `getAgentStance` | `tribal_village_set_stance`, `tribal_village_get_stance` | Done |
| Garrison | `garrisonAgentInBuilding`, `ungarrisonAllFromBuilding`, `getGarrisonCount` | `tribal_village_garrison`, `tribal_village_ungarrison`, `tribal_village_garrison_count` | Done |
| Production Queue | `queueUnitTraining`, `cancelLastQueuedUnit`, `getProductionQueueSize`, `getProductionQueueEntryProgress` | `tribal_village_queue_train`, `tribal_village_cancel_train`, `tribal_village_queue_size`, `tribal_village_queue_progress` | Done |
| Research | `researchBlacksmithUpgrade`, `researchUniversityTech`, `researchCastleTech`, `researchUnitUpgrade` | `tribal_village_research_blacksmith`, `tribal_village_research_university`, `tribal_village_research_castle`, `tribal_village_research_unit_upgrade` | Done |
| Research Query | `hasBlacksmithUpgrade`, `hasUniversityTechResearched`, `hasCastleTechResearched`, `hasUnitUpgradeResearched` | `tribal_village_has_blacksmith_upgrade`, `tribal_village_has_university_tech`, `tribal_village_has_castle_tech`, `tribal_village_has_unit_upgrade` | Done |
| Scout Mode | `setAgentScoutMode`, `isAgentScoutModeActive`, `getAgentScoutExploreRadius` | `tribal_village_set_scout_mode`, `tribal_village_is_scout_mode_active`, `tribal_village_get_scout_explore_radius` | Done |
| Rally Point | `setBuildingRallyPoint`, `clearBuildingRallyPoint`, `getBuildingRallyPoint` | `tribal_village_set_rally_point`, `tribal_village_clear_rally_point`, `tribal_village_get_rally_point_x/y` | Done |
| Stop | `stopAgent` | `tribal_village_stop` | Done |
| Hold Position | `setAgentHoldPosition`, `clearAgentHoldPosition`, `getAgentHoldPosition`, `isAgentHoldPositionActive` | `tribal_village_hold_position`, `tribal_village_clear_hold_position`, `tribal_village_get_hold_position_x/y`, `tribal_village_is_hold_position_active` | Done |
| Follow | `setAgentFollowTarget`, `clearAgentFollowTarget`, `getAgentFollowTargetId`, `isAgentFollowActive` | `tribal_village_follow_agent`, `tribal_village_clear_follow`, `tribal_village_get_follow_target`, `tribal_village_is_follow_active` | Done |
| Formation | `setControlGroupFormation`, `getControlGroupFormation`, `clearControlGroupFormation`, `setControlGroupFormationRotation`, `getControlGroupFormationRotation` | `tribal_village_set_formation`, `tribal_village_get_formation`, `tribal_village_clear_formation`, `tribal_village_set_formation_rotation`, `tribal_village_get_formation_rotation` | Done |
| Selection | `selectUnits`, `addToSelection`, `removeFromSelection`, `clearSelection`, `getSelectionCount`, `getSelectedAgentId` | `tribal_village_select_units`, `tribal_village_add_to_selection`, `tribal_village_remove_from_selection`, `tribal_village_clear_selection`, `tribal_village_get_selection_count`, `tribal_village_get_selected_agent_id` | Done |
| Control Groups | `createControlGroup`, `recallControlGroup`, `getControlGroupCount`, `getControlGroupAgentId` | `tribal_village_create_control_group`, `tribal_village_recall_control_group`, `tribal_village_get_control_group_count`, `tribal_village_get_control_group_agent_id` | Done |
| Command to Selection | `issueCommandToSelection` | `tribal_village_issue_command_to_selection` | Done |
| Market Trading | `initMarketPrices`, `getMarketPrice`, `setMarketPrice`, `marketBuyResource`, `marketSellResource`, etc. | `tribal_village_init_market_prices`, `tribal_village_get_market_price`, `tribal_village_market_buy`, `tribal_village_market_sell`, etc. | Done |
| Fog of War | `isRevealed`, `getRevealedTileCount`, `clearRevealedMap` | `tribal_village_is_tile_revealed`, `tribal_village_get_revealed_tile_count`, `tribal_village_clear_revealed_map` | Done |
| Threat Map | — | `tribal_village_has_known_threats`, `tribal_village_get_nearest_threat`, `tribal_village_get_threats_in_range`, `tribal_village_get_threat_at` | Done |
| Team Modifiers | — | `tribal_village_get/set_gather_rate_multiplier`, `tribal_village_get/set_build_cost_multiplier`, `tribal_village_get/set_unit_hp_bonus`, `tribal_village_get/set_unit_attack_bonus` | Done |
| Territory Scoring | — | `tribal_village_score_territory`, `tribal_village_get_territory_team_tiles`, etc. | Done |
| AI Difficulty | — | `tribal_village_get/set_difficulty_level`, `tribal_village_get/set_difficulty`, adaptive difficulty controls, threat response, coordination, targeting | Done |
| Error Handling | — | `tribal_village_has_error`, `tribal_village_get_error_code`, `tribal_village_get_error_message`, `tribal_village_clear_error` | Done |

### Existing Coordination System (`coordination.nim`)

| Request Type | Requestor | Responder | Mechanism |
|-------------|-----------|-----------|-----------|
| RequestProtection | Gatherer (flee) | Fighter (escort) | `fighterShouldEscort()` |
| RequestDefense | Fighter (threat) | Builder (walls/towers) | `builderShouldPrioritizeDefense()` |
| RequestSiegeBuild | Fighter (structures) | Builder (siege workshop) | `hasSiegeBuildRequest()` |

## Remaining Gaps

### Category 1: Missing Features (Lower Priority)

These features from the original analysis have not been implemented:

1. **Guard Command** - No ability to assign a military unit to guard a specific building or economic unit (distinct from the coordination-based escort).

2. **Waypoint Paths** - Patrol only supports 2 waypoints. No multi-waypoint patrol or custom movement paths.

3. **Economy Priority Override** - No API to force gatherers to prioritize specific resources (override the automatic task selection system).

4. **Aggressive Stance for Non-Fighters** - Gatherers/builders can only flee from threats. No option for them to fight back when cornered (though StanceAggressive exists, AI roles override it).
