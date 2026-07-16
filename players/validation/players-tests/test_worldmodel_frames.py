"""Tests for players.player_sdk.worldmodel.frames.

FrameAnchor semantics from the original ``mas_memory.HubAnchor``; TeamFrame
scenarios adapted from the frame-conversion section of the
``dedicated_runtime.py`` smoke test, with the game-baked bootstrap offsets
injected by the test instead of hardcoded in the library.
"""

from __future__ import annotations

from players.player_sdk.worldmodel.frames import FrameAnchor, TeamFrame


def check(label: str, cond: bool, detail: str = "") -> None:
    assert cond, f"FAIL {label}: {detail}"


def test_frame_anchor_unanchored_returns_none() -> None:
    a = FrameAnchor()
    assert not a.is_anchored
    assert a.to_shared((3, 3)) is None
    assert a.to_local((3, 3)) is None


def test_frame_anchor_first_sighting_wins() -> None:
    a = FrameAnchor()
    a.try_anchor((2, 5))
    assert a.is_anchored and a.landmark_own_frame == (2, 5)
    a.try_anchor((9, 9))  # disagreeing later sighting is ignored
    assert a.landmark_own_frame == (2, 5)


def test_frame_anchor_round_trip() -> None:
    a = FrameAnchor()
    a.try_anchor((2, 5))
    for own in [(0, 0), (2, 5), (-3, 7), (10, 10)]:
        shared = a.to_shared(own)
        assert a.to_local(shared) == own
    # The landmark itself is shared (0, 0).
    assert a.to_shared((2, 5)) == (0, 0)


# Bootstrap offsets used by the original stack's smoke test: agent 0 spawns
# at landmark + (0, 3), agent 1 at landmark + (0, 2), etc.
BOOTSTRAP = {0: (0, 3), 1: (0, 2), 2: (0, 1), 3: (0, -1), 4: (0, -2), 5: (0, -3), 6: (1, 0), 7: (-1, 0)}


def test_team_frame_bootstrap_conversion() -> None:
    tf = TeamFrame(bootstrap=BOOTSTRAP)
    # 1. Agent 0's spawn (local (0,0)) -> shared equals its bootstrap offset.
    check(
        "1 agent 0 spawn -> shared is bootstrap",
        tf.to_shared(0, (0, 0)) == (0, 3),
        f"got {tf.to_shared(0, (0, 0))}",
    )
    # 2. Landmark in agent 0's local frame: (0, -3).
    check("2 agent 0 landmark_local", tf.landmark_local_for(0) == (0, -3))
    # 3. Round-trips for every agent.
    for aid in range(8):
        for local in [(0, 0), (5, -3), (-2, 7), (10, 10)]:
            shared = tf.to_shared(aid, local)
            back = tf.from_shared(aid, shared)
            check(f"3 round-trip a{aid} {local}", back == local, f"{shared} {back}")
    # 4. Two agents observing the same world cell agree in shared frame.
    s0 = tf.to_shared(0, (4, 1))
    s1 = tf.to_shared(1, (4, 2))
    check("4 cross-agent shared-frame agreement", s0 == s1, f"s0={s0} s1={s1}")
    check("4b shared coord matches world offset", s0 == (4, 4))


def test_team_frame_defaults_to_zero_offset() -> None:
    tf = TeamFrame()
    assert tf.offset_for(42) == (0, 0)
    assert tf.to_shared(42, (3, 4)) == (3, 4)


def test_team_frame_reanchor_verifies_and_overrides() -> None:
    events: list[tuple] = []
    tf = TeamFrame(
        bootstrap={0: (0, 3)},
        on_reanchor=lambda aid, old, new: events.append((aid, old, new)),
    )
    assert not tf.is_verified(0)
    # Sighting agrees with bootstrap: landmark at local (0, -3) -> offset (0, 3).
    tf.reanchor(0, (0, -3))
    assert tf.is_verified(0)
    assert events == []  # no override needed
    assert tf.offset_for(0) == (0, 3)
    # Agent 1 (bootstrap default (0,0)) actually sees the landmark at (5, 5):
    # derived offset (-5, -5) replaces the wrong default and fires the hook.
    tf.reanchor(1, (5, 5))
    assert tf.is_verified(1)
    assert events == [(1, (0, 0), (-5, -5))]
    assert tf.offset_for(1) == (-5, -5)
    # Conversions use the override from now on.
    assert tf.to_shared(1, (5, 5)) == (0, 0)  # the landmark is shared origin
