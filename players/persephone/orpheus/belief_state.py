"""Belief-state schema for Orpheus agents."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING

from orpheus.types import KnowledgeSource, PlayerShape, Room, View

if TYPE_CHECKING:
    from orpheus.occupancy_grid import OccupancyGrid


# ---------------------------------------------------------------------------
# Player registry
# ---------------------------------------------------------------------------


@dataclass
class PlayerInfo:
    """Known information about a single player, indexed by player_index."""

    position: tuple[int, int, int] | None = None
    room: Room | None = None
    team: str | None = None
    team_source: KnowledgeSource | None = None
    role: str | None = None
    role_source: KnowledgeSource | None = None
    last_seen_in_whisper: int | None = None


# ---------------------------------------------------------------------------
# Social records
# ---------------------------------------------------------------------------


@dataclass
class ChatMessageRecord:
    """A chat message observed by the agent."""

    sender_index: int | None
    tick: int
    channel: str
    text: str
    occupants: list[int] | None = None


# ---------------------------------------------------------------------------
# Spatial records
# ---------------------------------------------------------------------------


@dataclass
class MinimapSighting:
    """A color-only minimap observation at an estimated world position."""

    color: int
    position: tuple[int, int]
    tick: int


# ---------------------------------------------------------------------------
# Belief state
# ---------------------------------------------------------------------------


@dataclass
class BeliefState:
    """Persistent fixed-schema memory shared by Orpheus modes and tasks."""

    # Self identity
    my_index: int | None = None
    my_color: int | None = None
    my_shape: PlayerShape | None = None
    my_role: str | None = None
    my_team: str | None = None
    my_room: Room | None = None

    # Timing
    tick: int = 0

    # Spatial
    position: tuple[int, int] | None = None
    room: Room | None = None
    room_size: tuple[int, int] | None = None
    occupancy_grid: OccupancyGrid | None = None

    # Player registry
    players: dict[int, PlayerInfo] = field(default_factory=dict)

    # Game state
    view: View = View.UNKNOWN
    round: int | None = None
    timer_secs: int | None = None
    player_count: int | None = None
    winner: str | None = None

    # Game schedule
    round_schedule: list[tuple[int, int]] = field(default_factory=list)

    # Action state
    cooldowns: dict[str, int] = field(default_factory=dict)

    # Chatroom state
    in_whisper: bool = False
    whisper_occupants: list[int] = field(default_factory=list)
    pending_offers: dict[str, bool] = field(
        default_factory=lambda: {"role": False, "color": False}
    )
    pending_entry: int | None = None
    menu_state: object | None = None

    # Hostage state
    hostage_selections: object | None = None

    # Social / knowledge
    chat_history: list[ChatMessageRecord] = field(default_factory=list)
    my_exchange_partner: int | None = None

    # Spatial observations
    minimap_sightings: list[MinimapSighting] = field(default_factory=list)

    # Leadership
    is_leader: bool = False
    leader_colors: dict[Room, int] = field(default_factory=dict)
    leader_last_confirmed_tick: dict[Room, int] = field(default_factory=dict)

    # Task
    current_task: object | None = None

    # Outer loop inferences
    inferences: dict = field(default_factory=dict)

    # Flexible space
    extra: dict = field(default_factory=dict)

    def reset(self) -> None:
        """Reset all fields to defaults. Used by Lobby on game restart."""
        fresh = BeliefState()
        for f in fields(self):
            setattr(self, f.name, getattr(fresh, f.name))


__all__ = [
    "BeliefState",
    "PlayerInfo",
    "ChatMessageRecord",
    "MinimapSighting",
]
