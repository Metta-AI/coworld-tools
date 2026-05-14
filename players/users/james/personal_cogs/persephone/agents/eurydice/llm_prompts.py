"""Prompt construction for Eurydice LLM control surfaces.

The prompt layer is provider-independent. It gives the model a compact game
contract plus the current JSON context; deterministic code still validates
every returned semantic action before execution.
"""

from __future__ import annotations

import json
from typing import Any

from agents.eurydice.llm_context import llm_decision_schema

PROMPT_VERSION = "eurydice.llm_prompt.v3"


def infer_surface(context: dict[str, Any]) -> str:
    """Infer the narrow control surface for a context packet."""

    view = context.get("view")
    runtime = context.get("runtime") if isinstance(context.get("runtime"), dict) else {}
    legal_actions = set(context.get("legal_actions") or [])
    if view == "whisper":
        return "whisper"
    if view == "global_chat":
        return "global"
    if view == "hostage_select":
        return "hostage"
    if view == "leader_summit":
        return "summit"
    if (
        view in {"playing", "waiting_entry"}
        and "probe_player" in legal_actions
        and runtime.get("current_mode") in {"probe_systematic", "probe_target"}
    ):
        return "probe"
    if view in {"playing", "waiting_entry"} and "probe_player" in legal_actions:
        return "probe"
    return "strategic"


def build_prompt(context: dict[str, Any], *, surface: str | None = None) -> str:
    """Build a concise, surface-specific prompt for one decision context."""

    system_prompt, user_prompt = build_prompt_parts(context, surface=surface)
    return "\n\n".join([system_prompt, user_prompt])


def build_prompt_parts(
    context: dict[str, Any],
    *,
    surface: str | None = None,
) -> tuple[str, str]:
    """Build system/user prompt parts for Messages-style providers."""

    surface = surface or infer_surface(context)
    return _system_instructions(surface), _user_prompt(context, surface)


def _user_prompt(context: dict[str, Any], surface: str) -> str:
    legal_actions = context.get("legal_actions") or []
    return "\n".join(
        [
            f"Prompt version: {PROMPT_VERSION}",
            f"Control surface: {surface}",
            f"Legal actions now: {json.dumps(legal_actions, sort_keys=True)}",
            "Choose exactly one legal action. If no listed action advances the objective, choose hold.",
            "Decision schema:",
            json.dumps(llm_decision_schema(), sort_keys=True),
            "",
            "Context:",
            json.dumps(context, sort_keys=True),
            "",
            "Return exactly one JSON object and no prose.",
        ]
    )


def _system_instructions(surface: str) -> str:
    return "\n".join(
        [
            _common_strategy(),
            "",
            _surface_strategy(surface),
            "",
            "Output rules:",
            "- Use only actions present in legal_actions.",
            "- Never emit raw button presses or unsupported modes.",
            "- For target actions, target is a PlayerID [color, shape] from players.",
            "- For select_hostage, use only runtime.hostage_options.options player_id values with selected=false.",
            "- For select_hostage, hostage_targets must exactly match the remaining required count.",
            "- Chat messages must be ASCII, <=48 characters, and immediately useful.",
            "- Do not use coordinates or symbols like + or [] in chat messages.",
            "- Rationale must be <=120 characters: terse cause, no full paragraph.",
            "- Do not claim mechanical facts unless the context contains mechanical evidence.",
            "- Never write I AM [role] unless it matches self.role/team or the objective explicitly allows deception.",
            "- Never write [role] HERE unless it matches self.role; use [role] WHERE? for questions.",
            "- Never write I HAVE [role] unless self or a player has that role from role_exchange/one_way_reveal evidence.",
            "- Return JSON only.",
        ]
    )


def _common_strategy() -> str:
    return """You control Eurydice's semantic strategy layer for Persephone's Escape.

Game contract:
- Hades and Cerberus are the Shades key pair. Their mutual role exchange is the Shades win prerequisite.
- Persephone and Demeter are the Nymphs key pair. Their mutual role exchange is the Nymphs win prerequisite.
- If our key exchange is unfinished, completing it is usually more important than positioning or broad scouting.
- If both teams complete their key exchange, Hades co-located with Persephone favors Shades; separation favors Nymphs.
- Shade grunts help Hades/Cerberus exchange and position Hades with Persephone.
- Nymph grunts protect Persephone, help Persephone/Demeter exchange, and keep Hades separated from Persephone.
- Spy play is information and cover management. Role exchange reveals Spy; color exchange can mislead because Spy colors invert.

Evidence rules:
- Mechanical role exchange and info-screen evidence outrank chat claims.
- Color exchange is strong team evidence, but weaker when Spy is in the config.
- Recent visible position and room facts outrank stale assumptions.
- Other agents may use unknown policies. Do not depend on Eurydice-specific conventions or synchronized behavior.

Strategy rules:
- Prefer actions that create real progress: key-pair role exchange, finding a key partner, locating enemy key roles, protecting or moving key roles, or extracting useful room intel.
- Ask for one specific thing at a time. Avoid generic STATUS messages.
- Reveal true role only when it helps a safe key exchange, verifies a trusted ally, or is a deliberate disruption/cover decision.
- Key roles should avoid revealing identity to known enemies. Grunts can trade information more freely.
- In final-round panic, if our key exchange is impossible, wasting enemy time and separating enemy key roles can be correct."""


def _surface_strategy(surface: str) -> str:
    if surface == "probe":
        return """Probe target guidance:
- Pick a visible or known-position player who advances the current objective.
- If you are Hades, prioritize likely Shades/Cerberus until role exchange completes; then locate Persephone.
- If you are Cerberus, prioritize likely Shades/Hades until role exchange completes; then help locate Persephone.
- If you are Persephone, prioritize likely Nymphs/Demeter and avoid risky unknown/Shades reveals.
- If you are Demeter, prioritize likely Nymphs/Persephone; after exchange, locate Hades.
- If you are Shade, scout room composition, find Hades/Cerberus, or locate Persephone for Shades.
- If you are Nymph, find/protect Persephone or locate Hades for Nymphs.
- Prefer unprobed local players over repeated failed targets unless urgency is high."""
    if surface == "whisper":
        return """Whisper guidance:
- Pending entry: grant likely allies, useful unknowns, or the intended probe target unless a sensitive exchange is underway with hostile/unknown third occupants.
- If a role offer is from a safe probable partner or verified ally, accepting can complete the only win-relevant exchange.
- Hades accepts role exchange with confirmed/probable Shades, especially possible Cerberus; avoid Nymphs unless final disruption requires risk.
- Cerberus accepts role exchange with confirmed/probable Shades, especially possible Hades.
- Persephone accepts role exchange only with confirmed/probable Nymphs, especially Demeter; never reveal to confirmed Shades.
- Demeter accepts role exchange with confirmed/probable Nymphs, especially Persephone.
- Grunts can use color/role exchange to gather and relay information.
- Spy should preserve cover unless verifying a real ally or making a decisive endgame play.
- Message examples should be specific: ROLE SHARE?, COLOR?, WHO HERE?, SEND ME, HADES HERE?, PERS WHERE?"""
    if surface == "global":
        return """Global chat guidance:
- Use global sparingly. It is for room-level coordination when private contact is blocked or leadership/hostage coordination matters.
- Ask for a concrete action or fact: SEND ME, NEED LEADER, HADES WHERE?, DEMETER HERE?, DO NOT SEND PERS.
- Do not spam generic status checks.
- Do not leak a key role's true identity or room to enemies unless the objective explicitly calls for disruption or bait."""
    if surface == "hostage":
        return """Hostage-selection guidance:
- Select exactly the required number of eligible targets.
- Copy player_id values exactly from runtime.hostage_options.options entries where selected=false.
- Do not invent hostage targets from visible colors, shapes, rooms, or recent chat.
- Never select yourself; the validator also blocks this.
- Shades leader: help Hades/Cerberus meet, keep Hades with Persephone once favorable, send Nymphs or expendable unknowns when making room, and avoid sending Hades/Cerberus apart unless it completes their exchange.
- Nymphs leader: protect Persephone, avoid sending Persephone, send Hades away from Persephone if both are local, and send Shades/unknowns before valuable Nymphs.
- Grunt volunteers can be expendable when moving them helps the key pair.
- If information is insufficient and a legal choice is not clearly beneficial, hold."""
    if surface == "summit":
        return """Leader-summit guidance:
- Summit is chat only; no mechanical exchange is possible.
- Use it to negotiate hostage movement, extract enemy-key locations, or coordinate with an allied leader.
- If allied or probably allied, share concise room intel and request the exact needed movement.
- If enemy or unknown, ask targeted questions and consider misdirection that protects your key role.
- Useful messages: SEND ME, SEND HADES, KEEP PERS, WHO HADES?, DEMETER WHERE?."""
    return """Strategic guidance:
- Only take a broad action if it is legal and clearly useful now.
- open_info is useful when validating known identities or recent exchanges.
- open_global is useful when room-level coordination is needed.
- move_to should move toward a specific visible/known target or tactical position, not wander.
- hold is correct when deterministic fallback is already suitable or the legal surface is not useful."""


__all__ = ["PROMPT_VERSION", "build_prompt", "build_prompt_parts", "infer_surface"]
