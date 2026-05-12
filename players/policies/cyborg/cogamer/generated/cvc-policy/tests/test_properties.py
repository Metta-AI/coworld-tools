"""Hypothesis property tests.

Invariants that must hold for any legal input.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from cvc_policy.agent.cargo_cap import CargoCapTracker
from cvc_policy.agent.resources import resource_priority
from cvc_policy.agent.scoring import scramble_target_score
from cvc_policy.agent.types import ELEMENTS, KnownEntity
from mettagrid.sdk.agent import (
    GridPosition,
    MettagridState,
    SelfState,
    TeamSummary,
)


# --- resource_priority ---------------------------------------------------

_RESOURCES = list(ELEMENTS)


def _state_with_shared(inventory: dict[str, int]) -> MettagridState:
    self_state = SelfState(
        entity_id="agent_self",
        entity_type="agent",
        position=GridPosition(x=0, y=0),
        labels=[],
        attributes={"global_x": 0, "global_y": 0, "team": "team_0"},
        role=None,
        inventory={"hp": 100},
        status=[],
    )
    ts = TeamSummary(
        team_id="team_0",
        members=[],
        shared_inventory=dict(inventory),
        shared_objectives=[],
    )
    return MettagridState(
        game="t", step=0, self_state=self_state, visible_entities=[],
        team_summary=ts, recent_events=[],
    )


@settings(max_examples=50, deadline=None)
@given(
    inventory=st.dictionaries(
        keys=st.sampled_from(_RESOURCES + ["heart", "extra"]),
        values=st.integers(min_value=0, max_value=20),
        max_size=8,
    ),
    bias=st.sampled_from(_RESOURCES),
)
def test_resource_priority_is_permutation(inventory, bias):
    state = _state_with_shared(inventory)
    order = resource_priority(state, resource_bias=bias)
    assert sorted(order) == sorted(_RESOURCES)
    assert len(order) == len(_RESOURCES)


@settings(max_examples=50, deadline=None)
@given(
    inventory=st.dictionaries(
        keys=st.sampled_from(_RESOURCES),
        values=st.integers(min_value=0, max_value=20),
        max_size=4,
    ),
    bias=st.sampled_from(_RESOURCES),
)
def test_resource_priority_sorted_ascending_with_bias_first_on_ties(inventory, bias):
    state = _state_with_shared(inventory)
    order = resource_priority(state, resource_bias=bias)

    # Ascending by inventory amount
    amounts = [int(inventory.get(r, 0)) for r in order]
    assert amounts == sorted(amounts)

    # Where amounts tie, bias resource (if present in the tie group) comes first.
    for i in range(len(order) - 1):
        a_amt = int(inventory.get(order[i], 0))
        b_amt = int(inventory.get(order[i + 1], 0))
        if a_amt == b_amt:
            # In a tie group: bias must not be preceded by a non-bias peer.
            if order[i + 1] == bias:
                # bias came after a non-bias tied peer — bug
                assert False, f"bias {bias} came after {order[i]} at same amount {a_amt}"


# --- CargoCapTracker -----------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(
    ramp=st.lists(st.integers(min_value=1, max_value=20), min_size=1, max_size=6, unique=True).map(sorted),
    plateau_repeats=st.integers(min_value=1, max_value=4),
)
def test_cargo_cap_single_plateau(ramp, plateau_repeats):
    """Monotonic cargo growth followed by a plateau -> cap == plateau value."""
    tracker = CargoCapTracker()
    sig = ("miner",)
    # Growth phase: mined_last_tick True, each observation grows cargo.
    for c in ramp:
        tracker.observe(gear_sig=sig, cargo=c, mined_last_tick=True)
    plateau = ramp[-1]
    # Plateau: re-observe same cargo with mined_last_tick True.
    for _ in range(plateau_repeats):
        tracker.observe(gear_sig=sig, cargo=plateau, mined_last_tick=True)
    assert tracker.known_cap(sig) == plateau


@settings(max_examples=50, deadline=None)
@given(
    true_cap=st.integers(min_value=2, max_value=15),
)
def test_cargo_cap_bounded_by_true_cap(true_cap):
    """If cargo is always <= true_cap and includes a plateau at true_cap under
    a matching gear_sig, known_cap equals true_cap."""
    tracker = CargoCapTracker()
    sig = ("miner",)
    # Ramp up to true_cap
    for c in range(1, true_cap + 1):
        tracker.observe(gear_sig=sig, cargo=c, mined_last_tick=True)
    # Plateau at true_cap
    tracker.observe(gear_sig=sig, cargo=true_cap, mined_last_tick=True)
    assert tracker.known_cap(sig) == true_cap


@settings(max_examples=50, deadline=None)
@given(
    high_cap=st.integers(min_value=5, max_value=15),
    lower=st.integers(min_value=1, max_value=4),
)
def test_cargo_cap_monotonic_never_shrinks(high_cap, lower):
    """Once known_cap(sig) is set, a smaller plateau cannot shrink it."""
    tracker = CargoCapTracker()
    sig = ("miner",)
    for c in range(1, high_cap + 1):
        tracker.observe(gear_sig=sig, cargo=c, mined_last_tick=True)
    tracker.observe(gear_sig=sig, cargo=high_cap, mined_last_tick=True)
    assert tracker.known_cap(sig) == high_cap
    # Now simulate a lower false plateau (e.g. mid-trip after deposit).
    tracker.observe(gear_sig=sig, cargo=lower, mined_last_tick=True)
    tracker.observe(gear_sig=sig, cargo=lower, mined_last_tick=True)
    assert tracker.known_cap(sig) == high_cap


# --- scramble_target_score -----------------------------------------------


def _junction(x: int, y: int) -> KnownEntity:
    return KnownEntity(
        entity_type="junction",
        global_x=x,
        global_y=y,
        labels=(),
        team=None,
        owner=None,
        last_seen_step=0,
        attributes={},
    )


@settings(max_examples=50, deadline=None)
@given(
    hub=st.tuples(st.integers(min_value=-20, max_value=20), st.integers(min_value=-20, max_value=20)),
    here=st.tuples(st.integers(min_value=-20, max_value=20), st.integers(min_value=-20, max_value=20)),
    close_offset=st.integers(min_value=0, max_value=4),
    far_extra=st.integers(min_value=1, max_value=15),
)
def test_scramble_target_distance_monotonic(hub, here, close_offset, far_extra):
    """With identical blocker sets, a candidate closer to current_position
    scores <= a candidate farther away (tuple natural ordering; lower is
    preferred)."""
    # Place candidates along +x so the farther one is strictly farther.
    close_x = here[0] + close_offset
    far_x = close_x + far_extra
    closer = _junction(close_x, here[1])
    farther = _junction(far_x, here[1])
    score_close = scramble_target_score(
        current_position=here,
        hub_position=hub,
        candidate=closer,
        neutral_junctions=[],
        friendly_junctions=[],
    )
    score_far = scramble_target_score(
        current_position=here,
        hub_position=hub,
        candidate=farther,
        neutral_junctions=[],
        friendly_junctions=[],
    )
    # Same blockers, same neutrals/friendly; only distance and corner_pressure
    # differ. corner_pressure is subtracted for the farther one (more negative),
    # but it saturates at 10.0 and grows slowly (/8.0). With far_extra>=1 the
    # distance difference dominates except when corner_pressure grows past the
    # distance delta. Assert the primary tuple component uses natural ordering
    # on distance - corner_pressure.
    # distance delta = far_extra, corner_pressure delta <= far_extra/8 <= far_extra.
    # So score_far[0] - score_close[0] = far_extra - (cp_far - cp_close) >= 0.
    assert score_close[0] <= score_far[0]
