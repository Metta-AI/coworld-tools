"""Belief update integration for Orpheus perception frames."""

from __future__ import annotations

import numpy as np

from orpheus.belief_state import (
    BeliefState,
    ChatMessageRecord,
    MinimapSighting,
    PlayerInfo,
)
from orpheus.perception._common import PLAYER_COLORS, TEAM_A_COLOR, TEAM_B_COLOR
from orpheus.perception.types import (
    ChatMessage,
    ChatroomPerception,
    ExchangePerception,
    ExchangePlayer,
    FramePerception,
    GlobalChatPerception,
    InfoScreenPerception,
    KnownPlayer,
    LobbyPerception,
    OverworldPerception,
    PlayerShape,
    ResultPerception,
    RoleRevealPerception,
    Room,
    RosterRevealPerception,
    View,
    VisiblePlayer,
)
from orpheus.types import KnowledgeSource

OVERWORLD_VIEWS = {
    View.PLAYING,
    View.HOSTAGE_SELECT,
    View.LEADER_SUMMIT,
    View.WAITING_ENTRY,
}

# BeliefState instances live for the lifetime of a Pipeline, so id() reuse is
# acceptable in practice despite not being a general-purpose object identity
# cache strategy.
_previous_positions: dict[int, tuple[int, int]] = {}


def apply(
    belief_state: BeliefState,
    perception: FramePerception,
    previous_view: View,
) -> None:
    """Mutate belief_state in place by integrating one frame's perception.

    Args:
        belief_state: Persistent framework belief state to update.
        perception: Symbolic perception output for the current frame.
        previous_view: View from the previous tick, used for Lobby reset and
            whisper-exit transitions.
    """
    if _is_lobby_reset(perception.view, previous_view):
        belief_state.reset()
        _previous_positions.pop(id(belief_state), None)

    _apply_universal_updates(belief_state, perception.view)

    if perception.view == View.LOBBY:
        _apply_lobby(belief_state, perception.lobby)
    elif perception.view == View.ROSTER_REVEAL:
        _apply_roster_reveal(belief_state, perception.roster_reveal)
    elif perception.view == View.ROLE_REVEAL:
        _apply_role_reveal(belief_state, perception.role_reveal)
    elif perception.view in OVERWORLD_VIEWS:
        _apply_overworld(
            belief_state,
            perception.overworld,
            perception.view,
            perception.raw_pixels,
        )
    elif perception.view == View.WHISPER:
        _apply_whisper(belief_state, perception.chatroom)
    elif perception.view == View.GLOBAL_CHAT:
        _apply_global_chat(belief_state, perception.global_chat)
    elif perception.view == View.INFO_SCREEN:
        _apply_info_screen(belief_state, perception.info_screen)
    elif perception.view == View.HOSTAGE_EXCHANGE:
        _apply_exchange(belief_state, perception.exchange)
    elif perception.view in {View.REVEAL, View.GAME_OVER}:
        _apply_result(belief_state, perception.result)


def decode_player_index(
    color: int,
    shape: PlayerShape | None,
    player_count: int | None,
) -> int | None:
    """Return the unique player index matching ``(color, shape)``.

    The player color repeats every 8 indices and shape repeats every 12
    indices. Since lcm(8, 12) = 24, the pair is unique for up to 24 players.

    Args:
        color: PICO-8 palette index for the player color.
        shape: Detected player shape, or None if shape detection failed.
        player_count: Known player count. If unknown, search the full 0..23
            possible index space.

    Returns:
        The matching player index, or None if no unique match is available.
    """
    if shape is None:
        return None

    for index in range(player_count or 24):
        if (
            PLAYER_COLORS[index % 8] == color
            and PlayerShape(index % 12) == shape
        ):
            return index
    return None


def team_color_to_name(color: int | None) -> str | None:
    """Map a team color palette index to a canonical team name."""
    if color == TEAM_A_COLOR:
        return "shades"
    if color == TEAM_B_COLOR:
        return "nymphs"
    return None


def room_string_to_enum(s: str | None) -> Room | None:
    """Map a perception room string to a Room enum."""
    if s is None:
        return None

    normalized = s.strip().lower().replace("_", " ")
    if normalized == "underworld":
        return Room.UNDERWORLD
    if normalized == "mortal realm":
        return Room.MORTAL_REALM
    return None


def _is_lobby_reset(current_view: View, previous_view: View) -> bool:
    return (
        current_view == View.LOBBY
        and previous_view not in {View.LOBBY, View.UNKNOWN}
    )


def _apply_universal_updates(
    belief_state: BeliefState,
    current_view: View,
) -> None:
    previous_in_whisper = belief_state.in_whisper

    belief_state.tick += 1
    belief_state.view = current_view
    belief_state.in_whisper = current_view == View.WHISPER

    if previous_in_whisper and not belief_state.in_whisper:
        belief_state.whisper_occupants = []
        belief_state.pending_offers = {"role": False, "color": False}
        belief_state.pending_entry = None
        belief_state.menu_state = None
        belief_state.active_color_offers = []
        belief_state.active_role_offers = []
        belief_state.last_exchange_event = None

    expired: list[str] = []
    for key, value in list(belief_state.cooldowns.items()):
        if value > 0:
            belief_state.cooldowns[key] = value - 1
        if belief_state.cooldowns[key] <= 0:
            expired.append(key)

    for key in expired:
        del belief_state.cooldowns[key]


def _apply_lobby(
    belief_state: BeliefState,
    lobby: LobbyPerception | None,
) -> None:
    if lobby is None:
        return

    if lobby.player_count is not None:
        belief_state.player_count = lobby.player_count


def _apply_roster_reveal(
    belief_state: BeliefState,
    roster_reveal: RosterRevealPerception | None,
) -> None:
    if roster_reveal is None:
        return

    for entry in roster_reveal.players:
        player_index = decode_player_index(
            entry.color,
            entry.shape,
            belief_state.player_count,
        )
        if player_index is None:
            continue

        player = belief_state.players.setdefault(player_index, PlayerInfo())
        player.room = entry.room


def _apply_role_reveal(
    belief_state: BeliefState,
    role_reveal: RoleRevealPerception | None,
) -> None:
    if role_reveal is None:
        return

    if belief_state.player_count is None and role_reveal.player_count is not None:
        belief_state.player_count = role_reveal.player_count

    if role_reveal.panel_index is not None:
        belief_state.role_reveal_panel_index = role_reveal.panel_index

    is_role_card = role_reveal.panel_index in (None, 1)
    if is_role_card:
        if belief_state.my_role is None and role_reveal.role is not None:
            belief_state.my_role = role_reveal.role.lower()

        if belief_state.my_team is None and role_reveal.team is not None:
            belief_state.my_team = role_reveal.team.lower()

        if belief_state.my_room is None:
            belief_state.my_room = room_string_to_enum(role_reveal.room)

        if (
            belief_state.room_size is None
            and role_reveal.room_size is not None
            and role_reveal.room_size > 0
        ):
            belief_state.room_size = (
                role_reveal.room_size,
                role_reveal.room_size,
            )

        if belief_state.my_color is None and role_reveal.self_color is not None:
            belief_state.my_color = role_reveal.self_color

        if belief_state.my_shape is None and role_reveal.self_shape is not None:
            belief_state.my_shape = role_reveal.self_shape

        if (
            belief_state.my_index is None
            and belief_state.my_color is not None
            and belief_state.my_shape is not None
        ):
            belief_state.my_index = decode_player_index(
                belief_state.my_color,
                belief_state.my_shape,
                belief_state.player_count,
            )

    if not belief_state.round_schedule and role_reveal.round_schedule:
        belief_state.round_schedule = list(role_reveal.round_schedule)

    if role_reveal.match_roles:
        belief_state.match_roles = list(role_reveal.match_roles)

    if role_reveal.missing_roles:
        belief_state.missing_roles = list(role_reveal.missing_roles)

    if role_reveal.echo_substitutions:
        belief_state.echo_substitutions = list(role_reveal.echo_substitutions)

    if role_reveal.spy_in_game_config is not None:
        belief_state.spy_in_game_config = role_reveal.spy_in_game_config

    if (
        belief_state.occupancy_grid is None
        and belief_state.room_size is not None
        and _room_size_is_positive(belief_state.room_size)
    ):
        from orpheus.occupancy_grid import OccupancyGrid

        belief_state.occupancy_grid = OccupancyGrid(
            belief_state.room_size,
            resolution=2,
        )


def _apply_overworld(
    belief_state: BeliefState,
    overworld: OverworldPerception | None,
    view: View,
    raw_pixels: np.ndarray | None,
) -> None:
    if overworld is None:
        return

    new_position: tuple[int, int] | None = None
    if overworld.self_position is not None:
        new_position = (
            overworld.self_position.x,
            overworld.self_position.y,
        )
        belief_state.position = new_position

    if overworld.room is not None:
        belief_state.room = overworld.room

    if overworld.round is not None:
        belief_state.round = overworld.round

    if overworld.timer_secs is not None:
        belief_state.timer_secs = overworld.timer_secs

    _apply_overworld_visible_players(belief_state, overworld)
    _apply_overworld_speech_bubbles(belief_state, overworld)
    _apply_overworld_minimap_sightings(belief_state, overworld)

    belief_state.is_leader = overworld.is_leader
    if overworld.is_leader and belief_state.my_room is not None:
        leader_color = overworld.role_team_color
        if leader_color is None:
            leader_color = belief_state.my_color
        if leader_color is not None:
            # TODO Stage 2 perception gap: full leader detection for other
            # rooms requires crown indicators for visible non-self players.
            belief_state.leader_colors[belief_state.my_room] = leader_color

    if overworld.last_shout is not None:
        _append_shout_if_new(belief_state, overworld.last_shout)

    occupancy_grid = belief_state.occupancy_grid
    if occupancy_grid is not None:
        previous_position = _previous_positions.get(id(belief_state))
        if new_position is not None and new_position != previous_position:
            occupancy_grid.update_from_movement(new_position)
        if raw_pixels is not None and new_position is not None:
            occupancy_grid.update_from_viewport(
                new_position,
                raw_pixels,
                belief_state.room,
            )
        if belief_state.room_size is not None and overworld.minimap_dots:
            occupancy_grid.update_from_minimap(
                overworld.minimap_dots,
                belief_state.room_size,
                belief_state.my_color,
            )
        if new_position is not None:
            _previous_positions[id(belief_state)] = new_position

    if (
        view == View.HOSTAGE_SELECT
        and overworld.hostage_grid is not None
        and overworld.is_leader_selecting
    ):
        belief_state.hostage_selections = overworld.hostage_grid


def _apply_overworld_speech_bubbles(
    belief_state: BeliefState,
    overworld: OverworldPerception,
) -> None:
    for bubble in overworld.speech_bubbles:
        player_index = decode_player_index(
            bubble.player_color,
            bubble.player_shape,
            belief_state.player_count,
        )
        if player_index is None:
            player_index = _find_player_by_color(belief_state, bubble.player_color)
        if player_index is None:
            continue

        player = belief_state.players.setdefault(player_index, PlayerInfo())
        world_position = _screen_to_world(
            belief_state,
            bubble.screen_x,
            bubble.screen_y,
        )
        if world_position is not None:
            player.position = (
                world_position[0],
                world_position[1],
                belief_state.tick,
            )
        player.last_seen_in_whisper = belief_state.tick


def _apply_overworld_visible_players(
    belief_state: BeliefState,
    overworld: OverworldPerception,
) -> None:
    for visible in overworld.visible_players:
        _apply_visible_player(belief_state, visible, mark_in_whisper=False)


def _apply_visible_player(
    belief_state: BeliefState,
    visible: VisiblePlayer,
    *,
    mark_in_whisper: bool,
) -> None:
    player_index = decode_player_index(
        visible.player_color,
        visible.player_shape,
        belief_state.player_count,
    )
    if player_index is None:
        player_index = _find_player_by_color(belief_state, visible.player_color)
    if player_index is None:
        return

    player = belief_state.players.setdefault(player_index, PlayerInfo())
    world_position = _screen_to_world(
        belief_state,
        visible.screen_x,
        visible.screen_y,
    )
    if world_position is not None:
        player.position = (
            world_position[0],
            world_position[1],
            belief_state.tick,
        )
    if mark_in_whisper:
        player.last_seen_in_whisper = belief_state.tick
    if visible.role_indicator is not None:
        player.role = visible.role_indicator.role
        player.role_source = KnowledgeSource.GAME_DISPLAY
        player.team = visible.role_indicator.team
        player.team_source = KnowledgeSource.GAME_DISPLAY


def _find_player_by_color(belief_state: BeliefState, color: int) -> int | None:
    from orpheus.perception._common import PLAYER_COLORS
    matches = [
        i for i in range(belief_state.player_count or 10)
        if PLAYER_COLORS[i % len(PLAYER_COLORS)] == color
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _apply_overworld_minimap_sightings(
    belief_state: BeliefState,
    overworld: OverworldPerception,
) -> None:
    for dot in overworld.minimap_dots:
        if dot.is_self:
            continue

        belief_state.minimap_sightings.append(
            MinimapSighting(
                color=dot.color,
                position=(dot.world_x, dot.world_y),
                tick=belief_state.tick,
            )
        )


def _screen_to_world(
    belief_state: BeliefState,
    screen_x: int,
    screen_y: int,
) -> tuple[int, int] | None:
    if belief_state.position is None or belief_state.room_size is None:
        return None

    self_center_x, self_center_y = belief_state.position
    room_w, room_h = belief_state.room_size
    camera_x = _clamp(self_center_x - 64, 0, room_w - 128)
    camera_y = _clamp(self_center_y - 64, -9, room_h - 119)
    return screen_x + camera_x, screen_y + camera_y


def _clamp(value: int, lower: int, upper: int) -> int:
    return min(max(value, lower), upper)


def _room_size_is_positive(room_size: tuple[int, int]) -> bool:
    return room_size[0] > 0 and room_size[1] > 0


def _append_shout_if_new(belief_state: BeliefState, text: str) -> None:
    for record in reversed(belief_state.chat_history):
        if record.channel == "shout":
            if record.text == text:
                return
            break

    belief_state.chat_history.append(
        ChatMessageRecord(
            sender_index=None,
            tick=belief_state.tick,
            channel="shout",
            text=text,
            occupants=None,
        )
    )


def _apply_whisper(
    belief_state: BeliefState,
    chatroom: ChatroomPerception | None,
) -> None:
    if chatroom is None:
        return

    belief_state.whisper_occupants = []
    for color, shape in zip(chatroom.occupant_colors, chatroom.occupant_shapes):
        # Ambiguous color-only occupants are skipped until shape perception
        # succeeds; color alone can map to multiple player indices.
        player_index = decode_player_index(
            color,
            shape,
            belief_state.player_count,
        )
        if player_index is not None:
            belief_state.whisper_occupants.append(player_index)

    for message in chatroom.messages:
        appended = _append_chat_message_if_new(
            belief_state,
            message,
            channel="whisper",
            occupants=list(belief_state.whisper_occupants),
        )
        if appended and message.is_system:
            _apply_whisper_system_message(belief_state, chatroom, message)

    belief_state.pending_offers = {
        "role": chatroom.pending_role_offer,
        "color": chatroom.pending_color_offer,
    }

    if chatroom.has_pending_entry:
        belief_state.pending_entry = decode_player_index(
            chatroom.pending_entry_color,
            chatroom.pending_entry_shape,
            belief_state.player_count,
        )
        if belief_state.pending_entry is None:
            belief_state.pending_entry = _find_player_by_color(
                belief_state, chatroom.pending_entry_color,
            )
    else:
        belief_state.pending_entry = None

    belief_state.menu_state = {
        "bar": chatroom.bottom_bar,
        "category": chatroom.menu_category,
        "item": chatroom.menu_item,
        "enabled": chatroom.menu_enabled,
        "target_mode": chatroom.target_mode,
        "target_colors": list(chatroom.target_colors),
    }


def _append_chat_message_if_new(
    belief_state: BeliefState,
    message: ChatMessage,
    channel: str,
    occupants: list[int] | None,
) -> bool:
    sender_index = _decode_message_sender(belief_state, message)
    for record in belief_state.chat_history[-20:]:
        if (
            record.channel == channel
            and record.sender_index == sender_index
            and record.text == message.text
        ):
            return False

    belief_state.chat_history.append(
        ChatMessageRecord(
            sender_index=sender_index,
            tick=belief_state.tick,
            channel=channel,
            text=message.text,
            occupants=occupants,
        )
    )
    return True


def _apply_whisper_system_message(
    belief_state: BeliefState,
    chatroom: ChatroomPerception,
    message: ChatMessage,
) -> None:
    text = message.text.casefold()

    if "shared roles" in text:
        participants = _completion_participants(belief_state, message)
        _set_exchange_event(belief_state, "shared_roles", participants)
        _clear_completed_offers(belief_state.active_role_offers, participants)
        if belief_state.my_index in participants:
            for participant in participants:
                if participant != belief_state.my_index:
                    belief_state.my_exchange_partner = participant
                    break
        return

    if "swapped colors" in text:
        participants = _completion_participants(belief_state, message)
        _set_exchange_event(belief_state, "swapped_colors", participants)
        _clear_completed_offers(belief_state.active_color_offers, participants)
        return

    if "withdrew" in text:
        sender_index = _decode_system_message_sender(belief_state, message)
        participants = [sender_index] if sender_index is not None else []
        _set_exchange_event(belief_state, "withdrew", participants)
        _clear_withdrawn_offers(belief_state, text, participants)
        return

    if "offered lead" in text or "offered leadership" in text:
        sender_index = _decode_system_message_sender(belief_state, message)
        participants = [sender_index] if sender_index is not None else []
        _set_exchange_event(belief_state, "offered_lead", participants)
        return

    if "offered color" in text or "color offered" in text:
        sender_index = _decode_system_message_sender(
            belief_state,
            message,
            allow_single_other=chatroom.pending_color_offer,
        )
        _append_unique_offer(belief_state.active_color_offers, sender_index)
        return

    if "offered role" in text or "role offered" in text:
        sender_index = _decode_system_message_sender(
            belief_state,
            message,
            allow_single_other=chatroom.pending_role_offer,
        )
        _append_unique_offer(belief_state.active_role_offers, sender_index)


def _append_unique_offer(offers: list[int], player_index: int | None) -> None:
    if player_index is not None and player_index not in offers:
        offers.append(player_index)


def _set_exchange_event(
    belief_state: BeliefState,
    event_type: str,
    participants: list[int],
) -> None:
    belief_state.last_exchange_event = {
        "type": event_type,
        "tick": belief_state.tick,
        "participants": list(participants),
    }


def _clear_completed_offers(offers: list[int], participants: list[int]) -> None:
    if participants:
        offers[:] = [offerer for offerer in offers if offerer not in participants]
    else:
        offers.clear()


def _clear_withdrawn_offers(
    belief_state: BeliefState,
    text: str,
    participants: list[int],
) -> None:
    if "color" in text:
        _clear_offer_by_participants(belief_state.active_color_offers, participants)
    elif "role" in text:
        _clear_offer_by_participants(belief_state.active_role_offers, participants)
    else:
        _clear_offer_by_participants(belief_state.active_color_offers, participants)
        _clear_offer_by_participants(belief_state.active_role_offers, participants)


def _clear_offer_by_participants(
    offers: list[int],
    participants: list[int],
) -> None:
    if participants:
        offers[:] = [offerer for offerer in offers if offerer not in participants]
    elif len(offers) == 1:
        offers.clear()


def _completion_participants(
    belief_state: BeliefState,
    message: ChatMessage,
) -> list[int]:
    refs = _decode_system_message_refs(belief_state, message.text)
    if refs:
        return refs

    sender_index = _decode_message_sender(belief_state, message)
    occupants = list(belief_state.whisper_occupants)
    if sender_index is not None:
        participants = [sender_index]
        others = [occupant for occupant in occupants if occupant != sender_index]
        if len(others) == 1:
            participants.append(others[0])
        elif (
            belief_state.my_index is not None
            and belief_state.my_index != sender_index
            and belief_state.my_index in occupants
        ):
            participants.append(belief_state.my_index)
        return participants

    if len(occupants) == 2:
        return occupants
    return []


def _decode_system_message_sender(
    belief_state: BeliefState,
    message: ChatMessage,
    *,
    allow_single_other: bool = False,
) -> int | None:
    sender_index = _decode_message_sender(belief_state, message)
    if sender_index is not None:
        return sender_index

    refs = _decode_system_message_refs(belief_state, message.text)
    if refs:
        return refs[0]

    if allow_single_other:
        return _single_other_occupant(belief_state)
    return None


def _decode_system_message_refs(
    belief_state: BeliefState,
    text: str,
) -> list[int]:
    refs: list[int] = []
    i = 0
    while i + 1 < len(text):
        if ord(text[i]) != 1:
            i += 1
            continue

        player_index = ord(text[i + 1])
        if (
            player_index not in refs
            and (belief_state.player_count is None or player_index < belief_state.player_count)
        ):
            refs.append(player_index)
        i += 2

    return refs


def _single_other_occupant(belief_state: BeliefState) -> int | None:
    occupants = list(belief_state.whisper_occupants)
    if belief_state.my_index is None:
        return occupants[0] if len(occupants) == 1 else None

    others = [occupant for occupant in occupants if occupant != belief_state.my_index]
    if len(others) == 1:
        return others[0]
    return None


def _decode_message_sender(
    belief_state: BeliefState,
    message: ChatMessage,
) -> int | None:
    if message.sender_color is None:
        return None
    return decode_player_index(
        message.sender_color,
        message.sender_shape,
        belief_state.player_count,
    )


def _apply_global_chat(
    belief_state: BeliefState,
    global_chat: GlobalChatPerception | None,
) -> None:
    if global_chat is None:
        return

    for message in global_chat.messages:
        _append_chat_message_if_new(
            belief_state,
            message,
            channel="global",
            occupants=None,
        )

    candidate = global_chat.usurp_candidate
    if (
        candidate is not None
        and candidate.player_color is not None
        and belief_state.room is not None
    ):
        # TODO Stage 2 perception gap: this approximates the visible usurp
        # candidate as current leader when no usurp is active.
        belief_state.leader_colors[belief_state.room] = candidate.player_color

    if global_chat.hostage_grid is not None and belief_state.is_leader:
        belief_state.hostage_selections = global_chat.hostage_grid


def _apply_info_screen(
    belief_state: BeliefState,
    info_screen: InfoScreenPerception | None,
) -> None:
    if info_screen is None:
        return

    for known_player in info_screen.known_players:
        _apply_known_player(belief_state, known_player)


def _apply_known_player(
    belief_state: BeliefState,
    known_player: KnownPlayer,
) -> None:
    if known_player.is_self:
        return

    player_index = decode_player_index(
        known_player.color,
        known_player.shape,
        belief_state.player_count,
    )
    if player_index is None:
        return

    player = belief_state.players.setdefault(player_index, PlayerInfo())
    if known_player.role_name is not None and not known_player.color_only:
        player.role = known_player.role_name
        player.role_source = KnowledgeSource.GAME_DISPLAY

    team_name = team_color_to_name(known_player.team_color)
    if team_name is not None:
        player.team = team_name
        player.team_source = KnowledgeSource.GAME_DISPLAY


def _apply_exchange(
    belief_state: BeliefState,
    exchange: ExchangePerception | None,
) -> None:
    if exchange is None:
        return

    for exchange_player in (
        exchange.leaders + exchange.departing + exchange.arriving
    ):
        _apply_exchange_player(belief_state, exchange_player)

    if belief_state.my_room is None:
        return

    other_room = _other_room(belief_state.my_room)
    for exchange_player in exchange.departing:
        player_index = _decode_exchange_player(belief_state, exchange_player)
        if player_index is not None:
            belief_state.players.setdefault(
                player_index,
                PlayerInfo(),
            ).room = other_room

    for exchange_player in exchange.arriving:
        player_index = _decode_exchange_player(belief_state, exchange_player)
        if player_index is not None:
            belief_state.players.setdefault(
                player_index,
                PlayerInfo(),
            ).room = belief_state.my_room


def _apply_exchange_player(
    belief_state: BeliefState,
    exchange_player: ExchangePlayer,
) -> None:
    player_index = _decode_exchange_player(belief_state, exchange_player)
    if player_index is None:
        return

    player = belief_state.players.setdefault(player_index, PlayerInfo())
    role_indicator = exchange_player.role_indicator
    if role_indicator is None:
        return

    player.role = role_indicator.role
    player.role_source = KnowledgeSource.GAME_DISPLAY
    player.team = role_indicator.team
    player.team_source = KnowledgeSource.GAME_DISPLAY


def _decode_exchange_player(
    belief_state: BeliefState,
    exchange_player: ExchangePlayer,
) -> int | None:
    return decode_player_index(
        exchange_player.color,
        exchange_player.shape,
        belief_state.player_count,
    )


def _other_room(room: Room) -> Room:
    if room == Room.UNDERWORLD:
        return Room.MORTAL_REALM
    return Room.UNDERWORLD


def _apply_result(
    belief_state: BeliefState,
    result: ResultPerception | None,
) -> None:
    if result is None or result.winner is None:
        return

    belief_state.winner = result.winner.lower()


__all__ = [
    "apply",
    "decode_player_index",
    "team_color_to_name",
    "room_string_to_enum",
]
