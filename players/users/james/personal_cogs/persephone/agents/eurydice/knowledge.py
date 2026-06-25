"""Per-player knowledge records maintained by Eurydice."""

from __future__ import annotations

from dataclasses import dataclass, field

from orpheus.perception.types import Room

from .types import PlayerID, Role, RoleSource, Team, TeamSource, TrustLevel


@dataclass
class PlayerKnowledge:
    """Mutable belief record for one visually identified player.

    This stores Eurydice's current best-known identity, location, exchange
    status, interaction history, and trust classification for a player.
    """

    player_id: PlayerID
    name: str | None = None
    team: Team | None = None
    team_source: TeamSource = TeamSource.NONE
    team_confidence: float = 0.0
    role: Role | None = None
    role_source: RoleSource = RoleSource.NONE
    room: Room | None = None
    room_confidence: float = 0.0
    room_last_confirmed_tick: int = 0
    last_seen_position: tuple[int, int] | None = None
    has_exchanged_colors_with_us: bool = False
    has_exchanged_roles_with_us: bool = False
    we_have_pending_offer_to: str | None = None
    they_have_pending_offer: str | None = None
    last_interaction_tick: int = 0
    last_interaction_round: int = 0
    times_interacted: int = 0
    behavioral_flags: set[str] = field(default_factory=set)
    refused_role_exchange: bool = False
    exchange_eagerness: float = 0.0
    is_leader: bool = False
    was_leader_round: list[int] = field(default_factory=list)
    probable_whisper_partners: list[tuple[PlayerID, float]] = field(default_factory=list)
    claims_made: list[str] = field(default_factory=list)
    claims_about_identity: str | None = None
    we_claimed_to_be: str | None = None
    we_showed_color: bool = False
    we_showed_role: bool = False
    trust_level: TrustLevel = TrustLevel.UNCERTAIN

    @classmethod
    def create(cls, player_id: PlayerID) -> PlayerKnowledge:
        """Create a fresh knowledge record for ``player_id`` with defaults."""

        return cls(player_id=player_id)
