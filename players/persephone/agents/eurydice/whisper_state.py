"""State objects for Eurydice whisper exchange protocols."""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import PlayerID


@dataclass
class WhisperExchangeState:
    """Low-level exchange state derived from active whisper UI signals."""

    active_color_offers: set[PlayerID] = field(default_factory=set)
    color_exchange_completed: bool = False
    active_role_offers: set[PlayerID] = field(default_factory=set)
    role_exchange_completed: bool = False
    one_way_reveal: PlayerID | None = None
    leadership_offer_pending: bool = False
    last_system_message_tick: int = 0


@dataclass
class WhisperModeState:
    """Finite-state machine state for a single Eurydice whisper interaction."""

    protocol: str = "standard"
    fsm_state: str = "ENTER"
    entered_tick: int = 0
    occupants_at_entry: list[PlayerID] = field(default_factory=list)
    target_occupant: PlayerID | None = None
    hostile_present: bool = False
    color_exchange_initiated: bool = False
    color_exchange_completed: bool = False
    role_exchange_initiated: bool = False
    role_exchange_completed: bool = False
    waiting_for_response_since: int = 0
    messages_sent: int = 0
    exit_initiated: bool = False
