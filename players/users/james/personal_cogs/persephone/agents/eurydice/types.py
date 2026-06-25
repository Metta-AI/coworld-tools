"""Eurydice-specific enums, type aliases, and constants."""
from __future__ import annotations
from enum import Enum, auto
from typing import TypeAlias

# Import Room from Orpheus perception (already defined there)
from orpheus.perception.types import Room

# PlayerID: visual identity of a player (color index 0-15, shape enum value)
PlayerID: TypeAlias = tuple[int, int]


class Team(Enum):
    SHADES = auto()
    NYMPHS = auto()


class Role(Enum):
    HADES = auto()
    CERBERUS = auto()
    SHADE = auto()       # Shades grunt
    PERSEPHONE = auto()
    DEMETER = auto()
    NYMPH = auto()       # Nymphs grunt
    SPY = auto()


class TrustLevel(Enum):
    VERIFIED = auto()    # Mutual role exchange confirmed
    PROBABLE = auto()    # Color exchange or strong inference
    UNCERTAIN = auto()   # Weak inference or unverified claim
    HOSTILE = auto()     # Confirmed enemy team


class Urgency(Enum):
    CALM = auto()
    PRESSING = auto()
    PANIC = auto()


class ProbeIntent(Enum):
    ROLE_EXCHANGE = auto()
    FIND_KEY_PARTNER = auto()
    LOCATE_ENEMY_KEY = auto()
    VERIFY_SELF_AS_SPY = auto()
    GENERAL = auto()
    MAP_ROOM = auto()
    DISRUPT = auto()
    LOCATE_HADES = auto()


class TeamSource(Enum):
    COLOR_EXCHANGE = auto()
    ROLE_EXCHANGE = auto()
    INFERRED = auto()
    NONE = auto()


class RoleSource(Enum):
    ROLE_EXCHANGE = auto()
    ONE_WAY_REVEAL = auto()
    INFERRED = auto()
    CHAT_CLAIM = auto()
    NONE = auto()


class Phase(Enum):
    """Game phases (extends Orpheus view-based phase detection)."""
    LOBBY = auto()
    ROSTER_REVEAL = auto()
    ROLE_REVEAL = auto()
    PLAYING = auto()
    HOSTAGE_SELECT = auto()
    LEADER_SUMMIT = auto()
    HOSTAGE_EXCHANGE = auto()
    REVEAL = auto()
    GAME_OVER = auto()


class Objective(Enum):
    """High-level strategic objectives."""
    FIND_KEY_PARTNER = auto()
    COMPLETE_KEY_EXCHANGE = auto()
    LOCATE_ENEMY_KEY = auto()
    POSITION_FOR_WIN = auto()
    PROTECT_KEY_ROLE = auto()
    DISRUPT_ENEMY = auto()
    GATHER_INTEL = auto()
    MAINTAIN_COVER = auto()  # Spy
    IDLE = auto()


# Interaction range: 20px (BUBBLE_RADIUS from server constants.ts)
INTERACTION_RANGE: int = 20
INTERACTION_RANGE_SQ: int = INTERACTION_RANGE ** 2

# Whisper protocol timeouts (ticks)
# key_exchange was 96 (4s); live traces showed key-pair joins exiting on
# protocol_timeout / role_exchange_timeout before either side could complete
# the menu sequence and have the server confirm shared_roles. Bumped to 288
# (12 s) so the in-whisper handshake actually has room to land.
PROTOCOL_TIMEOUTS: dict[str, int] = {
    "standard": 240,      # 10 seconds
    "key_exchange": 288,  # 12 seconds
    "infiltration": 240,  # 10 seconds
    "stall": 288,         # 12 seconds
    "quick_verify": 144,  # 6 seconds
}
