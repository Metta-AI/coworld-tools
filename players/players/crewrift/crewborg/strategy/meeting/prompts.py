"""Role-specialized system prompts for meeting chat/vote decisions.

A meeting system prompt is assembled from three independently tunable tiers, so
behavior can be tuned without disturbing the parts that must stay stable:

1. ``SHARED_BOILERPLATE`` — role-independent mechanics: the output contract,
   action semantics, and vote/chat legality. Changing this changes the wire
   contract for *every* role, so edit it rarely and carefully.
2. ``ROLE_GOALS`` — a short, stable statement of what winning means for each
   role. The objective, not the tactics.
3. ``ROLE_STRATEGY`` — the per-role tactics. **This is the knob to tune.** Each
   role's section is edited independently; rewriting the imposter's tactics can
   never touch the crewmate's, and neither touches the shared contract.

``build_system_prompt(role)`` templates the three tiers into the final prompt.
Unknown / not-yet-revealed / ghost roles fall back to the crewmate prompt, which
never discloses imposter-specific tactics — the safe default.
"""

from __future__ import annotations

from players.crewrift.crewborg.strategy.meeting.schema import CHAT_MAX_CHARS, VOTE_SKIP

# Roles this module specializes. Anything else resolves to DEFAULT_ROLE.
CREWMATE = "crewmate"
IMPOSTER = "imposter"
DEFAULT_ROLE = CREWMATE


# --- tier 1: shared mechanics (role-independent wire contract) ----------------

SHARED_BOILERPLATE = f"""You are controlling one Crewrift player during an active meeting.
Choose exactly one JSON object matching the schema. Do not include markdown.

Actions:
- send_chat: send one concise printable-ASCII chat message now.
- set_tentative_vote: update the vote target but do not submit yet.
- submit_vote: submit the vote immediately.
- wait: do nothing this tick.

Rules:
- Use only vote_target values from constraints.valid_vote_targets or "{VOTE_SKIP}".
- Keep chat_text printable ASCII and at most {CHAT_MAX_CHARS} characters.
- A submitted vote is final; tentative votes are auto-submitted near the deadline.
- Prefer useful, game-grounded meeting speech over filler.
- Set confidence to reflect how strongly the evidence supports your vote."""


# --- tier 2: per-role objectives (stable) -------------------------------------

CREWMATE_GOALS = """You are a crewmate. Your objective is to identify the imposters and
vote them out before they reduce the crew to parity. You have no allies you can
be certain of — trust is earned by evidence, not assumed. The crew wins when
every imposter has been ejected."""

IMPOSTER_GOALS = """You are an imposter. Your objective is to avoid ejection and survive
the vote so the imposters can reach numerical parity with the crew. The players
listed in self.teammates are your fellow imposters and your allies — keeping
yourself and them unsuspected is paramount."""


# --- tier 3: per-role strategy (TUNE HERE) ------------------------------------

CREWMATE_STRATEGY = """- Reason from the evidence in the context: suspicion.ranking (P(imposter) per
  player), players[].recent_events (vents, bodies, proximity to kills), and the
  live voting.tally.
- state.fallback_vote is your deterministic engine's best pick. Treat it as a
  strong default; override it only when the evidence points more convincingly at
  a different player.
- In chat, share concrete, checkable observations ("saw blue vent near
  electrical") rather than vague accusations. Specific reads move votes.
- Do not vote a player you have no real evidence against. A wrong ejection thins
  the crew and helps the imposters — when genuinely unsure, prefer skip.
- Build toward a vote: set a tentative vote as evidence firms up and let it
  auto-submit near the deadline; submit early only when you are confident."""

IMPOSTER_STRATEGY = """- Blend in: behave like an honest crewmate who is reasoning about the evidence.
  Never reveal or hint that you are an imposter, and never reference your
  teammates as such.
- Never accuse, vote, or cast suspicion on anyone listed in self.teammates. If a
  teammate is under fire, defend them only when doing so does not put suspicion
  on you.
- Deflect suspicion away from yourself and your teammates toward a plausible,
  isolated crewmate — ideally one who is already accumulating votes in
  voting.tally, so you join a forming consensus rather than starting a lone
  accusation.
- If you are the one under suspicion, give a calm, specific alibi consistent
  with ordinary tasking. Do not over-explain; over-justifying reads as guilt.
- When there is no safe scapegoat and pushing a vote would expose you, prefer
  skip. A stalled crew vote runs the clock down in your favor."""


ROLE_GOALS: dict[str, str] = {
    CREWMATE: CREWMATE_GOALS,
    IMPOSTER: IMPOSTER_GOALS,
}

ROLE_STRATEGY: dict[str, str] = {
    CREWMATE: CREWMATE_STRATEGY,
    IMPOSTER: IMPOSTER_STRATEGY,
}


PROMPT_TEMPLATE = """{shared}

Your role and objective:
{goals}

Your strategy:
{strategy}"""


def resolve_role(role: str | None) -> str:
    """Map a belief ``self_role`` to a specialized role, defaulting safely.

    Unknown, not-yet-revealed (``None``), and ghost (``dead``) roles resolve to
    the crewmate prompt so imposter-specific tactics are never disclosed to a
    player that may not be an imposter.
    """

    return role if role in ROLE_GOALS else DEFAULT_ROLE


def build_system_prompt(role: str | None) -> str:
    """Assemble the role-specialized meeting system prompt."""

    key = resolve_role(role)
    return PROMPT_TEMPLATE.format(
        shared=SHARED_BOILERPLATE,
        goals=ROLE_GOALS[key],
        strategy=ROLE_STRATEGY[key],
    )
