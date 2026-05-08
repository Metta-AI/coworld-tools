"""Eurydice behavioral accumulation and inference pipeline.

Implements the post_belief_update hook that runs every tick to:
1. Feed raw observations into per-player accumulators
2. Derive behavioral flags from accumulated patterns
3. Run hard and soft inference rules to populate PlayerKnowledge
"""

from __future__ import annotations

import math
from collections.abc import Set

from orpheus.belief_state import BeliefState
from orpheus.perception._common import PLAYER_COLORS

from .accumulators import GlobalAccumulators, PlayerAccumulator
from .ext_keys import (
    EURYDICE_ACCUMULATORS,
    PLAYER_KNOWLEDGE,
)
from .knowledge import PlayerKnowledge
from .types import (
    PlayerID,
    Role,
    RoleSource,
    Team,
    TeamSource,
    TrustLevel,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def eurydice_post_belief_update(belief_state: BeliefState) -> None:
    """Post-belief-update hook. Runs every tick after Orpheus integrates perception.

    Registered at HookPoint.POST_BELIEF_UPDATE. Mutates belief_state.extra
    with accumulated behavioral data and derived inferences.
    """
    # Initialize on first tick (or after lobby reset)
    if EURYDICE_ACCUMULATORS not in belief_state.extra:
        initialize_eurydice_state(belief_state)

    accumulators: GlobalAccumulators = belief_state.extra[EURYDICE_ACCUMULATORS]
    knowledge: dict[PlayerID, PlayerKnowledge] = belief_state.extra[PLAYER_KNOWLEDGE]

    # Detect round transitions
    _check_round_transition(accumulators, belief_state)

    # 1. Feed raw observations into accumulators
    update_position_tracker(accumulators, knowledge, belief_state)
    update_minimap_tracker(accumulators, knowledge, belief_state)
    update_whisper_tracker(accumulators, belief_state)
    update_exchange_tracker(accumulators, knowledge, belief_state)
    update_chat_tracker(accumulators, knowledge, belief_state)
    update_leadership_tracker(accumulators, belief_state)

    # 2. Derive behavioral flags from accumulators
    for player_id, acc in accumulators.player_accumulators.items():
        if player_id in knowledge:
            knowledge[player_id].behavioral_flags = derive_behavioral_flags(
                acc, knowledge, accumulators, belief_state
            )

    # 3. Run inference rules
    run_hard_inferences(knowledge, belief_state)
    run_soft_inferences(knowledge, belief_state)


def initialize_eurydice_state(belief_state: BeliefState) -> None:
    """Initialize Eurydice's extended state in belief_state.extra.

    Called once when the hook first fires (game start or lobby reset).
    """
    belief_state.extra[EURYDICE_ACCUMULATORS] = GlobalAccumulators()
    belief_state.extra[PLAYER_KNOWLEDGE] = {}
    # Track previous chat history length for incremental processing
    belief_state.extra["_eurydice_prev_chat_len"] = 0
    # Track previous whisper occupants for entry detection
    belief_state.extra["_eurydice_prev_whisper_occupants"] = []


# ---------------------------------------------------------------------------
# Helper: player index <-> PlayerID mapping
# ---------------------------------------------------------------------------


def player_index_to_id(index: int, belief_state: BeliefState) -> PlayerID | None:
    """Convert Orpheus integer player index to Eurydice PlayerID (color, shape).

    Returns None if the player info isn't available.
    """
    player_info = belief_state.players.get(index)
    if player_info is not None and player_info.position is not None:
        # We have position data; derive color from index
        color = PLAYER_COLORS[index % 8]
        shape = index % 12
        return (color, shape)
    # Fallback: derive from index alone (always available)
    color = PLAYER_COLORS[index % 8]
    shape = index % 12
    return (color, shape)


def minimap_sighting_to_player_id(sighting, belief_state: BeliefState) -> PlayerID | None:
    """Map a color-only minimap sighting to Eurydice's best PlayerID guess.

    Minimap dots carry color but not shape. We pick the first player index with
    that color, skipping our own index when known. If the game has more than
    eight players, this naturally maps repeated colors to the first non-self
    matching index.
    """
    color = getattr(sighting, "color", None)
    if color not in PLAYER_COLORS:
        return None

    matching_indices = _matching_indices_for_color(color, belief_state)
    self_index = _known_self_index(belief_state)
    if self_index is not None:
        matching_indices = [index for index in matching_indices if index != self_index]
    elif color == belief_state.my_color:
        # With no self index/shape, a same-color dot cannot be safely separated
        # from our own marker unless another same-color slot exists.
        if len(matching_indices) <= 1:
            return None
        matching_indices = matching_indices[1:]

    if matching_indices:
        return player_index_to_id(matching_indices[0], belief_state)

    if color == belief_state.my_color:
        return None
    return (color, 0)


def _matching_indices_for_color(color: int, belief_state: BeliefState) -> list[int]:
    player_count = belief_state.player_count
    if player_count is None:
        known_indices = list(getattr(belief_state, "players", {}).keys())
        player_count = max(known_indices) + 1 if known_indices else len(PLAYER_COLORS)
        player_count = max(player_count, len(PLAYER_COLORS))
    return [
        index
        for index in range(max(0, player_count))
        if PLAYER_COLORS[index % len(PLAYER_COLORS)] == color
    ]


def _known_self_index(belief_state: BeliefState) -> int | None:
    if belief_state.my_index is not None:
        return belief_state.my_index
    if belief_state.my_color is None or belief_state.my_shape is None:
        return None

    my_shape = int(getattr(belief_state.my_shape, "value", belief_state.my_shape))
    for index in _matching_indices_for_color(belief_state.my_color, belief_state):
        if index % 12 == my_shape:
            return index
    return None


def _ensure_knowledge(
    knowledge: dict[PlayerID, PlayerKnowledge],
    player_id: PlayerID,
) -> PlayerKnowledge:
    """Get or create a PlayerKnowledge record."""
    if player_id not in knowledge:
        knowledge[player_id] = PlayerKnowledge.create(player_id)
    return knowledge[player_id]


def _ensure_accumulator(
    accumulators: GlobalAccumulators,
    player_id: PlayerID,
) -> PlayerAccumulator:
    """Get or create a PlayerAccumulator record."""
    if player_id not in accumulators.player_accumulators:
        accumulators.player_accumulators[player_id] = PlayerAccumulator(
            player_id=player_id
        )
    return accumulators.player_accumulators[player_id]


# ---------------------------------------------------------------------------
# Round transition detection
# ---------------------------------------------------------------------------


def _check_round_transition(
    accumulators: GlobalAccumulators,
    belief_state: BeliefState,
) -> None:
    """Detect round changes and reset per-round accumulators."""
    current_round = belief_state.round or 0
    if current_round > accumulators.current_round and accumulators.current_round > 0:
        # Round changed -- reset per-round fields
        handle_round_transition(accumulators, belief_state)
    if current_round > 0 and accumulators.current_round == 0:
        # First round detected
        accumulators.current_round = current_round
        accumulators.round_start_tick = belief_state.tick


def handle_round_transition(
    accumulators: GlobalAccumulators,
    belief_state: BeliefState,
) -> None:
    """Reset per-round counters while preserving cross-round evidence."""
    for acc in accumulators.player_accumulators.values():
        acc.reset_for_new_round()
    accumulators.current_round = belief_state.round or 0
    accumulators.round_start_tick = belief_state.tick
    accumulators.our_probe_cycles_this_round = 0


# ---------------------------------------------------------------------------
# Tracker: Position
# ---------------------------------------------------------------------------


def update_position_tracker(
    accumulators: GlobalAccumulators,
    knowledge: dict[PlayerID, PlayerKnowledge],
    belief_state: BeliefState,
) -> None:
    """Track player positions from belief_state.players.

    PlayerInfo.position is (x, y, tick) -- a player is "visible this tick"
    if position[2] == belief_state.tick.
    """
    current_tick = belief_state.tick

    for index, player_info in belief_state.players.items():
        player_id = player_index_to_id(index, belief_state)
        if player_id is None:
            continue

        acc = _ensure_accumulator(accumulators, player_id)
        _ensure_knowledge(knowledge, player_id)

        if player_info.position is None:
            # Not visible -- mark if not already marked
            if acc.not_visible_since is None:
                acc.not_visible_since = current_tick
            continue

        pos_x, pos_y, pos_tick = player_info.position

        if pos_tick != current_tick:
            # Position is stale (from a previous tick)
            if acc.not_visible_since is None:
                acc.not_visible_since = current_tick
            continue

        _record_position_observation(
            accumulators,
            knowledge,
            player_id,
            (pos_x, pos_y),
            current_tick,
        )

        # Approach detection: did this player move within 25px of another?
        for other_index, other_info in belief_state.players.items():
            if other_index == index:
                continue
            if other_info.position is None:
                continue
            other_x, other_y, other_tick = other_info.position
            if other_tick != current_tick:
                continue
            dist_to_other = math.sqrt(
                (pos_x - other_x) ** 2 + (pos_y - other_y) ** 2
            )
            if dist_to_other < 25.0:
                other_pid = player_index_to_id(other_index, belief_state)
                if other_pid is not None:
                    acc.distinct_players_approached.add(other_pid)


def update_minimap_tracker(
    accumulators: GlobalAccumulators,
    knowledge: dict[PlayerID, PlayerKnowledge],
    belief_state: BeliefState,
) -> None:
    """Track current-tick color-only minimap sightings as last-known positions."""
    current_tick = belief_state.tick
    seen_this_tick: set[PlayerID] = set()

    for sighting in getattr(belief_state, "minimap_sightings", []):
        if getattr(sighting, "tick", None) != current_tick:
            continue

        player_id = minimap_sighting_to_player_id(sighting, belief_state)
        if player_id is None or player_id in seen_this_tick:
            continue

        seen_this_tick.add(player_id)
        _record_position_observation(
            accumulators,
            knowledge,
            player_id,
            sighting.position,
            current_tick,
        )


def _record_position_observation(
    accumulators: GlobalAccumulators,
    knowledge: dict[PlayerID, PlayerKnowledge],
    player_id: PlayerID,
    position: tuple[int, int],
    current_tick: int,
) -> PlayerAccumulator:
    """Record one direct or minimap position observation for a player."""
    acc = _ensure_accumulator(accumulators, player_id)
    pk = _ensure_knowledge(knowledge, player_id)

    if acc.position_history and acc.position_history[-1][0] == current_tick:
        # A direct viewport/speech-bubble observation was already recorded this
        # tick. Keep the first observation to avoid double-counting movement.
        acc.not_visible_since = None
        return acc

    pos_x, pos_y = int(position[0]), int(position[1])
    acc.not_visible_since = None
    acc.visible_ticks_this_round += 1
    acc.position_history.append((current_tick, pos_x, pos_y))
    pk.last_seen_position = (pos_x, pos_y)

    if len(acc.position_history) >= 2:
        _, prev_x, prev_y = acc.position_history[-2]
        dx = pos_x - prev_x
        dy = pos_y - prev_y
        distance = math.sqrt(dx * dx + dy * dy)
        acc.total_distance_this_round += distance

        # Stationary detection: <2px movement while observed this tick.
        if distance < 2.0:
            acc.stationary_ticks += 1
        else:
            acc.stationary_ticks = 0

    return acc


# ---------------------------------------------------------------------------
# Tracker: Whisper
# ---------------------------------------------------------------------------


def update_whisper_tracker(
    accumulators: GlobalAccumulators,
    belief_state: BeliefState,
) -> None:
    """Track whisper entries and partnerships from belief_state."""
    prev_occupants: list[int] = belief_state.extra.get(
        "_eurydice_prev_whisper_occupants", []
    )
    current_occupants = list(belief_state.whisper_occupants)

    # Detect new entrants to our whisper
    if belief_state.in_whisper:
        new_entrants = set(current_occupants) - set(prev_occupants)
        for entrant_index in new_entrants:
            player_id = player_index_to_id(entrant_index, belief_state)
            if player_id is None:
                continue
            acc = _ensure_accumulator(accumulators, player_id)
            acc.whisper_entries_this_round += 1
            acc.whisper_entry_ticks.append(belief_state.tick)

        # Track partners (all current occupants are partners with each other)
        for occ_index in current_occupants:
            occ_pid = player_index_to_id(occ_index, belief_state)
            if occ_pid is None:
                continue
            acc = _ensure_accumulator(accumulators, occ_pid)
            for other_index in current_occupants:
                if other_index == occ_index:
                    continue
                other_pid = player_index_to_id(other_index, belief_state)
                if other_pid is not None:
                    acc.whisper_partners_this_round.add(other_pid)

            # Track time in whisper
            acc.total_time_in_whispers_ticks += 1

    belief_state.extra["_eurydice_prev_whisper_occupants"] = current_occupants


# ---------------------------------------------------------------------------
# Tracker: Exchange
# ---------------------------------------------------------------------------


def update_exchange_tracker(
    accumulators: GlobalAccumulators,
    knowledge: dict[PlayerID, PlayerKnowledge],
    belief_state: BeliefState,
) -> None:
    """Scan chat_history for exchange-related system messages.

    Uses substring matching for OCR resilience.
    """
    prev_len: int = belief_state.extra.get("_eurydice_prev_chat_len", 0)
    current_len = len(belief_state.chat_history)

    if current_len <= prev_len:
        belief_state.extra["_eurydice_prev_chat_len"] = current_len
        return

    new_messages = belief_state.chat_history[prev_len:]
    belief_state.extra["_eurydice_prev_chat_len"] = current_len

    for msg in new_messages:
        # Only process system messages (sender_index is None for system msgs)
        if msg.sender_index is not None:
            continue

        text_upper = msg.text.upper()

        # Determine the "other" player in a 2-person whisper
        other_index = _whisper_other_occupant(belief_state)
        other_pid = (
            player_index_to_id(other_index, belief_state)
            if other_index is not None
            else None
        )

        if "SWAP" in text_upper or "SWAPPED" in text_upper:
            # Color exchange completed
            if other_pid is not None:
                acc = _ensure_accumulator(accumulators, other_pid)
                acc.color_offers_received_and_accepted += 1
                pk = _ensure_knowledge(knowledge, other_pid)
                pk.has_exchanged_colors_with_us = True

        elif "SHARED" in text_upper and "ROLE" in text_upper:
            # Role exchange completed
            if other_pid is not None:
                acc = _ensure_accumulator(accumulators, other_pid)
                acc.role_offers_received_and_accepted += 1
                pk = _ensure_knowledge(knowledge, other_pid)
                pk.has_exchanged_roles_with_us = True

        elif "OFFER" in text_upper and "COLOR" in text_upper:
            # Color offer made/received
            if other_pid is not None:
                acc = _ensure_accumulator(accumulators, other_pid)
                acc.color_offers_made += 1
                # Track eagerness
                if acc.ticks_before_first_offer is None and belief_state.in_whisper:
                    # Estimate ticks since whisper entry
                    if acc.whisper_entry_ticks:
                        entry_tick = acc.whisper_entry_ticks[-1]
                        acc.ticks_before_first_offer = (
                            belief_state.tick - entry_tick
                        )

        elif "OFFER" in text_upper and "ROLE" in text_upper:
            # Role offer made/received
            if other_pid is not None:
                acc = _ensure_accumulator(accumulators, other_pid)
                acc.role_offers_made += 1
                if acc.ticks_before_first_offer is None and belief_state.in_whisper:
                    if acc.whisper_entry_ticks:
                        entry_tick = acc.whisper_entry_ticks[-1]
                        acc.ticks_before_first_offer = (
                            belief_state.tick - entry_tick
                        )

        elif "WITHDREW" in text_upper or "WITHDRE" in text_upper:
            # Offer withdrawn -- no accumulator update needed
            pass

        elif "SHOWED" in text_upper:
            # One-way role reveal
            pass

        elif "DECLINED" in text_upper or "DECLINE" in text_upper:
            # Role offer declined
            if other_pid is not None:
                acc = _ensure_accumulator(accumulators, other_pid)
                acc.role_offers_received_and_declined += 1
                pk = _ensure_knowledge(knowledge, other_pid)
                pk.refused_role_exchange = True


def _whisper_other_occupant(belief_state: BeliefState) -> int | None:
    """Return the single other occupant index in a 2-person whisper."""
    if not belief_state.in_whisper:
        return None
    occupants = belief_state.whisper_occupants
    if belief_state.my_index is None:
        return occupants[0] if len(occupants) == 1 else None
    others = [o for o in occupants if o != belief_state.my_index]
    return others[0] if len(others) == 1 else None


# ---------------------------------------------------------------------------
# Tracker: Chat
# ---------------------------------------------------------------------------


def update_chat_tracker(
    accumulators: GlobalAccumulators,
    knowledge: dict[PlayerID, PlayerKnowledge],
    belief_state: BeliefState,
) -> None:
    """Track non-system chat messages for behavioral analysis."""
    prev_len: int = belief_state.extra.get("_eurydice_prev_chat_len", 0)
    # Note: prev_len was already updated by exchange_tracker.
    # We process the same new_messages window but only non-system ones.
    # Re-derive the window from chat_history using a separate counter.
    chat_counter_key = "_eurydice_chat_tracker_len"
    chat_prev_len: int = belief_state.extra.get(chat_counter_key, 0)
    current_len = len(belief_state.chat_history)

    if current_len <= chat_prev_len:
        belief_state.extra[chat_counter_key] = current_len
        return

    new_messages = belief_state.chat_history[chat_prev_len:]
    belief_state.extra[chat_counter_key] = current_len

    for msg in new_messages:
        if msg.sender_index is None:
            continue  # System message; handled by exchange_tracker

        player_id = player_index_to_id(msg.sender_index, belief_state)
        if player_id is None:
            continue

        acc = _ensure_accumulator(accumulators, player_id)
        pk = _ensure_knowledge(knowledge, player_id)

        if msg.channel == "global" or msg.channel == "shout":
            acc.global_messages_sent_this_round += 1
        elif msg.channel == "whisper":
            acc.whisper_messages_sent += 1

        acc.message_content_log.append((belief_state.tick, msg.text))
        pk.claims_made.append(msg.text)


# ---------------------------------------------------------------------------
# Tracker: Leadership
# ---------------------------------------------------------------------------


def update_leadership_tracker(
    accumulators: GlobalAccumulators,
    belief_state: BeliefState,
) -> None:
    """Track leadership state changes.

    Note: Detailed usurp vote tracking requires parsing system messages
    for "LEADER" keyword. For now, we track our own leadership status
    and room leader colors.
    """
    # Leadership tracking is primarily used by the strategic layer.
    # The accumulator fields (sought_leadership, passed_leadership) are
    # updated when we observe system messages about leadership changes.
    # This is handled minimally here; full implementation requires
    # tracking specific system message patterns that we detect in
    # update_exchange_tracker.
    pass


# ---------------------------------------------------------------------------
# Behavioral flag derivation
# ---------------------------------------------------------------------------


def derive_behavioral_flags(
    acc: PlayerAccumulator,
    knowledge: dict[PlayerID, PlayerKnowledge],
    accumulators: GlobalAccumulators,
    belief_state: BeliefState,
) -> set[str]:
    """Derive behavioral flags from accumulated observations.

    Returns the set of currently active flags for this player.
    """
    flags: set[str] = set()
    round_ticks = belief_state.tick - accumulators.round_start_tick

    # "aggressive_probing": many whisper entries in short time
    if acc.whisper_entries_this_round >= 3 and round_ticks < 300:
        flags.add("aggressive_probing")
    elif acc.whisper_entries_this_round >= 2 and round_ticks < 180:
        flags.add("aggressive_probing")

    # "avoids_interaction": visible for extended time but never in whispers
    if (
        acc.visible_ticks_this_round > 200
        and acc.whisper_entries_this_round == 0
        and acc.stationary_ticks > 100
    ):
        flags.add("avoids_interaction")

    # "defensive_posture": low movement, few interactions, seeking leadership
    if (
        acc.total_distance_this_round < 50.0
        and acc.whisper_entries_this_round <= 1
    ):
        if acc.sought_leadership or acc.stationary_ticks > 150:
            flags.add("defensive_posture")

    # "exchange_eager": offered exchange very quickly in whisper
    if (
        acc.ticks_before_first_offer is not None
        and acc.ticks_before_first_offer < 48
    ):
        flags.add("exchange_eager")

    # "refuses_role_exchange": declined at least one R.OFFER
    if acc.role_offers_received_and_declined > 0:
        flags.add("refuses_role_exchange")

    # "seeks_specific_teammate": approaches same-team players preferentially
    if len(acc.distinct_players_approached) >= 2:
        approached_teams: list[Team | None] = []
        for approached_pid in acc.distinct_players_approached:
            pk = knowledge.get(approached_pid)
            if pk is not None and pk.team is not None:
                approached_teams.append(pk.team)
        if (
            approached_teams
            and all(t == approached_teams[0] for t in approached_teams)
        ):
            flags.add("seeks_specific_teammate")

    # "chatty_global": high global chat frequency
    if acc.global_messages_sent_this_round >= 2:
        flags.add("chatty_global")

    # "relaxed_after_urgency": was highly active in prior rounds, now passive
    if (
        acc.max_whisper_entries_any_round >= 3
        and acc.whisper_entries_this_round == 0
        and round_ticks > 120
    ):
        flags.add("relaxed_after_urgency")

    # "whispers_with_both_teams": partners include players from both teams
    partner_teams: set[Team] = set()
    for partner_id in acc.whisper_partners_this_round:
        pk = knowledge.get(partner_id)
        if pk is not None and pk.team is not None:
            partner_teams.add(pk.team)
    if len(partner_teams) >= 2:
        flags.add("whispers_with_both_teams")

    return flags


# ---------------------------------------------------------------------------
# Hard inference rules (certainty = 1.0)
# ---------------------------------------------------------------------------


def run_hard_inferences(
    knowledge: dict[PlayerID, PlayerKnowledge],
    belief_state: BeliefState,
) -> None:
    """Apply mechanical-truth updates to player knowledge.

    Sources: exchange events (from belief_state.last_exchange_event),
    player visibility (room assignment), roster reveal data.
    """
    # Room assignment from direct visibility
    my_room_enum = belief_state.my_room
    if my_room_enum is not None:
        for index, player_info in belief_state.players.items():
            if player_info.position is None:
                continue
            _, _, pos_tick = player_info.position
            if pos_tick != belief_state.tick:
                continue
            # Player is visible this tick -> same room as us
            player_id = player_index_to_id(index, belief_state)
            if player_id is None:
                continue
            pk = _ensure_knowledge(knowledge, player_id)
            pk.room = my_room_enum
            pk.room_confidence = 1.0
            pk.room_last_confirmed_tick = belief_state.tick

    # Room assignment from roster reveal (stored in players dict)
    for index, player_info in belief_state.players.items():
        if player_info.room is not None:
            player_id = player_index_to_id(index, belief_state)
            if player_id is None:
                continue
            pk = _ensure_knowledge(knowledge, player_id)
            # Only update if we don't have more recent info
            if pk.room_confidence < 1.0 or pk.room is None:
                pk.room = player_info.room
                pk.room_confidence = 1.0
                pk.room_last_confirmed_tick = belief_state.tick

    # Team/role from Orpheus player registry (game display source)
    for index, player_info in belief_state.players.items():
        player_id = player_index_to_id(index, belief_state)
        if player_id is None:
            continue
        pk = _ensure_knowledge(knowledge, player_id)

        # Team from Orpheus belief_update (color exchange or info screen)
        if player_info.team is not None and pk.team_source in (
            TeamSource.NONE,
            TeamSource.INFERRED,
        ):
            team = _parse_team_string(player_info.team)
            if team is not None:
                pk.team = team
                pk.team_source = TeamSource.COLOR_EXCHANGE
                pk.team_confidence = 1.0  # Default config has no Spy

        # Role from Orpheus belief_update (role exchange or info screen)
        if player_info.role is not None and pk.role_source in (
            RoleSource.NONE,
            RoleSource.INFERRED,
            RoleSource.CHAT_CLAIM,
        ):
            role = _parse_role_string(player_info.role)
            if role is not None:
                pk.role = role
                pk.role_source = RoleSource.ROLE_EXCHANGE
                # Also set team from role
                pk.team = _team_from_role(role)
                pk.team_source = TeamSource.ROLE_EXCHANGE
                pk.team_confidence = 1.0

    # Update trust levels based on knowledge confidence
    for pk in knowledge.values():
        if pk.role_source == RoleSource.ROLE_EXCHANGE:
            pk.trust_level = TrustLevel.VERIFIED
        elif pk.team_source in (TeamSource.COLOR_EXCHANGE, TeamSource.ROLE_EXCHANGE):
            my_team_str = belief_state.my_team
            if my_team_str is not None:
                my_team = _parse_team_string(my_team_str)
                if my_team is not None and pk.team is not None:
                    if pk.team == my_team:
                        pk.trust_level = TrustLevel.PROBABLE
                    else:
                        pk.trust_level = TrustLevel.HOSTILE


# ---------------------------------------------------------------------------
# Soft inference rules (certainty < 1.0)
# ---------------------------------------------------------------------------


def run_soft_inferences(
    knowledge: dict[PlayerID, PlayerKnowledge],
    belief_state: BeliefState,
) -> None:
    """Apply probabilistic inferences from behavioral flags."""
    my_team_str = belief_state.my_team
    my_team = _parse_team_string(my_team_str) if my_team_str else None

    for pk in knowledge.values():
        # "refuses_role_exchange" + same team -> likely key role
        if (
            "refuses_role_exchange" in pk.behavioral_flags
            and pk.team is not None
            and pk.team == my_team
            and pk.role is None
        ):
            # Confidence 0.3 per observation, already captured by flag presence
            pass  # Role inference is tentative; don't overwrite

        # "exchange_eager" + same team -> likely key role searcher
        if (
            "exchange_eager" in pk.behavioral_flags
            and pk.team is not None
            and pk.team == my_team
            and pk.role is None
        ):
            pk.exchange_eagerness = min(pk.exchange_eagerness + 0.35, 0.7)

        # "avoids_interaction" -> possible key role (Hades/Persephone)
        # Low confidence since avoidance has many explanations
        if "avoids_interaction" in pk.behavioral_flags:
            pass  # Noted in flags; strategic layer uses directly

        # Claims contradicting mechanical reveals -> deceptive
        if pk.claims_about_identity is not None and pk.team is not None:
            claim_upper = pk.claims_about_identity.upper()
            if pk.team == Team.SHADES and (
                "NYMPH" in claim_upper or "PERSEPHONE" in claim_upper or "DEMETER" in claim_upper
            ):
                if "inconsistent_claims" not in pk.behavioral_flags:
                    pk.behavioral_flags.add("inconsistent_claims")
            elif pk.team == Team.NYMPHS and (
                "SHADE" in claim_upper or "HADES" in claim_upper or "CERBERUS" in claim_upper
            ):
                if "inconsistent_claims" not in pk.behavioral_flags:
                    pk.behavioral_flags.add("inconsistent_claims")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_team_string(team_str: str | None) -> Team | None:
    """Convert Orpheus team string ('shades'/'nymphs') to Team enum."""
    if team_str is None:
        return None
    normalized = team_str.strip().lower()
    if normalized == "shades":
        return Team.SHADES
    if normalized == "nymphs":
        return Team.NYMPHS
    return None


def _parse_role_string(role_str: str | None) -> Role | None:
    """Convert Orpheus role string to Role enum."""
    if role_str is None:
        return None
    normalized = role_str.strip().lower()
    role_map = {
        "hades": Role.HADES,
        "cerberus": Role.CERBERUS,
        "shade": Role.SHADE,
        "persephone": Role.PERSEPHONE,
        "demeter": Role.DEMETER,
        "nymph": Role.NYMPH,
        "spy": Role.SPY,
    }
    return role_map.get(normalized)


def _team_from_role(role: Role) -> Team:
    """Derive team from role."""
    if role in (Role.HADES, Role.CERBERUS, Role.SHADE):
        return Team.SHADES
    if role in (Role.PERSEPHONE, Role.DEMETER, Role.NYMPH):
        return Team.NYMPHS
    # Spy: real team is context-dependent; default to SHADES as placeholder
    return Team.SHADES
