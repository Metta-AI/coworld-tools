from __future__ import annotations

from uuid import UUID

from commissioners.common.models import (
    DIVISION_TYPE_COMPETITION,
    DivisionSnapshot,
    MembershipSnapshot,
    OnRoundCompletedContext,
    PolicyTransitionObservation,
    PolicyMembershipEventChange,
    PolicyMembershipEventEvidence,
)
from commissioners.common.protocol import PolicyMembershipEventChange as ProtocolPolicyMembershipEventChange
from commissioners.common.utils import COMPLETED_EPISODE_COUNT_METADATA_KEY
from commissioners.common.ruleset_strategy.config import (
    DivisionMatch,
    RulesetStrategyCommissionerConfig,
    Transition,
    TransitionCriteria,
    TransitionRule,
    TransitionTarget,
)

NEGATIVE_AVERAGE_SCORE_TRANSITION_ID = "negative_average_score"
EXCESSIVE_CRASHED_EPISODES_TRANSITION_ID = "excessive_crashed_episodes"
MIN_CRASHED_EPISODES_PER_ROUND = 1
MAX_CRASHED_EPISODE_FRACTION_PER_ROUND = 0.5


def max_crashed_episodes(scheduled_episodes: int) -> float:
    return max(MIN_CRASHED_EPISODES_PER_ROUND, scheduled_episodes * MAX_CRASHED_EPISODE_FRACTION_PER_ROUND)


def build_membership_events(
    ctx: OnRoundCompletedContext,
    config: RulesetStrategyCommissionerConfig,
) -> list[PolicyMembershipEventChange]:
    if ctx.transition_observations is None:
        observations = {
            result.policy_version_id: PolicyTransitionObservation(
                scheduled_episodes=int(result.result_metadata.get(COMPLETED_EPISODE_COUNT_METADATA_KEY, 0)),
                completed_episodes=int(result.result_metadata.get(COMPLETED_EPISODE_COUNT_METADATA_KEY, 0)),
                score=result.score,
            )
            for result in ctx.round_results
        }
    else:
        observations = ctx.transition_observations
    events = build_competition_disqualification_events(ctx, observations)
    disqualified_membership_ids = {event.league_policy_membership_id for event in events}
    for rule in config.membership_changes:
        for membership in ctx.division_memberships:
            if membership.id in disqualified_membership_ids:
                continue
            if not rule.match.matches(ctx.division, membership):
                continue
            observation = observations.get(membership.policy_version_id)
            if observation is None:
                continue
            event = transition_change(
                rule,
                membership,
                ctx.all_divisions,
                completed_episodes=observation.completed_episodes,
                score=observation.score,
            )
            if event is not None:
                events.append(event)
    return events


def build_competition_disqualification_events(
    ctx: OnRoundCompletedContext,
    observations: dict[UUID, PolicyTransitionObservation] | None = None,
) -> list[PolicyMembershipEventChange]:
    if ctx.division.type != DIVISION_TYPE_COMPETITION:
        return []
    if observations is None:
        observations = {
            result.policy_version_id: PolicyTransitionObservation(
                scheduled_episodes=int(result.result_metadata.get(COMPLETED_EPISODE_COUNT_METADATA_KEY, 1)),
                completed_episodes=int(result.result_metadata.get(COMPLETED_EPISODE_COUNT_METADATA_KEY, 1)),
                score=result.score,
            )
            for result in ctx.round_results
        }
    events: list[PolicyMembershipEventChange] = []
    for membership in ctx.division_memberships:
        observation = observations.get(membership.policy_version_id)
        if observation is None:
            continue
        event: PolicyMembershipEventChange | None = None
        crashed_episodes = max(observation.scheduled_episodes - observation.completed_episodes, 0)
        if observation.completed_episodes > 0 and observation.score <= 0:
            event = disqualification_event(
                membership,
                reason="average round score <= 0",
                evidence=negative_average_score_evidence(observation),
            )
        elif crashed_episodes > max_crashed_episodes(observation.scheduled_episodes):
            event = disqualification_event(
                membership,
                reason="more than half of scheduled episodes crashed",
                evidence=excessive_crashed_episodes_evidence(observation),
            )
        if event is not None:
            events.append(event)
    return events


def build_negative_average_score_events(ctx: OnRoundCompletedContext) -> list[PolicyMembershipEventChange]:
    return [
        event
        for event in build_competition_disqualification_events(ctx)
        if event.evidence and event.evidence[0].metadata.get("transition_id") == NEGATIVE_AVERAGE_SCORE_TRANSITION_ID
    ]


def disqualification_event(
    membership: MembershipSnapshot,
    *,
    reason: str,
    evidence: PolicyMembershipEventEvidence,
) -> PolicyMembershipEventChange:
    return PolicyMembershipEventChange(
        league_policy_membership_id=membership.id,
        from_division_id=membership.division_id,
        to_division_id=None,
        status="disqualified",
        substatus="inactive",
        reason=reason,
        evidence=[evidence],
    )


def protocol_policy_membership_event(change: PolicyMembershipEventChange) -> ProtocolPolicyMembershipEventChange:
    return ProtocolPolicyMembershipEventChange.model_validate(change.model_dump(mode="json"))


def transition_change(
    rule: TransitionRule,
    membership: MembershipSnapshot,
    divisions: list[DivisionSnapshot],
    *,
    completed_episodes: int,
    score: float,
) -> PolicyMembershipEventChange | None:
    observed = {"completed_episodes": completed_episodes, "score": score}
    transition = next(
        (
            candidate
            for candidate in rule.transitions
            if criteria_matches(candidate.criteria, completed_episodes=completed_episodes, score=score)
        ),
        None,
    )
    if transition is None:
        return None

    target_division = target_for_transition(transition.to, membership, divisions)
    target_division_id = target_division.id if target_division is not None else None
    return PolicyMembershipEventChange(
        league_policy_membership_id=membership.id,
        from_division_id=membership.division_id,
        to_division_id=target_division_id,
        status=transition.to.status or membership_status(membership),
        substatus=transition.to.substatus,
        reason=transition.to.reason or transition_reason(transition),
        evidence=[transition_evidence(transition, observed, target_division_id=target_division_id)],
    )


def criteria_matches(criteria: TransitionCriteria, *, completed_episodes: int, score: float) -> bool:
    if criteria.otherwise:
        return True
    if criteria.completed_episodes_gt is not None:
        return completed_episodes > criteria.completed_episodes_gt
    if criteria.completed_episodes_lte is not None:
        return completed_episodes <= criteria.completed_episodes_lte
    if criteria.score_gt is not None:
        return score > criteria.score_gt
    if criteria.score_lte is not None:
        return score <= criteria.score_lte
    return False


def target_for_transition(
    target: TransitionTarget,
    membership: MembershipSnapshot,
    divisions: list[DivisionSnapshot],
) -> DivisionSnapshot | None:
    configured = target_division_for(
        divisions,
        name=target.to_division_name,
        match=target.to_division_match,
    )
    if configured is not None:
        return configured
    if target.status == "disqualified":
        return None
    return next((division for division in divisions if division.id == membership.division_id), None)


def transition_reason(transition: Transition) -> str:
    if transition.name is not None:
        return transition.name
    if transition.id is not None:
        return transition.id.replace("_", " ").capitalize()
    return "Ruleset transition"


def membership_status(membership: MembershipSnapshot) -> str:
    return membership.status.value if hasattr(membership.status, "value") else str(membership.status)


def criteria_evidence(criteria: TransitionCriteria) -> dict[str, int | float | bool]:
    return {
        key: value
        for key, value in criteria.model_dump(exclude_none=True).items()
        if value is not False
    }


def action_evidence(target: TransitionTarget) -> list[dict[str, object]]:
    action = {"type": "update_membership"} | target.model_dump(mode="json", exclude_none=True)
    return [action]


def transition_evidence(
    transition: Transition,
    observed: dict[str, int | float],
    *,
    target_division_id: object,
) -> PolicyMembershipEventEvidence:
    return PolicyMembershipEventEvidence(
        type="ruleset_transition",
        title="Ruleset transition",
        summary=transition_reason(transition),
        metadata={
            "transition_id": transition.id,
            "criteria": criteria_evidence(transition.criteria),
            "observed": observed,
            "actions": action_evidence(transition.to),
            "target_division_id": str(target_division_id) if target_division_id is not None else None,
        },
    )


def observation_evidence(observation: PolicyTransitionObservation) -> dict[str, int | float]:
    return {
        "scheduled_episodes": observation.scheduled_episodes,
        "completed_episodes": observation.completed_episodes,
        "crashed_episodes": max(observation.scheduled_episodes - observation.completed_episodes, 0),
        "score": observation.score,
    }


def negative_average_score_evidence(observation: PolicyTransitionObservation) -> PolicyMembershipEventEvidence:
    return PolicyMembershipEventEvidence(
        type="ruleset_transition",
        title="Ruleset transition",
        summary="average round score <= 0",
        metadata={
            "transition_id": NEGATIVE_AVERAGE_SCORE_TRANSITION_ID,
            "criteria": {"score_lte": 0.0},
            "observed": observation_evidence(observation),
            "actions": [{"type": "update_membership", "status": "disqualified", "substatus": "inactive"}],
            "target_division_id": None,
        },
    )


def excessive_crashed_episodes_evidence(observation: PolicyTransitionObservation) -> PolicyMembershipEventEvidence:
    return PolicyMembershipEventEvidence(
        type="ruleset_transition",
        title="Ruleset transition",
        summary="more than half of scheduled episodes crashed",
        metadata={
            "transition_id": EXCESSIVE_CRASHED_EPISODES_TRANSITION_ID,
            "criteria": {"crashed_episodes_gt": max_crashed_episodes(observation.scheduled_episodes)},
            "observed": observation_evidence(observation),
            "actions": [{"type": "update_membership", "status": "disqualified", "substatus": "inactive"}],
            "target_division_id": None,
        },
    )


def division_by_name(divisions: list[DivisionSnapshot], name: str | None) -> DivisionSnapshot | None:
    if name is None:
        return None
    return next((division for division in divisions if division.name == name), None)


def target_division_for(
    divisions: list[DivisionSnapshot],
    *,
    name: str | None,
    match: DivisionMatch | None,
) -> DivisionSnapshot | None:
    if name is not None:
        return division_by_name(divisions, name)
    if match is None:
        return None
    candidates = [division for division in divisions if match.matches(division)]
    return min(candidates, key=lambda division: (division.level, division.name, str(division.id)), default=None)
