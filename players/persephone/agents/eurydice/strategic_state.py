"""Strategic state snapshots derived from Eurydice's knowledge base."""

from __future__ import annotations

from dataclasses import dataclass, field

from orpheus.perception.types import Room

from .types import Objective, Phase, PlayerID, Role, Team, Urgency


@dataclass
class IntelItem:
    """A shareable piece of strategic information with provenance strength."""

    subject_id: PlayerID | None = None
    intel_type: str = ""
    content: str = ""
    confidence: float = 0.0
    tick_acquired: int = 0


@dataclass
class StrategicState:
    """Mutable per-decision strategic summary used by Eurydice modes."""

    my_role: Role | None = None
    my_team: Team | None = None
    my_room: Room | None = None
    my_player_id: PlayerID | None = None
    current_round: int = 0
    current_phase: Phase = Phase.LOBBY
    round_start_tick: int = 0
    ticks_remaining_in_phase: int = 0
    urgency: Urgency = Urgency.CALM
    key_exchange_done: bool = False
    key_partner_found: bool = False
    key_partner_id: PlayerID | None = None
    key_partner_room: Room | None = None
    enemy_key_exchange_done: bool | None = None
    enemy_key_exchange_likely: bool = False
    enemy_key_role_id: PlayerID | None = None
    enemy_key_role_room: Room | None = None
    players_in_my_room: list[PlayerID] = field(default_factory=list)
    players_in_other_room: list[PlayerID] = field(default_factory=list)
    players_room_unknown: list[PlayerID] = field(default_factory=list)
    allies_in_my_room: list[PlayerID] = field(default_factory=list)
    enemies_in_my_room: list[PlayerID] = field(default_factory=list)
    am_leader: bool = False
    room_leader_id: PlayerID | None = None
    room_leader_team: Team | None = None
    met_other_leader_in_summit: bool = False
    other_leader_team: Team | None = None
    players_probed_this_round: list[PlayerID] = field(default_factory=list)
    players_unprobed_in_room: list[PlayerID] = field(default_factory=list)
    probe_cycles_remaining: int = 0
    room_player_count: int = 0
    total_player_count: int = 0
    usurp_votes_needed: int = 0
    probe_coverage_fraction: float = 0.0
    local_intel_to_share: list[IntelItem] = field(default_factory=list)
    intel_for_summit: list[IntelItem] = field(default_factory=list)
    cover_intact: bool = True
    cover_identity: Team | None = None
    verified_ally: PlayerID | None = None
    current_objective: Objective = Objective.IDLE
    mode_entered_tick: int = 0
    consecutive_idle_ticks: int = 0
    round_schedule: list[int] = field(default_factory=list)
    match_roles: list[str] = field(default_factory=list)
    missing_roles: list[str] = field(default_factory=list)
    echo_substitutions: list[tuple[str, str]] = field(default_factory=list)
    spy_in_game_config: bool | None = None
