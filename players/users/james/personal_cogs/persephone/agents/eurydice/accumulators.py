"""Long-lived behavioral accumulators for Eurydice."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .types import PlayerID


@dataclass
class WhisperRecord:
    """A record of one whisper session involving Eurydice."""

    tick_entered: int = 0
    tick_exited: int | None = None
    occupants: list[PlayerID] = field(default_factory=list)
    exchanges_completed: list[str] = field(default_factory=list)
    protocol: str = ""


@dataclass
class PlayerAccumulator:
    """Cross-tick behavioral counters and histories for one player."""

    player_id: PlayerID
    position_history: deque[tuple[int, int, int]] = field(
        default_factory=lambda: deque(maxlen=120)
    )
    visible_ticks_this_round: int = 0
    stationary_ticks: int = 0
    not_visible_since: int | None = None
    total_distance_this_round: float = 0.0
    distinct_players_approached: set[PlayerID] = field(default_factory=set)
    whisper_entries_this_round: int = 0
    whisper_partners_this_round: set[PlayerID] = field(default_factory=set)
    total_time_in_whispers_ticks: int = 0
    whisper_entry_ticks: list[int] = field(default_factory=list)
    max_whisper_entries_any_round: int = 0
    color_offers_made: int = 0
    color_offers_received_and_accepted: int = 0
    role_offers_made: int = 0
    role_offers_received_and_declined: int = 0
    role_offers_received_and_accepted: int = 0
    ticks_before_first_offer: int | None = None
    global_messages_sent_this_round: int = 0
    whisper_messages_sent: int = 0
    message_content_log: list[tuple[int, str]] = field(default_factory=list)
    sought_leadership: bool = False
    passed_leadership: bool = False
    leadership_rounds: list[int] = field(default_factory=list)

    def reset_for_new_round(self) -> None:
        """Reset round-local counters while preserving cross-round evidence."""

        self.max_whisper_entries_any_round = max(
            self.max_whisper_entries_any_round,
            self.whisper_entries_this_round,
        )
        self.whisper_entries_this_round = 0
        self.whisper_partners_this_round = set()
        self.visible_ticks_this_round = 0
        self.total_distance_this_round = 0.0
        self.global_messages_sent_this_round = 0
        self.stationary_ticks = 0
        self.distinct_players_approached = set()


@dataclass
class GlobalAccumulators:
    """Container for Eurydice's game-lifetime behavioral accumulators."""

    player_accumulators: dict[PlayerID, PlayerAccumulator] = field(default_factory=dict)
    current_round: int = 0
    round_start_tick: int = 0
    our_whisper_history: list[WhisperRecord] = field(default_factory=list)
    our_probe_cycles_this_round: int = 0
