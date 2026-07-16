from __future__ import annotations

from commissioners.common.models import (
    DivisionSnapshot,
    MembershipSnapshot,
    OnRoundCompletedContext,
    POLICY_MEMBERSHIP_SUBSTATUS_ACTIVE,
    POLICY_MEMBERSHIP_SUBSTATUS_BENCHED,
    PolicyTransitionObservation,
    PolicyMembershipEventChange,
    PolicyMembershipEventEvidence,
    PolicyMembershipStatus,
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

DEFAULT_COMPETING_SUBSTATUS_REASON = "Default commissioner membership status assignment"


def build_default_competing_substatus_events(
    ctx: OnRoundCompletedContext,
    *,
    exclude_membership_ids: set[object] | None = None,
) -> list[PolicyMembershipEventChange]:
    exclude_membership_ids = exclude_membership_ids or set()
    events: list[PolicyMembershipEventChange] = []
    for membership in ctx.division_memberships:
        if membership.id in exclude_membership_ids or membership_status(membership) != PolicyMembershipStatus.competing.value:
            continue
        substatus = (
            POLICY_MEMBERSHIP_SUBSTATUS_ACTIVE if membership.is_champion else POLICY_MEMBERSHIP_SUBSTATUS_BENCHED
        )
        if membership_event_is_noop(
            membership,
            target_division_id=membership.division_id,
            status=PolicyMembershipStatus.competing.value,
            substatus=substatus,
        ):
            continue
        events.append(
            PolicyMembershipEventChange(
                league_policy_membership_id=membership.id,
                from_division_id=membership.division_id,
                to_division_id=membership.division_id,
                status=PolicyMembershipStatus.competing.value,
                substatus=substatus,
                reason=DEFAULT_COMPETING_SUBSTATUS_REASON,
            )
        )
    return events


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
    recent_rounds: dict[object, list[tuple[object, float]]] = {}
    for result in ctx.recent_results:
        recent_rounds.setdefault(result.round_id, []).append(
            (result.policy_version_id, result.score)
        )
    current_round_results = [
        (result.policy_version_id, result.score) for result in ctx.round_results
    ]
    events: list[PolicyMembershipEventChange] = []
    for rule in config.membership_changes:
        for membership in ctx.division_memberships:
            if not rule.match.matches(ctx.division, membership):
                continue
            observation = observations.get(membership.policy_version_id)
            if observation is None:
                continue
            event = transition_change(
                rule,
                membership,
                ctx.all_divisions,
                observation=observation,
                policy_version_id=membership.policy_version_id,
                recent_rounds=recent_rounds,
                current_round_results=current_round_results,
            )
            if event is not None:
                events.append(event)
    return events


def protocol_policy_membership_event(change: PolicyMembershipEventChange) -> ProtocolPolicyMembershipEventChange:
    return ProtocolPolicyMembershipEventChange.model_validate(change.model_dump(mode="json"))


def transition_change(
    rule: TransitionRule,
    membership: MembershipSnapshot,
    divisions: list[DivisionSnapshot],
    *,
    observation: PolicyTransitionObservation,
    policy_version_id: object = None,
    recent_rounds: dict[object, list[tuple[object, float]]] | None = None,
    current_round_results: list[tuple[object, float]] | None = None,
) -> PolicyMembershipEventChange | None:
    observed: dict[str, int | float] = {
        "completed_episodes": observation.completed_episodes,
        "scheduled_episodes": observation.scheduled_episodes,
        "score": observation.score,
    }
    if observation.failed_episodes:
        observed["failed_episodes"] = observation.failed_episodes
    if recent_rounds:
        observed["recent_rounds_observed"] = sum(
            1
            for results in recent_rounds.values()
            if any(pvid == policy_version_id for pvid, _ in results)
        )
    transition = next(
        (
            candidate
            for candidate in rule.transitions
            if criteria_matches(
                candidate.criteria,
                completed_episodes=observation.completed_episodes,
                score=observation.score,
                policy_version_id=policy_version_id,
                recent_rounds=recent_rounds,
                current_round_results=current_round_results,
            )
        ),
        None,
    )
    if transition is None:
        return None

    target_division = target_for_transition(transition.to, membership, divisions)
    target_division_id = target_division.id if target_division is not None else None
    target_status = transition.to.status or membership_status(membership)
    target_substatus = transition.to.substatus
    if membership_event_is_noop(
        membership,
        target_division_id=target_division_id,
        status=target_status,
        substatus=target_substatus,
    ):
        return None
    return PolicyMembershipEventChange(
        league_policy_membership_id=membership.id,
        from_division_id=membership.division_id,
        to_division_id=target_division_id,
        status=target_status,
        substatus=target_substatus,
        reason=transition.to.reason or transition_reason(transition),
        evidence=[
            transition_evidence(
                transition,
                observed,
                target_division_id=target_division_id,
                observation=observation,
            )
        ],
    )


def criteria_matches(
    criteria: TransitionCriteria,
    *,
    completed_episodes: int,
    score: float,
    policy_version_id: object = None,
    recent_rounds: dict[object, list[tuple[object, float]]] | None = None,
    current_round_results: list[tuple[object, float]] | None = None,
) -> bool:
    if criteria.otherwise:
        return True
    if criteria.completed_episodes_gt is not None:
        return completed_episodes > criteria.completed_episodes_gt
    if criteria.completed_episodes_lte is not None:
        return completed_episodes <= criteria.completed_episodes_lte
    if criteria.score_gt is not None:
        condition = lambda s: s > criteria.score_gt  # noqa: E731
    elif criteria.score_lte is not None:
        condition = lambda s: s <= criteria.score_lte  # noqa: E731
    else:
        return False
    if not condition(score):
        return False
    if criteria.sustained_rounds is None:
        return True
    return _sustained_condition_holds(
        criteria.sustained_rounds,
        condition,
        policy_version_id=policy_version_id,
        recent_rounds=recent_rounds or {},
        current_round_results=current_round_results or [],
    )


def _sustained_condition_holds(
    sustained_rounds: int,
    condition,
    *,
    policy_version_id: object,
    recent_rounds: dict[object, list[tuple[object, float]]],
    current_round_results: list[tuple[object, float]],
) -> bool:
    # Sustained: the condition must hold for EVERY recent round the policy
    # appears in (order-free — the protocol carries no round ordering), and at
    # least sustained_rounds of those rounds must be DISCRIMINATING: some
    # other policy in the same round did NOT satisfy the condition. The guard
    # keeps a league-wide outage (e.g. a game update blinding every bot at
    # once, all scores zero) from mass-disqualifying the whole field, and
    # makes thin history fail-safe: too few rounds on record, no transition.
    discriminating = 0
    rounds = list(recent_rounds.values()) + [current_round_results]
    seen_any = False
    for results in rounds:
        own = [s for pvid, s in results if pvid == policy_version_id]
        if not own:
            continue
        seen_any = True
        if not all(condition(s) for s in own):
            return False
        if any(not condition(s) for pvid, s in results if pvid != policy_version_id):
            discriminating += 1
    return seen_any and discriminating >= sustained_rounds


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


def membership_event_is_noop(
    membership: MembershipSnapshot,
    *,
    target_division_id: object,
    status: str,
    substatus: str | None,
) -> bool:
    return (
        membership.division_id == target_division_id
        and membership_status(membership) == status
        and membership.substatus == substatus
    )


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
    observation: PolicyTransitionObservation,
) -> PolicyMembershipEventEvidence:
    metadata: dict[str, object] = {
        "transition_id": transition.id,
        "criteria": criteria_evidence(transition.criteria),
        "observed": observed,
        "actions": action_evidence(transition.to),
        "target_division_id": str(target_division_id) if target_division_id is not None else None,
    }
    if observation.failed_request_ids:
        metadata["failed_request_ids"] = observation.failed_request_ids
    if observation.failure_error_samples:
        metadata["failure_error_samples"] = observation.failure_error_samples
    return PolicyMembershipEventEvidence(
        type="ruleset_transition",
        title="Ruleset transition",
        summary=transition_reason(transition),
        metadata=metadata,
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
