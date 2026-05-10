"""Unit tests for the Orpheus Stage 2 belief update pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from orpheus import belief_update
from orpheus.belief_state import BeliefState, ChatMessageRecord, PlayerInfo
from orpheus.idle import IdleMode
from orpheus.mode import ModeRegistry
from orpheus.perception.types import (
    ChatMessage,
    ChatroomBarState,
    ChatroomPerception,
    ExchangePerception,
    ExchangePlayer,
    FramePerception,
    GlobalChatPerception,
    HostageGrid,
    InfoScreenPerception,
    KnownPlayer,
    LobbyPerception,
    MinimapDot,
    OverworldPerception,
    PlayerShape,
    Position,
    RoleIndicator,
    ResultPerception,
    RoleRevealPerception,
    Room,
    RosterEntry,
    RosterRevealPerception,
    SpeechBubble,
    UsurpCandidate,
    View,
    VisiblePlayer,
)
from orpheus.pipeline import Pipeline
from orpheus.types import KnowledgeSource, PLAYER_COLORS


def _frame(view: View, **kwargs) -> FramePerception:
    """Build a FramePerception with the supplied populated view payload."""
    return FramePerception(view=view, **kwargs)


def _apply(
    belief_state: BeliefState,
    perception: FramePerception,
    previous_view: View | None = None,
) -> None:
    """Apply perception using the current belief view by default."""
    belief_update.apply(
        belief_state,
        perception,
        belief_state.view if previous_view is None else previous_view,
    )


def _shape(index: int) -> PlayerShape:
    """Return the deterministic shape for a player index."""
    return PlayerShape(index % 12)


def _color(index: int) -> int:
    """Return the deterministic color for a player index."""
    return PLAYER_COLORS[index % 8]


def _system_ref(index: int) -> str:
    """Return the raw rich-text player reference used in system messages."""
    return "\x01" + chr(index)


def test_universal_tick_increment() -> None:
    """Belief update increments the tick on every frame."""
    belief_state = BeliefState()

    _apply(belief_state, _frame(View.UNKNOWN))
    _apply(belief_state, _frame(View.UNKNOWN))

    assert belief_state.tick == 2


def test_universal_view_set() -> None:
    """Belief update mirrors perception.view into belief_state.view."""
    belief_state = BeliefState()

    _apply(belief_state, _frame(View.GLOBAL_CHAT))

    assert belief_state.view == View.GLOBAL_CHAT


def test_universal_in_whisper_set_and_cleared() -> None:
    """Entering and leaving whisper updates the derived in_whisper flag."""
    belief_state = BeliefState()

    _apply(
        belief_state,
        _frame(View.WHISPER, chatroom=ChatroomPerception()),
    )
    assert belief_state.in_whisper is True

    _apply(
        belief_state,
        _frame(View.PLAYING, overworld=OverworldPerception()),
    )

    assert belief_state.in_whisper is False


def test_whisper_exit_clears_state() -> None:
    """Leaving whisper clears whisper-only state fields."""
    belief_state = BeliefState(
        in_whisper=True,
        whisper_occupants=[1, 2],
        pending_offers={"role": True, "color": True},
        pending_entry=3,
        menu_state={"bar": "menu"},
    )

    _apply(
        belief_state,
        _frame(View.PLAYING, overworld=OverworldPerception()),
        previous_view=View.WHISPER,
    )

    assert belief_state.whisper_occupants == []
    assert belief_state.pending_offers == {"role": False, "color": False}
    assert belief_state.active_color_offers == []
    assert belief_state.active_role_offers == []
    assert belief_state.last_exchange_event is None
    assert belief_state.pending_entry is None
    assert belief_state.menu_state is None


def test_cooldowns_tick_down_and_expire() -> None:
    """Cooldown values decrement and are removed once they hit zero."""
    belief_state = BeliefState(cooldowns={"chat": 2, "shout": 1})

    _apply(belief_state, _frame(View.UNKNOWN))
    assert belief_state.cooldowns == {"chat": 1}

    _apply(belief_state, _frame(View.UNKNOWN))
    assert belief_state.cooldowns == {}


def test_lobby_resets_state_after_non_lobby() -> None:
    """Lobby after a non-Lobby view resets game-specific state."""
    belief_state = BeliefState(
        tick=20,
        view=View.PLAYING,
        players={1: PlayerInfo(room=Room.UNDERWORLD)},
        my_role="hades",
    )

    _apply(
        belief_state,
        _frame(View.LOBBY, lobby=LobbyPerception(player_count=10)),
        previous_view=View.PLAYING,
    )

    assert belief_state.tick == 1
    assert belief_state.view == View.LOBBY
    assert belief_state.players == {}
    assert belief_state.my_role is None
    assert belief_state.player_count == 10


def test_lobby_does_not_reset_when_previous_was_lobby() -> None:
    """Consecutive Lobby frames preserve the existing belief state."""
    belief_state = BeliefState(
        tick=5,
        view=View.LOBBY,
        players={1: PlayerInfo(room=Room.UNDERWORLD)},
    )

    _apply(
        belief_state,
        _frame(View.LOBBY, lobby=LobbyPerception(player_count=10)),
        previous_view=View.LOBBY,
    )

    assert belief_state.tick == 6
    assert 1 in belief_state.players


def test_lobby_does_not_reset_when_previous_was_unknown() -> None:
    """Initial boot into Lobby does not clear preloaded state."""
    belief_state = BeliefState(
        tick=5,
        view=View.UNKNOWN,
        players={1: PlayerInfo(room=Room.UNDERWORLD)},
    )

    _apply(
        belief_state,
        _frame(View.LOBBY, lobby=LobbyPerception(player_count=10)),
        previous_view=View.UNKNOWN,
    )

    assert belief_state.tick == 6
    assert 1 in belief_state.players


def test_lobby_player_count_set() -> None:
    """Lobby player_count is copied when perception exposes it."""
    belief_state = BeliefState()

    _apply(
        belief_state,
        _frame(View.LOBBY, lobby=LobbyPerception(player_count=12)),
    )

    assert belief_state.player_count == 12


def test_roster_reveal_populates_player_registry() -> None:
    """RosterReveal creates player registry entries with room assignments."""
    belief_state = BeliefState(player_count=10)
    roster = RosterRevealPerception(
        players=[
            RosterEntry(
                color=_color(0),
                shape=_shape(0),
                room=Room.UNDERWORLD,
            ),
            RosterEntry(
                color=_color(9),
                shape=_shape(9),
                room=Room.MORTAL_REALM,
            ),
        ]
    )

    _apply(belief_state, _frame(View.ROSTER_REVEAL, roster_reveal=roster))

    assert belief_state.players[0].room == Room.UNDERWORLD
    assert belief_state.players[9].room == Room.MORTAL_REALM


def test_roster_reveal_skips_entries_without_shape() -> None:
    """RosterReveal skips ambiguous color-only entries."""
    belief_state = BeliefState(player_count=10)
    roster = RosterRevealPerception(
        players=[
            RosterEntry(
                color=_color(0),
                shape=None,
                room=Room.UNDERWORLD,
            )
        ]
    )

    _apply(belief_state, _frame(View.ROSTER_REVEAL, roster_reveal=roster))

    assert belief_state.players == {}


def test_role_reveal_sets_self_identity() -> None:
    """RoleReveal sets static self role, team, and room fields."""
    belief_state = BeliefState()
    role_reveal = RoleRevealPerception(
        panel_index=1,
        role="Hades",
        team="Shades",
        room="Underworld",
    )

    _apply(belief_state, _frame(View.ROLE_REVEAL, role_reveal=role_reveal))

    assert belief_state.my_role == "hades"
    assert belief_state.my_team == "shades"
    assert belief_state.my_room == Room.UNDERWORLD
    assert belief_state.role_reveal_panel_index == 1


def test_role_reveal_populates_self_color_shape_index() -> None:
    """RoleReveal centered own sprite resolves self color, shape, and index."""
    belief_state = BeliefState()
    role_reveal = RoleRevealPerception(
        self_color=8,
        self_shape=PlayerShape.TRIANGLE,
        player_count=10,
    )

    _apply(belief_state, _frame(View.ROLE_REVEAL, role_reveal=role_reveal))

    assert belief_state.player_count == 10
    assert belief_state.my_color == 8
    assert belief_state.my_shape == PlayerShape.TRIANGLE
    assert belief_state.my_index == 2


def test_role_reveal_populates_round_schedule() -> None:
    """RoleReveal schedule panel stores round durations and hostage counts."""
    belief_state = BeliefState()
    role_reveal = RoleRevealPerception(
        panel_index=3,
        round_schedule=[(180, 1), (120, 2), (45, 1)],
    )

    _apply(belief_state, _frame(View.ROLE_REVEAL, role_reveal=role_reveal))

    assert belief_state.round_schedule == [(180, 1), (120, 2), (45, 1)]


def test_role_reveal_populates_match_config() -> None:
    """RoleReveal summary panel stores role membership and Spy presence."""
    belief_state = BeliefState()
    role_reveal = RoleRevealPerception(
        panel_index=2,
        match_roles=["Hades", "Spy", "Nymph"],
        missing_roles=["Cerberus", "Demeter"],
        echo_substitutions=[("Echo of Hades", "Hades")],
        spy_in_game_config=True,
    )

    _apply(belief_state, _frame(View.ROLE_REVEAL, role_reveal=role_reveal))

    assert belief_state.match_roles == ["Hades", "Spy", "Nymph"]
    assert belief_state.missing_roles == ["Cerberus", "Demeter"]
    assert belief_state.echo_substitutions == [("Echo of Hades", "Hades")]
    assert belief_state.spy_in_game_config is True


def test_role_reveal_initializes_room_size_as_tuple() -> None:
    """RoleReveal converts square room_size into a width-height tuple."""
    belief_state = BeliefState()

    _apply(
        belief_state,
        _frame(
            View.ROLE_REVEAL,
            role_reveal=RoleRevealPerception(room_size=160),
        ),
    )

    assert belief_state.room_size == (160, 160)


def test_role_reveal_set_once() -> None:
    """RoleReveal static fields are not overwritten by later frames."""
    belief_state = BeliefState(
        my_role="hades",
        my_team="shades",
        my_room=Room.UNDERWORLD,
        room_size=(100, 100),
    )
    role_reveal = RoleRevealPerception(
        role="Nymph",
        team="Nymphs",
        room="Mortal Realm",
        room_size=200,
    )

    _apply(belief_state, _frame(View.ROLE_REVEAL, role_reveal=role_reveal))

    assert belief_state.my_role == "hades"
    assert belief_state.my_team == "shades"
    assert belief_state.my_room == Room.UNDERWORLD
    assert belief_state.room_size == (100, 100)


def test_role_reveal_missing_identity_fields_preserves_unknowns() -> None:
    """RoleReveal frames with missing identity fields do not crash or invent data."""
    belief_state = BeliefState()

    _apply(
        belief_state,
        _frame(View.ROLE_REVEAL, role_reveal=RoleRevealPerception()),
    )

    assert belief_state.my_role is None
    assert belief_state.my_team is None
    assert belief_state.my_room is None


def test_role_reveal_non_positive_room_size_does_not_create_grid() -> None:
    """Invalid RoleReveal room sizes are ignored for spatial grid creation."""
    for room_size in (0, -10):
        belief_state = BeliefState()

        _apply(
            belief_state,
            _frame(
                View.ROLE_REVEAL,
                role_reveal=RoleRevealPerception(room_size=room_size),
            ),
        )

        assert belief_state.room_size is None
        assert belief_state.occupancy_grid is None


def test_overworld_self_position_and_room() -> None:
    """Overworld perception updates self position and current room."""
    belief_state = BeliefState()
    overworld = OverworldPerception(
        self_position=Position(room=Room.UNDERWORLD, x=70, y=80),
        room=Room.MORTAL_REALM,
    )

    _apply(belief_state, _frame(View.PLAYING, overworld=overworld))

    assert belief_state.position == (70, 80)
    assert belief_state.room == Room.MORTAL_REALM


def test_overworld_without_self_position_preserves_existing_position() -> None:
    """Overworld frames without localization do not erase the last known position."""
    belief_state = BeliefState(position=(10, 10))

    _apply(
        belief_state,
        _frame(View.PLAYING, overworld=OverworldPerception()),
    )

    assert belief_state.position == (10, 10)


def test_overworld_speech_bubble_updates_player_position() -> None:
    """Speech bubbles identify player position and whisper availability."""
    belief_state = BeliefState(player_count=10, room_size=(200, 200))
    overworld = OverworldPerception(
        self_position=Position(room=Room.UNDERWORLD, x=80, y=90),
        speech_bubbles=[
            SpeechBubble(
                screen_x=20,
                screen_y=30,
                player_color=_color(2),
                player_shape=_shape(2),
            )
        ],
    )

    _apply(belief_state, _frame(View.PLAYING, overworld=overworld))

    assert belief_state.players[2].position == (36, 56, 1)
    assert belief_state.players[2].last_seen_in_whisper == 1


def test_overworld_visible_player_updates_position_without_whisper() -> None:
    """Plain visible sprites identify player position without whisper state."""
    belief_state = BeliefState(player_count=10, room_size=(200, 200))
    overworld = OverworldPerception(
        self_position=Position(room=Room.UNDERWORLD, x=80, y=90),
        visible_players=[
            VisiblePlayer(
                screen_x=20,
                screen_y=30,
                player_color=_color(2),
                player_shape=_shape(2),
            )
        ],
    )

    _apply(belief_state, _frame(View.PLAYING, overworld=overworld))

    assert belief_state.players[2].position == (36, 56, 1)
    assert belief_state.players[2].last_seen_in_whisper is None


def test_overworld_visible_player_updates_role_indicator() -> None:
    """Visible role indicators become mechanical game-display knowledge."""
    belief_state = BeliefState(player_count=10, room_size=(200, 200))
    overworld = OverworldPerception(
        self_position=Position(room=Room.UNDERWORLD, x=80, y=90),
        visible_players=[
            VisiblePlayer(
                screen_x=20,
                screen_y=30,
                player_color=_color(0),
                player_shape=_shape(0),
                role_indicator=RoleIndicator(team="shades", role="hades"),
            )
        ],
    )

    _apply(belief_state, _frame(View.PLAYING, overworld=overworld))

    assert belief_state.players[0].role == "hades"
    assert belief_state.players[0].team == "shades"
    assert belief_state.players[0].role_source == KnowledgeSource.GAME_DISPLAY
    assert belief_state.players[0].team_source == KnowledgeSource.GAME_DISPLAY


def test_overworld_minimap_sightings_appended() -> None:
    """Overworld minimap appends non-self sightings and skips self dots."""
    belief_state = BeliefState()
    overworld = OverworldPerception(
        minimap_dots=[
            MinimapDot(
                color=2,
                minimap_x=1,
                minimap_y=2,
                world_x=10,
                world_y=20,
                is_self=True,
            ),
            MinimapDot(
                color=_color(1),
                minimap_x=3,
                minimap_y=4,
                world_x=30,
                world_y=40,
                is_self=False,
            ),
        ]
    )

    _apply(belief_state, _frame(View.PLAYING, overworld=overworld))

    assert len(belief_state.minimap_sightings) == 1
    assert belief_state.minimap_sightings[0].color == _color(1)
    assert belief_state.minimap_sightings[0].position == (30, 40)
    assert belief_state.minimap_sightings[0].tick == 1


def test_overworld_shout_dedup() -> None:
    """Repeated shout text in consecutive frames is recorded once."""
    belief_state = BeliefState()

    _apply(
        belief_state,
        _frame(
            View.PLAYING,
            overworld=OverworldPerception(last_shout="hello room"),
        ),
    )
    _apply(
        belief_state,
        _frame(
            View.PLAYING,
            overworld=OverworldPerception(last_shout="hello room"),
        ),
    )

    assert len(belief_state.chat_history) == 1
    assert belief_state.chat_history[0].channel == "shout"


def test_overworld_shout_appends_new_text() -> None:
    """A changed shout strip text appends a new shout record."""
    belief_state = BeliefState()

    _apply(
        belief_state,
        _frame(View.PLAYING, overworld=OverworldPerception(last_shout="one")),
    )
    _apply(
        belief_state,
        _frame(View.PLAYING, overworld=OverworldPerception(last_shout="two")),
    )

    assert [record.text for record in belief_state.chat_history] == [
        "one",
        "two",
    ]


def test_overworld_is_leader_and_leader_color() -> None:
    """Overworld leader HUD updates self leadership and leader color."""
    belief_state = BeliefState(my_room=Room.UNDERWORLD)
    overworld = OverworldPerception(is_leader=True, role_team_color=14)

    _apply(belief_state, _frame(View.PLAYING, overworld=overworld))

    assert belief_state.is_leader is True
    assert belief_state.leader_colors[Room.UNDERWORLD] == 14


def test_overworld_hostage_selections_passed_through_when_leader() -> None:
    """HostageSelect stores the hostage grid while leader selection is active."""
    belief_state = BeliefState()
    grid = HostageGrid(
        eligible_colors=[_color(1)],
        eligible_shapes=[_shape(1)],
        selected_positions=[0],
    )
    overworld = OverworldPerception(
        is_leader_selecting=True,
        hostage_grid=grid,
    )

    _apply(belief_state, _frame(View.HOSTAGE_SELECT, overworld=overworld))

    assert belief_state.hostage_selections is grid


def test_whisper_occupants_decoded() -> None:
    """Whisper occupants include only fully decoded color-shape pairs."""
    belief_state = BeliefState(player_count=10)
    chatroom = ChatroomPerception(
        occupant_colors=[_color(0), _color(9), _color(2)],
        occupant_shapes=[_shape(0), _shape(9), None],
    )

    _apply(belief_state, _frame(View.WHISPER, chatroom=chatroom))

    assert belief_state.whisper_occupants == [0, 9]


def test_whisper_without_chatroom_marks_view_without_crashing() -> None:
    """A WHISPER frame with no decoded chatroom payload still tracks the view."""
    belief_state = BeliefState()

    _apply(belief_state, _frame(View.WHISPER, chatroom=None))

    assert belief_state.view == View.WHISPER
    assert belief_state.in_whisper is True
    assert belief_state.whisper_occupants == []


def test_whisper_unrecognized_color_shape_pairs_are_skipped() -> None:
    """Unrecognized chatroom sprite pairs are ignored instead of crashing."""
    belief_state = BeliefState(player_count=10)
    chatroom = ChatroomPerception(
        occupant_colors=[99],
        occupant_shapes=[_shape(0)],
        has_pending_entry=True,
        pending_entry_color=99,
        pending_entry_shape=_shape(0),
        messages=[
            ChatMessage(
                sender_color=99,
                sender_shape=_shape(0),
                is_system=False,
                text="unknown sender",
                y_position=40,
            )
        ],
    )

    _apply(belief_state, _frame(View.WHISPER, chatroom=chatroom))

    assert belief_state.whisper_occupants == []
    assert belief_state.pending_entry is None
    assert belief_state.chat_history[0].sender_index is None


def test_whisper_chat_history_appends_with_occupants_tag() -> None:
    """Whisper messages record sender and current occupant context."""
    belief_state = BeliefState(player_count=10)
    chatroom = ChatroomPerception(
        occupant_colors=[_color(0)],
        occupant_shapes=[_shape(0)],
        messages=[
            ChatMessage(
                sender_color=_color(0),
                sender_shape=_shape(0),
                is_system=False,
                text="trust me",
                y_position=40,
            )
        ],
    )

    _apply(belief_state, _frame(View.WHISPER, chatroom=chatroom))

    assert belief_state.chat_history == [
        ChatMessageRecord(
            sender_index=0,
            tick=1,
            channel="whisper",
            text="trust me",
            occupants=[0],
        )
    ]


def test_whisper_chat_history_dedup() -> None:
    """Repeated whisper messages with the same sender and text are deduped."""
    belief_state = BeliefState(player_count=10)
    message = ChatMessage(
        sender_color=_color(0),
        sender_shape=_shape(0),
        is_system=False,
        text="same",
        y_position=40,
    )
    chatroom = ChatroomPerception(messages=[message])

    _apply(belief_state, _frame(View.WHISPER, chatroom=chatroom))
    _apply(belief_state, _frame(View.WHISPER, chatroom=chatroom))

    assert len(belief_state.chat_history) == 1


def test_whisper_pending_offers_and_entry() -> None:
    """Whisper pending offers and entry request are copied from chatroom UI."""
    belief_state = BeliefState(player_count=10)
    chatroom = ChatroomPerception(
        pending_role_offer=True,
        pending_color_offer=False,
        has_pending_entry=True,
        pending_entry_color=_color(9),
        pending_entry_shape=_shape(9),
    )

    _apply(belief_state, _frame(View.WHISPER, chatroom=chatroom))

    assert belief_state.pending_offers == {"role": True, "color": False}
    assert belief_state.pending_entry == 9


def test_whisper_menu_state_built() -> None:
    """Whisper menu state captures the bottom-bar parser fields."""
    belief_state = BeliefState()
    chatroom = ChatroomPerception(
        bottom_bar=ChatroomBarState.MENU,
        menu_category="ROLE",
        menu_item="OFFER",
        menu_enabled=True,
        target_mode="color",
        target_colors=[3, 14],
    )

    _apply(belief_state, _frame(View.WHISPER, chatroom=chatroom))

    assert belief_state.menu_state == {
        "bar": ChatroomBarState.MENU,
        "category": "ROLE",
        "item": "OFFER",
        "enabled": True,
        "target_mode": "color",
        "target_colors": [3, 14],
    }


def test_global_chat_messages_appended() -> None:
    """Global chat messages append with global channel and no occupants."""
    belief_state = BeliefState(player_count=10)
    global_chat = GlobalChatPerception(
        messages=[
            ChatMessage(
                sender_color=_color(2),
                sender_shape=_shape(2),
                is_system=False,
                text="global hello",
                y_position=60,
            )
        ]
    )

    _apply(belief_state, _frame(View.GLOBAL_CHAT, global_chat=global_chat))

    record = belief_state.chat_history[0]
    assert record.sender_index == 2
    assert record.channel == "global"
    assert record.text == "global hello"
    assert record.occupants is None


def test_info_screen_updates_role_and_team() -> None:
    """Info screen known players update game-display role and team fields."""
    belief_state = BeliefState(player_count=10)
    info_screen = InfoScreenPerception(
        known_players=[
            KnownPlayer(
                color=_color(0),
                shape=_shape(0),
                role_name="hades",
                team_color=3,
                is_self=True,
                color_only=False,
            ),
            KnownPlayer(
                color=_color(2),
                shape=_shape(2),
                role_name="demeter",
                team_color=14,
                is_self=False,
                color_only=False,
            ),
        ]
    )

    _apply(belief_state, _frame(View.INFO_SCREEN, info_screen=info_screen))

    assert 0 not in belief_state.players
    player = belief_state.players[2]
    assert player.role == "demeter"
    assert player.role_source == KnowledgeSource.GAME_DISPLAY
    assert player.team == "nymphs"
    assert player.team_source == KnowledgeSource.GAME_DISPLAY


def test_info_screen_skips_color_only_entries_for_role() -> None:
    """Color-only info entries do not set role but may still set team."""
    belief_state = BeliefState(player_count=10)
    info_screen = InfoScreenPerception(
        known_players=[
            KnownPlayer(
                color=_color(2),
                shape=_shape(2),
                role_name="demeter",
                team_color=3,
                is_self=False,
                color_only=True,
            )
        ]
    )

    _apply(belief_state, _frame(View.INFO_SCREEN, info_screen=info_screen))

    player = belief_state.players[2]
    assert player.role is None
    assert player.role_source is None
    assert player.team == "shades"
    assert player.team_source == KnowledgeSource.GAME_DISPLAY


def test_exchange_role_team_updates() -> None:
    """Exchange screen role indicators update player role and team."""
    belief_state = BeliefState(player_count=10)
    exchange = ExchangePerception(
        leaders=[
            ExchangePlayer(
                color=_color(2),
                shape=_shape(2),
                role_indicator=RoleIndicator(team="shades", role="hades"),
            )
        ]
    )

    _apply(belief_state, _frame(View.HOSTAGE_EXCHANGE, exchange=exchange))

    player = belief_state.players[2]
    assert player.role == "hades"
    assert player.role_source == KnowledgeSource.GAME_DISPLAY
    assert player.team == "shades"
    assert player.team_source == KnowledgeSource.GAME_DISPLAY


def test_exchange_room_reassignment_for_hostages() -> None:
    """Departing hostages move to the other room and arrivals to our room."""
    belief_state = BeliefState(
        player_count=10,
        my_room=Room.UNDERWORLD,
    )
    exchange = ExchangePerception(
        departing=[ExchangePlayer(color=_color(2), shape=_shape(2))],
        arriving=[ExchangePlayer(color=_color(3), shape=_shape(3))],
    )

    _apply(belief_state, _frame(View.HOSTAGE_EXCHANGE, exchange=exchange))

    assert belief_state.players[2].room == Room.MORTAL_REALM
    assert belief_state.players[3].room == Room.UNDERWORLD


def test_reveal_winner_lowercased() -> None:
    """Reveal/GameOver winner strings are stored lowercase."""
    belief_state = BeliefState()

    _apply(
        belief_state,
        _frame(
            View.REVEAL,
            result=ResultPerception(winner="Shades"),
        ),
    )

    assert belief_state.winner == "shades"


def test_decode_player_index_unique() -> None:
    """Player color-shape pairs decode uniquely across the 24-index space."""
    seen_pairs = set()
    for index in range(24):
        pair = (_color(index), _shape(index))
        seen_pairs.add(pair)
        assert belief_update.decode_player_index(*pair, None) == index

    assert len(seen_pairs) == 24
    assert belief_update.decode_player_index(_color(0), None, None) is None
    assert belief_update.decode_player_index(99, _shape(0), None) is None
    assert belief_update.decode_player_index(_color(17), _shape(17), 10) is None


def test_team_color_mapping() -> None:
    """Team palette colors map to canonical lowercase team names."""
    assert belief_update.team_color_to_name(3) == "shades"
    assert belief_update.team_color_to_name(14) == "nymphs"
    assert belief_update.team_color_to_name(None) is None
    assert belief_update.team_color_to_name(8) is None


def test_room_string_to_enum() -> None:
    """Room strings normalize to Room enum values."""
    assert belief_update.room_string_to_enum("Underworld") == Room.UNDERWORLD
    assert belief_update.room_string_to_enum("underworld") == Room.UNDERWORLD
    assert (
        belief_update.room_string_to_enum("Mortal Realm")
        == Room.MORTAL_REALM
    )
    assert (
        belief_update.room_string_to_enum("mortal_realm")
        == Room.MORTAL_REALM
    )
    assert belief_update.room_string_to_enum(None) is None
    assert belief_update.room_string_to_enum("Olympus") is None


def test_global_chat_updates_leader_color_and_hostage_grid() -> None:
    """Global chat tracks visible leader candidate and leader hostage grid."""
    belief_state = BeliefState(room=Room.UNDERWORLD, is_leader=True)
    grid = HostageGrid(selected_colors=[_color(1)])
    global_chat = GlobalChatPerception(
        usurp_candidate=UsurpCandidate(player_color=_color(3)),
        hostage_grid=grid,
    )

    _apply(belief_state, _frame(View.GLOBAL_CHAT, global_chat=global_chat))

    assert belief_state.leader_colors[Room.UNDERWORLD] == _color(3)
    assert belief_state.hostage_selections is grid


def test_pipeline_calls_belief_update_apply() -> None:
    """Pipeline delegates belief updates through the Stage 2 module."""
    send_input = MagicMock()
    pipeline = Pipeline(
        initial_mode=IdleMode(),
        mode_registry=ModeRegistry(),
        send_input=send_input,
        send_chat=MagicMock(),
    )
    frame = np.zeros((128, 128), dtype=np.uint8)
    perception = _frame(
        View.LOBBY,
        lobby=LobbyPerception(player_count=10),
    )

    with patch("orpheus.pipeline.parse_frame", return_value=perception):
        with patch(
            "orpheus.pipeline.belief_update.apply",
            wraps=belief_update.apply,
        ) as apply_mock:
            pipeline.tick(frame)

    apply_mock.assert_called_once()
    assert apply_mock.call_args.args[2] == View.UNKNOWN
    assert pipeline.belief_state.tick == 1
    assert pipeline.belief_state.player_count == 10
    send_input.assert_called_once_with(0)
