"""Tests for dynamic cargo-cap discovery.

The tracker watches (gear_sig, cargo, attempted_mine) tuples across ticks.
When a mine attempt does not increase cargo, the current cargo is the cap
for that gear combination. The agent uses `known_cap(sig)` as its deposit
threshold; before discovery it has no cap and keeps mining.
"""

from __future__ import annotations

import pytest

from cvc_policy.agent.cargo_cap import CargoCapTracker


# ---------------------------------------------------------------------------
# Basic tracker behavior
# ---------------------------------------------------------------------------


class TestCargoCapTracker:
    def test_empty_tracker_has_no_cap(self):
        tracker = CargoCapTracker()
        assert tracker.known_cap(("miner",)) is None

    def test_single_successful_mine_does_not_set_cap(self):
        tracker = CargoCapTracker()
        tracker.observe(gear_sig=("miner",), cargo=0, mined_last_tick=False)
        tracker.observe(gear_sig=("miner",), cargo=10, mined_last_tick=True)
        assert tracker.known_cap(("miner",)) is None

    def test_plateau_after_mine_sets_cap(self):
        tracker = CargoCapTracker()
        tracker.observe(gear_sig=("miner",), cargo=0, mined_last_tick=False)
        tracker.observe(gear_sig=("miner",), cargo=10, mined_last_tick=True)
        tracker.observe(gear_sig=("miner",), cargo=20, mined_last_tick=True)
        tracker.observe(gear_sig=("miner",), cargo=30, mined_last_tick=True)
        tracker.observe(gear_sig=("miner",), cargo=40, mined_last_tick=True)
        # Next mine attempt fails — cargo stays at 40 → cap discovered.
        tracker.observe(gear_sig=("miner",), cargo=40, mined_last_tick=True)
        assert tracker.known_cap(("miner",)) == 40

    def test_plateau_without_mine_attempt_does_not_set_cap(self):
        """Cargo staying flat while NOT trying to mine must not count as cap."""
        tracker = CargoCapTracker()
        tracker.observe(gear_sig=("miner",), cargo=20, mined_last_tick=False)
        tracker.observe(gear_sig=("miner",), cargo=20, mined_last_tick=False)
        tracker.observe(gear_sig=("miner",), cargo=20, mined_last_tick=False)
        assert tracker.known_cap(("miner",)) is None

    def test_cap_is_per_gear_signature(self):
        tracker = CargoCapTracker()
        # Discover cap=4 with no gear.
        tracker.observe(gear_sig=(), cargo=0, mined_last_tick=False)
        tracker.observe(gear_sig=(), cargo=1, mined_last_tick=True)
        tracker.observe(gear_sig=(), cargo=2, mined_last_tick=True)
        tracker.observe(gear_sig=(), cargo=3, mined_last_tick=True)
        tracker.observe(gear_sig=(), cargo=4, mined_last_tick=True)
        tracker.observe(gear_sig=(), cargo=4, mined_last_tick=True)
        assert tracker.known_cap(()) == 4
        # Gear signature ("miner",) is still unknown.
        assert tracker.known_cap(("miner",)) is None

    def test_cap_survives_gear_switch(self):
        tracker = CargoCapTracker()
        # Discover no-gear cap.
        for i, c in enumerate([0, 1, 2, 3, 4, 4]):
            tracker.observe(gear_sig=(), cargo=c, mined_last_tick=i > 0)
        # Switch to miner gear — must not clobber the () cap.
        tracker.observe(gear_sig=("miner",), cargo=0, mined_last_tick=False)
        assert tracker.known_cap(()) == 4

    def test_drop_resets_prev_cargo_so_next_plateau_not_false_positive(self):
        """After depositing (cargo drops), a later plateau at the same level isn't
        mistaken for a re-discovery at a smaller cap."""
        tracker = CargoCapTracker()
        # Discover 40.
        for i, c in enumerate([0, 10, 20, 30, 40, 40]):
            tracker.observe(gear_sig=("miner",), cargo=c, mined_last_tick=i > 0)
        assert tracker.known_cap(("miner",)) == 40
        # Deposit — cargo drops to 0.
        tracker.observe(gear_sig=("miner",), cargo=0, mined_last_tick=False)
        # Mine back up; a false plateau at 10 must not shrink the known cap.
        tracker.observe(gear_sig=("miner",), cargo=10, mined_last_tick=True)
        tracker.observe(gear_sig=("miner",), cargo=10, mined_last_tick=True)
        # Cap should NOT be overwritten down to 10. We keep the known 40.
        assert tracker.known_cap(("miner",)) == 40


# ---------------------------------------------------------------------------
# "Efficient number of mining bumps" — integration over the tracker +
# deposit_threshold to prove trip cost matches the extract_amount.
# ---------------------------------------------------------------------------


def _simulate_trip(
    tracker: CargoCapTracker,
    *,
    gear_sig: tuple[str, ...],
    extract_amount: int,
    true_cap: int,
    start_cargo: int = 0,
) -> tuple[int, int]:
    """Drive the tracker through one mining trip.

    Returns (bumps, final_cargo) where bumps = number of mine attempts that
    occurred before the tracker's known_cap(sig) made the agent stop.
    """
    cargo = start_cargo
    bumps = 0
    # First observation: arrive at extractor, haven't mined yet.
    tracker.observe(gear_sig=gear_sig, cargo=cargo, mined_last_tick=False)
    while True:
        known = tracker.known_cap(gear_sig)
        if known is not None and cargo >= known:
            return bumps, cargo
        # Attempt a mine. In the real game this costs one tick.
        bumps += 1
        cargo = min(cargo + extract_amount, true_cap)
        tracker.observe(gear_sig=gear_sig, cargo=cargo, mined_last_tick=True)


class TestMiningBumpEfficiency:
    @pytest.mark.parametrize(
        ("gear_sig", "extract_amount", "cap"),
        [
            ((), 1, 4),              # ungeared: cap 4, 1 per bump
            (("miner",), 10, 40),    # miner gear: cap 40, 10 per bump
            (("miner",), 5, 20),     # different hypothetical mission config
            (("aligner",), 2, 8),    # different gear, different cap
        ],
    )
    def test_trip_cost_after_discovery(self, gear_sig, extract_amount, cap):
        tracker = CargoCapTracker()

        # Discovery trip: should take cap/extract_amount successful bumps plus
        # one plateau bump to confirm the cap.
        bumps, final = _simulate_trip(
            tracker, gear_sig=gear_sig, extract_amount=extract_amount, true_cap=cap
        )
        expected_successful = cap // extract_amount
        assert final == cap
        assert bumps == expected_successful + 1, (
            f"discovery trip should take {expected_successful}+1 bumps, took {bumps}"
        )
        assert tracker.known_cap(gear_sig) == cap

        # Subsequent trips should take exactly cap/extract_amount bumps — no
        # wasted plateau bump because the cap is already known.
        for _ in range(3):
            bumps, final = _simulate_trip(
                tracker, gear_sig=gear_sig, extract_amount=extract_amount, true_cap=cap
            )
            assert final == cap
            assert bumps == expected_successful, (
                f"post-discovery trip should take exactly {expected_successful} "
                f"bumps, took {bumps}"
            )

    def test_two_gear_sets_discovered_independently(self):
        tracker = CargoCapTracker()
        # Trip without gear first.
        _simulate_trip(tracker, gear_sig=(), extract_amount=1, true_cap=4)
        assert tracker.known_cap(()) == 4
        # Switching to miner gear is a fresh discovery.
        _simulate_trip(tracker, gear_sig=("miner",), extract_amount=10, true_cap=40)
        assert tracker.known_cap(("miner",)) == 40
        # Both persist.
        assert tracker.known_cap(()) == 4
        assert tracker.known_cap(("miner",)) == 40


def test_discovery_callback_fires_once_on_new_cap():
    from cvc_policy.agent.cargo_cap import CargoCapTracker

    seen: list[tuple[tuple[str, ...], int]] = []
    tracker = CargoCapTracker(on_discovery=lambda sig, cap: seen.append((sig, cap)))
    # Simulate mining: cargo grows 0→10→20→30→40, then plateau at 40.
    for i, c in enumerate([0, 10, 20, 30, 40, 40]):
        tracker.observe(gear_sig=("miner",), cargo=c, mined_last_tick=i > 0)
    assert seen == [(("miner",), 40)]


def test_discovery_callback_not_refired_on_same_cap():
    from cvc_policy.agent.cargo_cap import CargoCapTracker

    seen: list[tuple[tuple[str, ...], int]] = []
    tracker = CargoCapTracker(on_discovery=lambda sig, cap: seen.append((sig, cap)))
    for i, c in enumerate([0, 10, 20, 30, 40, 40, 40]):
        tracker.observe(gear_sig=("miner",), cargo=c, mined_last_tick=i > 0)
    assert seen == [(("miner",), 40)]


def test_game_state_forwards_on_cargo_cap_discovery():
    """GameState should plumb on_cargo_cap_discovery into the CargoCapTracker."""
    from cvc_policy.game_state import GameState
    from tests.conftest import _fake_policy_env_info

    seen: list[tuple[tuple[str, ...], int]] = []
    gs = GameState(
        _fake_policy_env_info(),
        agent_id=0,
        on_cargo_cap_discovery=lambda sig, cap: seen.append((sig, cap)),
    )
    # Drive the tracker directly via the engine attribute — proves plumbing.
    for i, c in enumerate([0, 10, 20, 30, 40, 40]):
        gs.engine._cargo_cap.observe(
            gear_sig=("miner",), cargo=c, mined_last_tick=i > 0
        )
    assert seen == [(("miner",), 40)]
