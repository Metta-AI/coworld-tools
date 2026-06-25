"""Communication dataclasses and keyword registries for Eurydice."""

from __future__ import annotations

from dataclasses import dataclass

from .types import PlayerID, Role, Team

ROLE_KEYWORDS: dict[str, Role] = {
    "HADES": Role.HADES,
    "HAD": Role.HADES,
    "PERSEPHONE": Role.PERSEPHONE,
    "PERS": Role.PERSEPHONE,
    "SEPH": Role.PERSEPHONE,
    "CERBERUS": Role.CERBERUS,
    "CERB": Role.CERBERUS,
    "DEMETER": Role.DEMETER,
    "DEM": Role.DEMETER,
    "SHADE": Role.SHADE,
    "SHADES": Role.SHADE,
    "NYMPH": Role.NYMPH,
    "NYMPHS": Role.NYMPH,
    "SPY": Role.SPY,
}

TEAM_KEYWORDS: dict[str, Team] = {
    "SHADES": Team.SHADES,
    "SHADE": Team.SHADES,
    "GREEN": Team.SHADES,
    "NYMPHS": Team.NYMPHS,
    "NYMPH": Team.NYMPHS,
    "PINK": Team.NYMPHS,
}

ACTION_KEYWORDS: dict[str, tuple[str, str | None]] = {
    "SEND ME": ("send_hostage", "self"),
    "SEND": ("send_hostage", None),
    "VOTE": ("vote_usurp", None),
    "MEET": ("meet", None),
    "EXCHANGE": ("exchange", None),
    "SWAP": ("exchange", None),
}


@dataclass
class IdentityClaim:
    """Parsed claim about a player identity."""

    claimed_role: str | None = None
    claimed_team: str | None = None
    confidence: float = 0.0
    subject: str = "self"


@dataclass
class LocationClaim:
    """Parsed claim about a player's location."""

    subject: str = ""
    location: str = ""
    confidence: float = 0.0


@dataclass
class ActionRequest:
    """Parsed request for another player or the room to take an action."""

    action_type: str = ""
    target: str | None = None
    confidence: float = 0.0


@dataclass
class Question:
    """Parsed question from chat."""

    question_type: str = ""
    subject: str | None = None


@dataclass
class ParsedMessage:
    """Structured parse result for one chat message."""

    raw_text: str = ""
    sender_id: PlayerID | None = None
    channel: str = ""
    tick: int = 0
    identity_claim: IdentityClaim | None = None
    location_claim: LocationClaim | None = None
    action_request: ActionRequest | None = None
    question: Question | None = None
    uninterpretable: bool = False
