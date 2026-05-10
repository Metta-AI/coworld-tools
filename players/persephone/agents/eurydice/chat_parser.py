"""Keyword-based chat parsing and credibility scoring for Eurydice.

The game chat is short, noisy, and adversarial.  This module intentionally
uses conservative pattern matching: it extracts high-value social signals
without treating unrecognized text as evidence.
"""

from __future__ import annotations

import re
from typing import Any

from orpheus.perception._common import PLAYER_COLORS

from agents.eurydice.communication import (
    ACTION_KEYWORDS,
    ROLE_KEYWORDS,
    TEAM_KEYWORDS,
    ActionRequest,
    IdentityClaim,
    LocationClaim,
    ParsedMessage,
    Question,
)
from agents.eurydice.knowledge import PlayerKnowledge
from agents.eurydice.types import PlayerID, Role, RoleSource, Team, TeamSource


_IDENTITY_PREFIX_RE = re.compile(r"\b(?:I\s+AM|I'M|IM)\s+(?:A\s+|AN\s+|THE\s+)?([A-Z]+)\b")
_LOCATION_RE = re.compile(
    r"\b(?P<subject>[A-Z][A-Z0-9 _-]{0,24}?)\s+IS\s+IN\s+"
    r"(?P<location>[A-Z][A-Z0-9 _-]{0,24})(?:[.!?,]|$)"
)
_QUESTION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("WHO", "identity"),
    ("WHERE", "location"),
    ("FOUND", "found"),
    ("HAVE YOU", "status"),
    ("HAVE", "status"),
)


def parse_message(
    text: str,
    sender_id: PlayerID | None,
    channel: str,
    tick: int,
) -> ParsedMessage:
    """Parse raw chat text into Eurydice's structured message intents."""

    text_upper = text.upper()
    identity_claim = extract_identity_claim(text_upper)
    location_claim = _extract_location_claim(text_upper)
    action_request = extract_action_request(text_upper)
    question = extract_question(text_upper)
    uninterpretable = not any(
        (identity_claim, location_claim, action_request, question)
    )

    return ParsedMessage(
        raw_text=text,
        sender_id=sender_id,
        channel=channel,
        tick=tick,
        identity_claim=identity_claim,
        location_claim=location_claim,
        action_request=action_request,
        question=question,
        uninterpretable=uninterpretable,
    )


def assess_credibility(
    parsed: ParsedMessage,
    sender_knowledge: PlayerKnowledge | None,
    my_team: Team | None,
) -> float:
    """Estimate how much Eurydice should trust a parsed message.

    Mechanical role exchanges are the strongest evidence, color exchanges are
    useful but weaker, and known enemies are treated as hostile sources.  A
    sender contradicting mechanically known identity facts is sharply
    discounted even if they are otherwise trusted.
    """

    credibility = 0.3

    if sender_knowledge is not None and sender_knowledge.team is not None:
        if my_team is not None and sender_knowledge.team != my_team:
            credibility = 0.1
        elif my_team is not None and sender_knowledge.team == my_team:
            if sender_knowledge.team_source is TeamSource.ROLE_EXCHANGE:
                credibility = 0.85
            elif sender_knowledge.team_source is TeamSource.COLOR_EXCHANGE:
                credibility = 0.6

    if parsed.identity_claim is not None and _contradicts_known_identity(
        parsed.identity_claim, sender_knowledge
    ):
        credibility *= 0.1

    return _clamp(credibility)


def update_knowledge_from_chat(
    parsed: ParsedMessage,
    credibility: float,
    knowledge: dict[PlayerID, PlayerKnowledge],
    belief_state: Any,
) -> None:
    """Apply parsed chat claims to the mutable knowledge base.

    Credible identity claims become low-priority knowledge.  Raw identity
    claims and action requests are still recorded on the sender because even
    unreliable messages are useful behavioral evidence.
    """

    sender_record = _sender_record(parsed, knowledge)

    if parsed.identity_claim is not None and sender_record is not None:
        sender_record.claims_about_identity = _identity_claim_text(
            parsed.identity_claim
        )

    if parsed.action_request is not None and sender_record is not None:
        _note_action_request(sender_record, parsed)

    if credibility <= 0.5 or parsed.identity_claim is None:
        return

    target_id = _resolve_player_reference(
        parsed.identity_claim.subject, parsed, knowledge, belief_state
    )
    if target_id is None:
        return

    target_record = knowledge.setdefault(target_id, PlayerKnowledge.create(target_id))
    _apply_identity_claim(target_record, parsed.identity_claim, credibility)


def extract_identity_claim(text_upper: str) -> IdentityClaim | None:
    """Extract an ``I am ...`` role or team claim from uppercase text."""

    match = _IDENTITY_PREFIX_RE.search(text_upper)
    if match is None:
        return None

    keyword = match.group(1)
    role = ROLE_KEYWORDS.get(keyword)
    team = TEAM_KEYWORDS.get(keyword)
    if role is None and team is None:
        return None

    return IdentityClaim(
        claimed_role=role.name if role is not None else None,
        claimed_team=team.name if team is not None else None,
        confidence=0.8,
        subject="self",
    )


def extract_action_request(text_upper: str) -> ActionRequest | None:
    """Extract the first action request, preferring longer keyword matches."""

    for keyword in sorted(ACTION_KEYWORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(keyword)}\b", text_upper):
            action_type, target = ACTION_KEYWORDS[keyword]
            return ActionRequest(
                action_type=action_type,
                target=target,
                confidence=0.75,
            )
    return None


def extract_question(text_upper: str) -> Question | None:
    """Extract broad question intent from punctuation or question words."""

    for keyword, question_type in _QUESTION_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", text_upper):
            return Question(question_type=question_type)

    if "?" in text_upper:
        return Question(question_type="general")

    return None


def _extract_location_claim(text_upper: str) -> LocationClaim | None:
    """Extract simple ``X is in Y`` location claims."""

    match = _LOCATION_RE.search(text_upper)
    if match is None:
        return None

    subject = _clean_phrase(match.group("subject"))
    location = _clean_phrase(match.group("location"))
    if not subject or not location:
        return None

    return LocationClaim(subject=subject, location=location, confidence=0.6)


def _apply_identity_claim(
    record: PlayerKnowledge,
    claim: IdentityClaim,
    credibility: float,
) -> None:
    """Write a credible identity claim without overwriting stronger sources."""

    claimed_role = _role_from_claim(claim.claimed_role)
    claimed_team = _team_from_claim(claim.claimed_team)
    if claimed_team is None and claimed_role is not None:
        claimed_team = _team_for_role(claimed_role)

    if claimed_role is not None and record.role_source in (
        RoleSource.NONE,
        RoleSource.INFERRED,
        RoleSource.CHAT_CLAIM,
    ):
        record.role = claimed_role
        record.role_source = RoleSource.CHAT_CLAIM

    if claimed_team is not None and record.team_source in (
        TeamSource.NONE,
        TeamSource.INFERRED,
    ):
        record.team = claimed_team
        record.team_source = TeamSource.INFERRED
        record.team_confidence = max(record.team_confidence, credibility)


def _contradicts_known_identity(
    claim: IdentityClaim,
    sender_knowledge: PlayerKnowledge | None,
) -> bool:
    """Return True when a claim conflicts with established sender facts."""

    if sender_knowledge is None:
        return False

    claimed_role = _role_from_claim(claim.claimed_role)
    claimed_team = _team_from_claim(claim.claimed_team)
    if claimed_team is None and claimed_role is not None:
        claimed_team = _team_for_role(claimed_role)

    if (
        claimed_role is not None
        and sender_knowledge.role is not None
        and claimed_role is not sender_knowledge.role
    ):
        return True

    if (
        claimed_team is not None
        and sender_knowledge.team is not None
        and claimed_team is not sender_knowledge.team
    ):
        return True

    if (
        claimed_team is not None
        and sender_knowledge.role is not None
        and claimed_team is not _team_for_role(sender_knowledge.role)
    ):
        return True

    return False


def _resolve_player_reference(
    subject: str,
    parsed: ParsedMessage,
    knowledge: dict[PlayerID, PlayerKnowledge],
    belief_state: Any,
) -> PlayerID | None:
    """Resolve a parsed subject to a PlayerID when possible."""

    normalized = subject.strip().upper()
    if normalized in {"SELF", "ME", "I", "SENDER"}:
        return parsed.sender_id

    for player_id, record in knowledge.items():
        if record.name is not None and record.name.upper() == normalized:
            return player_id

    players = getattr(belief_state, "players", {})
    for index, player_info in players.items():
        name = getattr(player_info, "name", None)
        if name is not None and name.upper() == normalized:
            return (PLAYER_COLORS[index % len(PLAYER_COLORS)], index % 12)

    return None


def _sender_record(
    parsed: ParsedMessage,
    knowledge: dict[PlayerID, PlayerKnowledge],
) -> PlayerKnowledge | None:
    if parsed.sender_id is None:
        return None
    return knowledge.setdefault(parsed.sender_id, PlayerKnowledge.create(parsed.sender_id))


def _note_action_request(record: PlayerKnowledge, parsed: ParsedMessage) -> None:
    """Record a raw action request once on the sender record."""

    if parsed.raw_text and parsed.raw_text not in record.claims_made:
        record.claims_made.append(parsed.raw_text)


def _identity_claim_text(claim: IdentityClaim) -> str:
    parts: list[str] = []
    if claim.claimed_role is not None:
        parts.append(claim.claimed_role.title())
    if claim.claimed_team is not None and claim.claimed_team not in parts:
        parts.append(claim.claimed_team.title())
    return "I am " + "/".join(parts) if parts else "I am unknown"


def _role_from_claim(claimed_role: str | None) -> Role | None:
    if claimed_role is None:
        return None
    return Role.__members__.get(claimed_role.upper())


def _team_from_claim(claimed_team: str | None) -> Team | None:
    if claimed_team is None:
        return None
    return Team.__members__.get(claimed_team.upper())


def _team_for_role(role: Role) -> Team:
    if role in (Role.HADES, Role.CERBERUS, Role.SHADE, Role.SPY):
        return Team.SHADES
    return Team.NYMPHS


def _clean_phrase(value: str) -> str:
    return value.strip(" \t\r\n.!?,")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
