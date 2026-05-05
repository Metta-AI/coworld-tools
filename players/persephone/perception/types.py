"""Type definitions for the perception module.

All dataclasses and enums used in FramePerception output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class View(Enum):
    """Which view/phase is currently displayed in the frame."""

    ROLE_REVEAL = "role_reveal"
    LOBBY = "lobby"
    PLAYING = "playing"
    HOSTAGE_SELECT = "hostage_select"
    LEADER_SUMMIT = "leader_summit"
    HOSTAGE_EXCHANGE = "hostage_exchange"
    WHISPER = "whisper"
    WAITING_ENTRY = "waiting_entry"
    GLOBAL_CHAT = "global_chat"
    INFO_SCREEN = "info_screen"
    REVEAL = "reveal"
    GAME_OVER = "game_over"
    UNKNOWN = "unknown"


class Room(Enum):
    """Which room the player is in."""

    UNDERWORLD = "underworld"  # RoomA, floor color 12
    MORTAL_REALM = "mortal_realm"  # RoomB, floor color 9


class BottomBarState(Enum):
    """State of the overworld bottom bar."""

    DEFAULT = "default"  # "J:CHAT  K:INFO  L:MENU"
    WAITING = "waiting"  # "WAITING..."
    COMM_MENU = "comm_menu"  # "< SHOUT >" or "< INFO >"


class ChatroomBarState(Enum):
    """State of the chatroom bottom bar."""

    DEFAULT = "default"  # "L:EXIT  K:ACTIONS  ENTER:MSG"
    MENU = "menu"  # "(CATEGORY) ACTION"
    TARGET_PICKER = "target"  # "COLOR: [sprites]" or "ROLE: [sprites]"


class InfoMode(Enum):
    """Sub-mode of the info screen."""

    ROLE = "role"
    SHARED = "shared"


class PlayerShape(Enum):
    """The 12 player sprite shapes."""

    CIRCLE = 0
    SQUARE = 1
    TRIANGLE = 2
    DIAMOND = 3
    STAR = 4
    CROSS = 5
    X_SHAPE = 6
    HEART = 7
    CRESCENT = 8
    BOLT = 9
    HOURGLASS = 10
    RING = 11


# ---------------------------------------------------------------------------
# Component dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MinimapDot:
    """A single dot detected on the minimap."""

    color: int  # Palette index (0-15)
    minimap_x: int  # 0-19 position within minimap
    minimap_y: int  # 0-19
    world_x: int  # Estimated world pixel coordinate
    world_y: int  # Estimated world pixel coordinate
    is_self: bool  # True if color == 2 (self dot)


@dataclass
class Position:
    """Estimated world position of the viewer."""

    room: Room
    x: int  # World pixel x
    y: int  # World pixel y


@dataclass
class SpeechBubble:
    """A speech bubble detected above a player sprite in the overworld."""

    screen_x: int  # Top-left x of the player sprite (not the bubble)
    screen_y: int  # Top-left y of the player sprite
    player_color: int  # Color read from sprite center pixel


@dataclass
class OverworldBottomBar:
    """Parsed state of the overworld bottom bar."""

    state: BottomBarState
    comm_menu_item: str | None = None  # Current item text if comm menu open
    has_unread_global: bool = False  # Green dot at (124, 123)


@dataclass
class ChatMessage:
    """A single visible chat message line."""

    sender_color: int | None  # Player color (None for system messages)
    is_system: bool  # True if rendered in color 8
    text: str  # OCR'd text content (best-effort)
    y_position: int  # Screen y where this message is drawn


@dataclass
class RoleIndicator:
    """Parsed role indicator bar (5x2 pixels below a sprite)."""

    team: str  # "shades" or "nymphs"
    role: str  # "hades", "cerberus", "shade", "persephone", "demeter", "nymph"


@dataclass
class KnownPlayer:
    """A player entry from the info screen."""

    color: int  # Player's palette color
    role_name: str | None  # Role name if fully revealed
    team_color: int | None  # Team color from indicator or dot
    is_self: bool  # First entry is always self
    color_only: bool  # True if "???" shown (color exchange only)


@dataclass
class UsurpCandidate:
    """Current usurp candidate shown in the global chat selector."""

    text: str | None = None  # "NONE", "ME", or None if showing a sprite
    player_color: int | None = None  # Player color if showing a sprite


@dataclass
class HostageGrid:
    """Hostage selection grid visible to leaders during HostageSelect."""

    eligible_colors: list[int] = field(default_factory=list)
    selected_colors: list[int] = field(default_factory=list)
    cursor_index: int | None = None
    count_label: str | None = None  # e.g. "1/2 HOSTAGES"
    is_committed: bool = False


@dataclass
class ExchangePlayer:
    """A player shown in the hostage exchange screen."""

    color: int  # Player color from sprite
    role_indicator: RoleIndicator | None = None


# ---------------------------------------------------------------------------
# Per-view perception dataclasses
# ---------------------------------------------------------------------------


@dataclass
class OverworldPerception:
    """Symbolic data extracted from the overworld view."""

    # HUD
    round: int | None = None  # 1-indexed round number
    timer_secs: int | None = None  # Seconds remaining
    role_name: str | None = None  # Own role name from top bar
    role_team_color: int | None = None  # Palette index of role text (3 or 14)

    # Phase-specific (HostageSelect)
    hostage_select_secs: int | None = None
    is_leader_selecting: bool = False

    # Minimap
    minimap_dots: list[MinimapDot] = field(default_factory=list)

    # Position
    self_position: Position | None = None

    # Room
    room: Room | None = None

    # Shout strip (Playing only)
    last_shout: str | None = None
    last_shout_color: int | None = None

    # Bottom bar
    bottom_bar: OverworldBottomBar = field(
        default_factory=lambda: OverworldBottomBar(state=BottomBarState.DEFAULT)
    )

    # Nearby indicators
    speech_bubbles: list[SpeechBubble] = field(default_factory=list)


@dataclass
class ChatroomPerception:
    """Symbolic data extracted from the chatroom view."""

    occupant_colors: list[int] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)
    has_pending_entry: bool = False
    pending_entry_color: int | None = None
    bottom_bar: ChatroomBarState = ChatroomBarState.DEFAULT
    # Default bar indicators
    pending_role_offer: bool = False
    pending_color_offer: bool = False
    # Menu state
    menu_category: str | None = None
    menu_item: str | None = None
    menu_enabled: bool = False
    # Target picker
    target_mode: str | None = None
    target_colors: list[int] = field(default_factory=list)


@dataclass
class GlobalChatPerception:
    """Symbolic data extracted from the global chat view."""

    room_name: str | None = None
    usurp_candidate: UsurpCandidate | None = None
    hostage_grid: HostageGrid | None = None
    messages: list[ChatMessage] = field(default_factory=list)
    bottom_bar_text: str | None = None


@dataclass
class InfoScreenPerception:
    """Symbolic data extracted from the info screen."""

    mode: InfoMode = InfoMode.SHARED
    # "role" mode
    role_name: str | None = None
    team_name: str | None = None
    team_color: int | None = None
    # "shared" mode
    known_players: list[KnownPlayer] = field(default_factory=list)


@dataclass
class RoleRevealPerception:
    """Symbolic data extracted from the role reveal screen."""

    role: str | None = None  # e.g. "Hades"
    team: str | None = None  # "Shades" or "Nymphs"
    team_color: int | None = None  # 3 or 14
    room: str | None = None  # "Underworld" or "Mortal Realm"
    player_count: int | None = None
    room_size: int | None = None  # Room is square: NxN
    countdown_secs: int | None = None


@dataclass
class ExchangePerception:
    """Symbolic data extracted from the hostage exchange screen."""

    leaders: list[ExchangePlayer] = field(default_factory=list)
    departing: list[ExchangePlayer] = field(default_factory=list)
    arriving: list[ExchangePlayer] = field(default_factory=list)
    viewer_status: str | None = None  # "hostage", "leader", or "spectator"


@dataclass
class ResultPerception:
    """Symbolic data extracted from reveal/game over screens."""

    is_reveal: bool = False  # True = Reveal phase, False = GameOver
    winner: str | None = None  # "Shades", "Nymphs", or None (draw)
    winner_color: int | None = None  # 3, 14, or 1


@dataclass
class LobbyPerception:
    """Symbolic data extracted from the lobby view."""

    player_count: int | None = None
    max_players: int | None = None
    countdown_secs: int | None = None


# ---------------------------------------------------------------------------
# Top-level result
# ---------------------------------------------------------------------------


@dataclass
class FramePerception:
    """Complete symbolic representation of a single frame.

    Exactly one of the per-view fields is populated, determined by ``view``.
    Exception: ``WAITING_ENTRY`` also populates ``overworld`` since the game
    world is still rendered.
    """

    view: View

    overworld: OverworldPerception | None = None
    chatroom: ChatroomPerception | None = None
    global_chat: GlobalChatPerception | None = None
    info_screen: InfoScreenPerception | None = None
    role_reveal: RoleRevealPerception | None = None
    exchange: ExchangePerception | None = None
    result: ResultPerception | None = None
    lobby: LobbyPerception | None = None

    raw_pixels: np.ndarray | None = None  # (128, 128) uint8, values 0-15
