"""Tests for dynamic heart-cap discovery.

Aligners pick up hearts at the hub and deliver them to junctions. The
heart-cap tracker watches (gear_sig, heart_count, attempted_pickup) tuples
across ticks and infers the carry limit when a pickup attempt does not
increase heart_count.

Mirrors the structure of tests/agent/test_cargo_cap.py exactly.
"""

from __future__ import annotations

from cvc_policy.agent.heart_cap import HeartCapTracker


# ---------------------------------------------------------------------------
# Basic tracker behavior
# ---------------------------------------------------------------------------


class TestHeartCapTracker:
    def test_empty_tracker_has_no_cap(self):
        tracker = HeartCapTracker()
        assert tracker.known_cap(("aligner",)) is None

    def test_single_successful_pickup_does_not_set_cap(self):
        tracker = HeartCapTracker()
        tracker.observe(gear_sig=("aligner",), hearts=0, tried_pickup_last_tick=False)
        tracker.observe(gear_sig=("aligner",), hearts=1, tried_pickup_last_tick=True)
        assert tracker.known_cap(("aligner",)) is None

    def test_plateau_after_pickup_sets_cap(self):
        tracker = HeartCapTracker()
        tracker.observe(gear_sig=("aligner",), hearts=0, tried_pickup_last_tick=False)
        tracker.observe(gear_sig=("aligner",), hearts=1, tried_pickup_last_tick=True)
        tracker.observe(gear_sig=("aligner",), hearts=2, tried_pickup_last_tick=True)
        tracker.observe(gear_sig=("aligner",), hearts=3, tried_pickup_last_tick=True)
        # Next pickup attempt fails — hearts stay at 3 → cap discovered.
        tracker.observe(gear_sig=("aligner",), hearts=3, tried_pickup_last_tick=True)
        assert tracker.known_cap(("aligner",)) == 3

    def test_heart_cap_bumps_then_plateau_sets_cap(self):
        """Scripted 0→1→2→3→3 transition asserts cap=3 for ('aligner',)."""
        tracker = HeartCapTracker()
        for i, h in enumerate([0, 1, 2, 3, 3]):
            tracker.observe(
                gear_sig=("aligner",), hearts=h, tried_pickup_last_tick=i > 0
            )
        assert tracker.known_cap(("aligner",)) == 3

    def test_plateau_without_pickup_attempt_does_not_set_cap(self):
        tracker = HeartCapTracker()
        tracker.observe(gear_sig=("aligner",), hearts=2, tried_pickup_last_tick=False)
        tracker.observe(gear_sig=("aligner",), hearts=2, tried_pickup_last_tick=False)
        tracker.observe(gear_sig=("aligner",), hearts=2, tried_pickup_last_tick=False)
        assert tracker.known_cap(("aligner",)) is None

    def test_cap_is_per_gear_signature(self):
        tracker = HeartCapTracker()
        for i, h in enumerate([0, 1, 2, 2]):
            tracker.observe(
                gear_sig=(), hearts=h, tried_pickup_last_tick=i > 0
            )
        assert tracker.known_cap(()) == 2
        assert tracker.known_cap(("aligner",)) is None

    def test_cap_survives_gear_switch(self):
        tracker = HeartCapTracker()
        for i, h in enumerate([0, 1, 2, 2]):
            tracker.observe(gear_sig=(), hearts=h, tried_pickup_last_tick=i > 0)
        tracker.observe(
            gear_sig=("aligner",), hearts=0, tried_pickup_last_tick=False
        )
        assert tracker.known_cap(()) == 2

    def test_drop_after_delivery_does_not_shrink_known_cap(self):
        tracker = HeartCapTracker()
        for i, h in enumerate([0, 1, 2, 3, 3]):
            tracker.observe(
                gear_sig=("aligner",), hearts=h, tried_pickup_last_tick=i > 0
            )
        assert tracker.known_cap(("aligner",)) == 3
        # Deliver — hearts drop.
        tracker.observe(
            gear_sig=("aligner",), hearts=0, tried_pickup_last_tick=False
        )
        # Pick up, then false plateau at 1.
        tracker.observe(
            gear_sig=("aligner",), hearts=1, tried_pickup_last_tick=True
        )
        tracker.observe(
            gear_sig=("aligner",), hearts=1, tried_pickup_last_tick=True
        )
        assert tracker.known_cap(("aligner",)) == 3


# ---------------------------------------------------------------------------
# Discovery callback
# ---------------------------------------------------------------------------


def test_discovery_callback_fires_once_on_new_cap():
    seen: list[tuple[tuple[str, ...], int]] = []
    tracker = HeartCapTracker(on_discovery=lambda sig, cap: seen.append((sig, cap)))
    for i, h in enumerate([0, 1, 2, 3, 3]):
        tracker.observe(
            gear_sig=("aligner",), hearts=h, tried_pickup_last_tick=i > 0
        )
    assert seen == [(("aligner",), 3)]


def test_discovery_callback_not_refired_on_same_cap():
    seen: list[tuple[tuple[str, ...], int]] = []
    tracker = HeartCapTracker(on_discovery=lambda sig, cap: seen.append((sig, cap)))
    for i, h in enumerate([0, 1, 2, 3, 3, 3]):
        tracker.observe(
            gear_sig=("aligner",), hearts=h, tried_pickup_last_tick=i > 0
        )
    assert seen == [(("aligner",), 3)]
