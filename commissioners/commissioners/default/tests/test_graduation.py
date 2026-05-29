from graduation import percentile_graduation

DIVISIONS = [
    {"id": "d0", "name": "open", "level": 0},
    {"id": "d1", "name": "mid", "level": 1},
    {"id": "d2", "name": "pro", "level": 2},
]


def _membership(policy_id: str, division_id: str) -> dict:
    return {"id": f"m_{policy_id}", "policy_version_id": policy_id, "division_id": division_id}


def _rankings(*policy_ids: str) -> list[dict]:
    return [{"policy_version_id": pid, "rank": i, "score": 1.0 - i * 0.1} for i, pid in enumerate(policy_ids, 1)]


def test_promote_and_relegate_to_adjacent_divisions():
    memberships = [_membership(p, "d1") for p in ("a", "b", "c", "d")]
    changes = percentile_graduation(
        _rankings("a", "b", "c", "d"),
        memberships=memberships,
        divisions=DIVISIONS,
        current_division_id="d1",
        promote_top_pct=25,
        relegate_bottom_pct=25,
    )
    by_membership = {c["membership_id"]: c["to_division_id"] for c in changes}
    assert by_membership == {"m_a": "d2", "m_d": "d0"}


def test_top_division_has_no_promotion_target():
    memberships = [_membership(p, "d2") for p in ("a", "b")]
    changes = percentile_graduation(
        _rankings("a", "b"),
        memberships=memberships,
        divisions=DIVISIONS,
        current_division_id="d2",
        promote_top_pct=50,
        relegate_bottom_pct=0,
    )
    # No division above level 2: promotion silently produces no change.
    assert changes == []


def test_empty_rankings_produce_no_changes():
    assert (
        percentile_graduation(
            [],
            memberships=[],
            divisions=DIVISIONS,
            current_division_id="d1",
            promote_top_pct=50,
            relegate_bottom_pct=50,
        )
        == []
    )


def test_positive_percent_moves_at_least_one():
    memberships = [_membership(p, "d1") for p in ("a", "b", "c")]
    changes = percentile_graduation(
        _rankings("a", "b", "c"),
        memberships=memberships,
        divisions=DIVISIONS,
        current_division_id="d1",
        promote_top_pct=1,  # floor(3 * 1/100) == 0, but at least one promotes
        relegate_bottom_pct=0,
    )
    assert [c["membership_id"] for c in changes] == ["m_a"]
