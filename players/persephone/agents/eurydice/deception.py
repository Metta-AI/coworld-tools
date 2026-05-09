"""Deception state and Spy cover logic for Eurydice."""

from __future__ import annotations

from dataclasses import dataclass, field

from orpheus.logging import LogLevel

from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.types import PlayerID, Role, RoleSource, Team, Urgency

from .log import logger


@dataclass
class LieRecord:
    """One lie told to a specific player."""

    tick: int = 0
    target_id: PlayerID | None = None
    claim: str = ""
    channel: str = ""  # "global" | "whisper"


@dataclass
class DeceptionState:
    """Tracks what identity we're projecting and who we've deceived."""

    projected_role: Role | None = None
    projected_team: Team | None = None
    target_audience: set[PlayerID] = field(default_factory=set)
    lies_told: list[LieRecord] = field(default_factory=list)
    cover_consistent: bool = True
    cover_blown_logged: bool = False


def should_deceive(
    my_role: Role | None,
    target_knowledge: PlayerKnowledge | None,
    urgency: Urgency,
) -> bool:
    """Return whether deception is worth using for the current interaction."""

    del target_knowledge  # Reserved for later target-specific risk checks.

    if my_role in {Role.SHADE, Role.NYMPH, Role.SPY}:
        decision, reason = True, "grunt_or_spy_role"
    elif my_role in {Role.HADES, Role.PERSEPHONE}:
        decision = urgency is Urgency.PANIC
        reason = "primary_key_role_panic" if decision else "primary_key_role_not_panic"
    elif my_role in {Role.CERBERUS, Role.DEMETER}:
        decision = urgency in {Urgency.PRESSING, Urgency.PANIC}
        reason = "partner_key_role_urgent" if decision else "partner_key_role_calm"
    else:
        decision, reason = False, "unknown_or_non_deceptive_role"

    if logger:
        logger.event(
            "deception_decision",
            {"should_deceive": decision, "reason": reason},
            LogLevel.DECISIONS,
        )
    return decision


def record_lie(
    state: DeceptionState,
    target_id: PlayerID | None,
    claim: str,
    channel: str,
    tick: int,
) -> None:
    """Record a lie and mark the target as part of our deceived audience."""

    consistent = check_consistency(state, claim, target_id)
    if not consistent:
        state.cover_consistent = False

    state.lies_told.append(
        LieRecord(
            tick=tick,
            target_id=target_id,
            claim=claim,
            channel=channel,
        )
    )
    if target_id is not None:
        state.target_audience.add(target_id)

    if logger:
        logger.event(
            "lie_recorded",
            {
                "target": _player_id_value(target_id),
                "lie_type": _lie_type(claim),
                "content": claim,
                "consistent": consistent,
            },
            LogLevel.DECISIONS,
        )


def check_consistency(
    state: DeceptionState,
    new_claim: str,
    target_id: PlayerID | None,
) -> bool:
    """Return False when a target has already heard a different claim.

    Lie records are intentionally string-based at this stage. We normalize
    spacing, case, and basic sentence punctuation so harmless formatting
    differences do not count as contradictions.
    """

    normalized_claim = _normalize_claim(new_claim)
    for lie in state.lies_told:
        if not _claim_applies_to_target(lie, target_id):
            continue
        if _normalize_claim(lie.claim) != normalized_claim:
            return False
    return True


def get_cover_team(my_role: Role | None, my_team: Team | None) -> Team | None:
    """Return the Spy's opposite-team cover, or None for honest roles."""

    if my_role is not Role.SPY:
        return None
    if my_team is Team.SHADES:
        return Team.NYMPHS
    if my_team is Team.NYMPHS:
        return Team.SHADES
    return None


def is_cover_blown(
    deception_state: DeceptionState,
    knowledge_base: dict[PlayerID, PlayerKnowledge] | None,
) -> bool:
    """Return whether our cover should be treated as blown.

    Other players' private knowledge is not directly observable, so this
    stage uses the local consistency flag as the operational signal. The
    knowledge base is accepted for the future mechanically verified path.
    """

    del knowledge_base
    blown = not deception_state.cover_consistent
    if blown and not deception_state.cover_blown_logged:
        deception_state.cover_blown_logged = True
        if logger:
            logger.event(
                "cover_blown",
                {"reason": "inconsistent_lie_record"},
                LogLevel.DECISIONS,
            )
    return blown


def spy_should_accept_role_exchange(
    offerer_knowledge: PlayerKnowledge | None,
    my_team: Team | None,
    verified_ally: PlayerID | None,
    urgency: Urgency,
) -> bool:
    """Decide whether a Spy should accept an incoming role exchange offer."""

    if offerer_knowledge is None:
        return False

    offerer_id = offerer_knowledge.player_id
    if verified_ally is not None and offerer_id == verified_ally:
        return True

    offerer_team = offerer_knowledge.team
    if offerer_team is None or my_team is None:
        return False
    if offerer_team is not my_team:
        return False
    return urgency is Urgency.PANIC


def _normalize_claim(claim: str) -> str:
    """Normalize a claim for conservative consistency comparisons."""

    text = claim.strip().upper()
    for char in ".,!?;:":
        text = text.replace(char, "")
    return " ".join(text.split())


def _claim_applies_to_target(lie: LieRecord, target_id: PlayerID | None) -> bool:
    """Return whether a past lie is relevant to a new target-specific claim."""

    if lie.target_id is None:
        return True
    if target_id is None:
        return True
    return lie.target_id == target_id


def _lie_type(claim: str) -> str:
    text = _normalize_claim(claim)
    role_names = {role.name for role in Role}
    if any(role_name in text for role_name in role_names):
        return "role"
    if "SHADES" in text or "NYMPHS" in text:
        return "team"
    if "I AM" in text or "IM " in text or text.startswith("IM"):
        return "identity"
    return "statement"


def _player_id_value(player_id: PlayerID | None) -> list[int] | None:
    if player_id is None:
        return None
    return [int(player_id[0]), int(player_id[1])]
