"""Reusable assertion helpers returning AssertResult.

Each helper is a factory: takes configuration, returns a callable
`(Run) -> AssertResult`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from cvc_policy.scenarios._run import Run


@dataclass
class AssertResult:
    name: str
    passed: bool
    message: str = ""
    failed_at_step: int | None = None


def no_crash() -> Callable[[Run], AssertResult]:
    def _check(run: Run) -> AssertResult:
        errors = run.events_of_type("error")
        if not errors:
            return AssertResult(name="no_crash", passed=True, message="no error events")
        first = errors[0]
        return AssertResult(
            name="no_crash",
            passed=False,
            message=f"error event: {first['payload']}",
            failed_at_step=first["step"],
        )

    return _check


def has_action_event_per_agent(cogs: int) -> Callable[[Run], AssertResult]:
    def _check(run: Run) -> AssertResult:
        seen = {e["agent"] for e in run.events_of_type("action")}
        missing = [a for a in range(cogs) if a not in seen]
        if not missing:
            return AssertResult(
                name="has_action_event_per_agent", passed=True, message=f"all {cogs} agents acted"
            )
        return AssertResult(
            name="has_action_event_per_agent",
            passed=False,
            message=f"no action events for agent {missing[0]}",
        )

    return _check


def cap_discovered_by(
    *, agent: int, gear_sig: tuple[str, ...], expected_cap: int, by_step: int
) -> Callable[[Run], AssertResult]:
    def _check(run: Run) -> AssertResult:
        sig = list(gear_sig)
        for e in run.events_of_type("cap_discovered"):
            if e.get("agent") != agent:
                continue
            if e["payload"].get("gear_sig") != sig:
                continue
            if e["payload"].get("cap") != expected_cap:
                return AssertResult(
                    name="cap_discovered_by",
                    passed=False,
                    message=f"cap mismatch: got {e['payload'].get('cap')} want {expected_cap}",
                    failed_at_step=e["step"],
                )
            if e["step"] > by_step:
                return AssertResult(
                    name="cap_discovered_by",
                    passed=False,
                    message=f"discovered at step {e['step']} > by_step {by_step}",
                    failed_at_step=e["step"],
                )
            return AssertResult(
                name="cap_discovered_by",
                passed=True,
                message=f"cap={expected_cap} at step {e['step']}",
            )
        return AssertResult(
            name="cap_discovered_by",
            passed=False,
            message=f"no cap_discovered(gear_sig={gear_sig}) for agent {agent}",
        )

    return _check


def no_target_at(pos: tuple[int, int]) -> Callable[[Run], AssertResult]:
    target_pos = list(pos)

    def _check(run: Run) -> AssertResult:
        for e in run.events_of_type("target"):
            if e["payload"].get("pos") == target_pos or tuple(e["payload"].get("pos", [])) == pos:
                return AssertResult(
                    name="no_target_at",
                    passed=False,
                    message=f"target at {pos} by agent {e.get('agent')}",
                    failed_at_step=e["step"],
                )
        return AssertResult(name="no_target_at", passed=True, message=f"no target at {pos}")

    return _check


def mining_trips_efficient(
    *, agent: int, max_bumps_per_trip: int
) -> Callable[[Run], AssertResult]:
    """After the first cap_discovered, no mining trip should bump the
    target more than `max_bumps_per_trip` times. The cap+extract_amount
    math determines this bound; we pass it in rather than infer it
    from the event stream because extract amounts vary by resource.
    """

    def _check(run: Run) -> AssertResult:
        discs = [
            e
            for e in run.events_of_type("cap_discovered")
            if e.get("agent") == agent
        ]
        if not discs:
            return AssertResult(
                name="mining_trips_efficient",
                passed=False,
                message="no cap_discovered event",
            )
        discovery_step = discs[0]["step"]
        trips = run.mining_trips(agent)
        post = [t for t in trips if t.start_step > discovery_step]
        if not post:
            return AssertResult(
                name="mining_trips_efficient",
                passed=False,
                message="no mining trips after cap_discovered",
            )
        for t in post:
            if t.bump_count > max_bumps_per_trip:
                return AssertResult(
                    name="mining_trips_efficient",
                    passed=False,
                    message=(
                        f"trip at step {t.start_step} had {t.bump_count} bumps, "
                        f"max allowed {max_bumps_per_trip}"
                    ),
                    failed_at_step=t.end_step,
                )
        return AssertResult(
            name="mining_trips_efficient",
            passed=True,
            message=f"{len(post)} trips, max {max_bumps_per_trip} bumps each",
        )

    return _check


def known_entities_at_least(
    *, agent: int, minimum: int
) -> Callable[[Run], AssertResult]:
    """Assert the final world_model_summary has known_entities >= minimum."""

    def _check(run: Run) -> AssertResult:
        summaries = [
            e
            for e in run.events_of_type("world_model_summary")
            if e.get("agent") == agent
        ]
        if not summaries:
            return AssertResult(
                name="known_entities_at_least",
                passed=False,
                message="no world_model_summary event",
            )
        last = summaries[-1]
        n = last["payload"].get("known_entities", 0)
        if n >= minimum:
            return AssertResult(
                name="known_entities_at_least",
                passed=True,
                message=f"known_entities {n} >= {minimum}",
            )
        return AssertResult(
            name="known_entities_at_least",
            passed=False,
            message=f"known_entities {n} < {minimum}",
            failed_at_step=last["step"],
        )

    return _check


def after_heavy_trip_switches_target(
    *, agent: int, heavy_threshold: int
) -> Callable[[Run], AssertResult]:
    """Assert: whenever a mining trip has >= heavy_threshold bumps
    (proxy for self-draining the extractor), the next mining trip for
    the same agent is at a different position.

    This is the reframed form of `empty_extractor_skipped` — see
    design doc §7a for the rationale.
    """

    def _check(run: Run) -> AssertResult:
        trips = run.mining_trips(agent)
        for i, t in enumerate(trips):
            if t.bump_count < heavy_threshold:
                continue
            nxt = trips[i + 1] if i + 1 < len(trips) else None
            if nxt is None:
                # last trip in run; nothing to check
                continue
            if nxt.target_pos == t.target_pos:
                return AssertResult(
                    name="after_heavy_trip_switches_target",
                    passed=False,
                    message=(
                        f"heavy trip at {t.target_pos} ({t.bump_count} bumps) "
                        f"followed by another trip at the same position"
                    ),
                    failed_at_step=nxt.start_step,
                )
        return AssertResult(
            name="after_heavy_trip_switches_target",
            passed=True,
            message=f"all heavy (>= {heavy_threshold} bump) trips switched targets",
        )

    return _check


__all__ = [
    "AssertResult",
    "no_crash",
    "has_action_event_per_agent",
    "cap_discovered_by",
    "no_target_at",
    "mining_trips_efficient",
    "known_entities_at_least",
    "after_heavy_trip_switches_target",
]
