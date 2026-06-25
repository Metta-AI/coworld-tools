# Cogisis Rules

Cogisis implements a Nemesis-style survival game as a custom cogame engine.
This file is the implementation contract. It paraphrases the modeled rules and
does not copy rulebook prose, card text, room-sheet text, or component art.

The official game includes many named cards and component-specific effects.
Cogisis models those as generic action, item, event, room, wound, and marker
mechanics so the simulator remains first-party and executable.

## Rule Inventory

### Setup And Hidden State

- R-001: A game supports one to five cogs, each controlling one crew character with a role, starting weapon ammo, action deck, hidden objective pair, and hibernatorium start. Tests: tests/test_engine.py::test_mission_builds_ship_with_core_nemesis_systems, tests/test_cli.py::test_cli_root_cogs_sets_player_count_when_autorun
- R-002: The ship is a graph of rooms connected by numbered corridors; only the hibernatorium starts explored, while other rooms reveal on first entry. Tests: tests/test_engine.py::test_mission_builds_ship_with_core_nemesis_systems, tests/test_rules_board.py::test_exploration_token_effects_apply_when_room_is_first_explored
- R-003: The ship has a destination, three hidden engine states, a time track, hibernation threshold, escape pods, and a self-destruct track. Tests: tests/test_engine.py::test_mission_builds_ship_with_core_nemesis_systems, tests/test_rules_character.py::test_self_destruct_cannot_start_after_hibernation_and_unlocks_pods_on_yellow_track
- R-004: Each character has two hidden objectives until the first encounter, when every unresolved character deterministically chooses one objective for reproducible policy runs. Tests: tests/test_engine.py::test_noisy_movement_places_noise_then_spawns_intruder_from_bag, tests/test_client.py::test_client_frame_separates_global_and_player_private_state
- R-005: Global state hides private objectives and action-card identities; player observations expose that player's private state. Tests: tests/test_client.py::test_client_frame_separates_global_and_player_private_state

### Round And Action Economy

- R-006: A player phase gives each active character one turn with up to two action slots, then the ship resolves the event phase. Tests: tests/test_engine.py::test_player_phase_allows_two_actions_per_character_before_event_phase, tests/test_web_server.py::test_web_server_accepts_authenticated_player_turn_actions
- R-007: Passing ends the current character's remaining action slots without advancing the whole round unless no active turns remain. Tests: tests/test_engine.py::test_player_phase_allows_two_actions_per_character_before_event_phase, tests/test_web_server.py::test_web_server_accepts_authenticated_player_turn_actions
- R-008: Policies replan between the two action slots so the second action can react to the first action's changed state. Tests: tests/test_engine.py::test_policy_player_phase_replans_between_actions
- R-009: Each character starts with a shuffled ten-card action deck and five-card hand; paid actions discard selected cards and active characters draw back to five after the event phase. Tests: tests/test_engine.py::test_paid_actions_discard_selected_action_cards, tests/test_engine.py::test_event_phase_refills_action_hand_to_five_cards
- R-010: Manual player clients must provide exact discard card ids for paid actions, while headless policy runs auto-discard. Tests: tests/test_engine.py::test_paid_actions_can_require_explicit_discards, tests/test_web_server.py::test_web_server_accepts_authenticated_player_turn_actions
- R-011: Free metadata actions, including player naming, do not consume paid action cards or turn slots. Tests: tests/test_engine.py::test_character_can_set_public_display_name, tests/test_web_server.py::test_web_server_accepts_authenticated_player_turn_actions

### Movement, Exploration, Doors, And Noise

- R-012: Movement between adjacent rooms is blocked if the connecting door is closed and is impossible when rooms are not connected. Tests: tests/test_rules_board.py::test_closed_doors_block_crew_movement_and_danger_intruders_destroy_them, tests/test_web_server.py::test_web_server_accepts_authenticated_player_turn_actions
- R-013: Destroyed doors stay destroyed and cannot be closed again. Tests: tests/test_rules_board.py::test_destroyed_doors_cannot_be_closed_again
- R-014: Danger movement makes neighboring intruders move into the character's room unless a closed door blocks them, in which case the door is destroyed and the intruder stays put. Tests: tests/test_rules_board.py::test_closed_doors_block_crew_movement_and_danger_intruders_destroy_them
- R-015: First entry into an unexplored room reveals it and resolves its exploration effect. Tests: tests/test_rules_board.py::test_exploration_token_effects_apply_when_room_is_first_explored, tests/test_engine.py::test_noisy_movement_places_noise_then_spawns_intruder_from_bag
- R-016: Exploration effects can place fire, place malfunction, add slime, resolve danger, or resolve silence. Tests: tests/test_rules_board.py::test_exploration_token_effects_apply_when_room_is_first_explored
- R-017: Moving into an empty room resolves noise; silence places no marker, danger moves intruders or marks every corridor, and numbered results place a corridor marker. Tests: tests/test_engine.py::test_noisy_movement_places_noise_then_spawns_intruder_from_bag, tests/test_rules_board.py::test_slime_turns_silence_noise_roll_into_danger
- R-018: A slimed character treats silence noise results as danger. Tests: tests/test_rules_board.py::test_slime_turns_silence_noise_roll_into_danger
- R-019: If a numbered noise marker already exists on the target corridor, markers for that room are cleared and an encounter is resolved from the intruder bag. Tests: tests/test_engine.py::test_noisy_movement_places_noise_then_spawns_intruder_from_bag

### Markers And Ship Hazards

- R-020: Fire markers cannot duplicate in a room; exhausting the fire marker pool ends the game. Tests: tests/test_rules_board.py::test_fire_marker_pool_ends_game_when_exhausted_without_duplicate_consumption
- R-021: During event fire damage, characters in burning rooms take a light wound and intruders in burning rooms take one damage. Tests: tests/test_rules_board.py::test_event_fire_damage_wounds_characters_and_burns_intruders
- R-022: Malfunction markers cannot duplicate in a room; exhausting the malfunction marker pool ends the game. Tests: tests/test_rules_board.py::test_malfunction_marker_pool_ends_game_when_exhausted_without_duplicate_consumption
- R-023: Malfunctioned rooms disable room actions, but searching still works and repair can clear the malfunction. Tests: tests/test_rules_board.py::test_malfunction_blocks_room_actions_but_not_search_and_repair_clears_marker

### Encounters, Combat, Wounds, And Contamination

- R-024: Encounters spawn an intruder from the bag; blank tokens add an adult token back to the bag, and larvae add contamination. Tests: tests/test_engine.py::test_noisy_movement_places_noise_then_spawns_intruder_from_bag
- R-025: When a character is in combat, out-of-combat actions are blocked; moving away is treated as an escape and triggers intruder attacks. Tests: tests/test_rules_board.py::test_out_of_combat_actions_are_blocked_in_combat_and_escape_move_triggers_attack
- R-026: Shooting consumes ammo, melee wounds the character, attacks damage intruders, and lethal damage records intruder kills. Tests: tests/test_engine.py::test_repair_signal_hibernate_and_victory_check, tests/test_rules_board.py::test_event_fire_damage_wounds_characters_and_burns_intruders
- R-027: Intruders attack by kind: larvae add contamination, creepers cause light wounds, adults cause serious wounds, and larger intruders cause serious wounds plus contamination. Tests: tests/test_engine.py::test_intruder_attack_adds_wounds_and_death_unlocks_escape_pods, tests/test_rules_character.py::test_light_wounds_convert_to_serious_and_third_serious_wound_kills
- R-028: Three light wounds convert into one serious wound; three serious wounds kill the character. Tests: tests/test_rules_character.py::test_light_wounds_convert_to_serious_and_third_serious_wound_kills
- R-029: The first character death unlocks all escape pods. Tests: tests/test_engine.py::test_intruder_attack_adds_wounds_and_death_unlocks_escape_pods, tests/test_rules_character.py::test_light_wounds_convert_to_serious_and_third_serious_wound_kills
- R-030: Scanning contamination removes clean cards; infected cards attach a larva, and scanning infected cards while already carrying a larva kills the character and spawns a creeper. Tests: tests/test_rules_character.py::test_contamination_scan_discards_clean_cards_and_infected_card_attaches_larva, tests/test_rules_character.py::test_scanning_infected_contamination_with_larva_kills_character_and_spawns_creeper

### Objects, Items, Crafting, And Room Actions

- R-031: Characters can carry at most two heavy objects and may drop carried objects. Tests: tests/test_rules_character.py::test_heavy_objects_are_limited_to_two_and_can_be_dropped
- R-032: Searching an empty, intruder-free room decrements its search counter and gives the character an item; empty rooms report no item. Tests: tests/test_engine.py::test_paid_actions_discard_selected_action_cards, tests/test_rules_board.py::test_malfunction_blocks_room_actions_but_not_search_and_repair_clears_marker
- R-033: Crafting consumes required component items and creates the crafted item. Tests: tests/test_rules_character.py::test_crafting_consumes_components_and_creates_crafted_item
- R-034: Comms sends a signal, cockpit sets coordinates, laboratory discovers a weakness, nest destroys eggs, and these room actions can satisfy objectives. Tests: tests/test_engine.py::test_repair_signal_hibernate_and_victory_check
- R-035: Surgery removes larva and contamination cards, then gives the character a light wound. Tests: tests/test_rules_character.py::test_surgery_removes_larva_and_contamination_then_adds_light_wound
- R-036: Armory reloads ammo without exceeding weapon capacity. Tests: tests/test_rules_character.py::test_armory_room_reload_is_capped_by_ammo_capacity
- R-037: Engine status can be checked without changing the engine, and damaged engines can be repaired from their engine room. Tests: tests/test_rules_character.py::test_engine_status_can_be_checked_without_repairing_engine, tests/test_engine.py::test_repair_signal_hibernate_and_victory_check

### Escape, Events, And Endgame

- R-038: Hibernation requires the hibernatorium, no intruder in the room, and the hibernation threshold to be open. Tests: tests/test_engine.py::test_repair_signal_hibernate_and_victory_check
- R-039: Escape pods start locked, require the character to be in the pod room without intruders, and launch the escaping character when unlocked. Tests: tests/test_engine.py::test_intruder_attack_adds_wounds_and_death_unlocks_escape_pods
- R-040: Self-destruct cannot start after any character has hibernated; once active, it ticks during event phases, unlocks pods on the yellow track, and destroys the ship at zero. Tests: tests/test_rules_character.py::test_self_destruct_cannot_start_after_hibernation_and_unlocks_pods_on_yellow_track
- R-041: The event phase advances time, resolves fire, resolves intruder attacks, ticks self-destruct, checks end conditions, and returns to player phase when the game continues. Tests: tests/test_client.py::test_build_client_frames_records_global_map_and_events, tests/test_rules_board.py::test_event_fire_damage_wounds_characters_and_burns_intruders
- R-042: The game ends on hyperjump, self-destruct, all characters inactive, marker-pool catastrophe, or configured max steps. Tests: tests/test_engine.py::test_damaged_engines_make_hibernated_character_lose, tests/test_rules_board.py::test_fire_marker_pool_ends_game_when_exhausted_without_duplicate_consumption, tests/test_rules_board.py::test_malfunction_marker_pool_ends_game_when_exhausted_without_duplicate_consumption
- R-043: Winning requires survival plus the chosen objective; hibernating survivors also require the ship to survive with fewer than two damaged engines. Tests: tests/test_engine.py::test_repair_signal_hibernate_and_victory_check, tests/test_engine.py::test_damaged_engines_make_hibernated_character_lose

### Interfaces And Running

- R-044: Running without `--autorun` starts paused clients or exits silently for headless renders; the simulator does not advance until admin/player action or explicit autorun. Tests: tests/test_cli.py::test_cli_defaults_to_gui_without_autorun, tests/test_cli.py::test_cli_without_autorun_does_not_play_or_print
- R-045: The local web server exposes admin, global, and authenticated player clients, with policy-client URLs removed. Tests: tests/test_web_server.py::test_web_server_exposes_paused_clients_and_manual_step
- R-046: Player clients expose only valid turn actions, support follow-up choices, submit paid discards, and advance the turn token. Tests: tests/test_client.py::test_client_frame_includes_structured_turn_action_options, tests/test_web_server.py::test_web_server_accepts_authenticated_player_turn_actions
- R-047: The global client shows the ship layout, connection indicators, God Mode for global hidden information, noise markers in corridors, and opens player clients in separate windows. Tests: tests/test_client.py::test_render_client_html_embeds_self_contained_surface, tests/test_client.py::test_render_client_html_draws_noise_markers_in_corridors
- R-048: Player client pages do not expose God Mode and preserve focused name input across live refreshes. Tests: tests/test_client.py::test_render_player_client_does_not_include_god_mode, tests/test_client.py::test_render_client_html_preserves_focused_name_input_across_live_refresh
