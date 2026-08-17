"""Adaptive fire control: rate learning, lattice parking, contract edges.

The scenarios mirror the live incident that motivated the component: a
game changed its rotation rate 8x with no config diff, and a hardcoded
controller oscillated forever. Every test drives the controller through
its public two-call contract (observe, then command)."""

import pytest

from players.player_sdk.fire_control import AdaptiveFireControl, circular_delta


def drive(fc, true_rate, desired, steps, held_ticks=1, freeze=False):
    """Simulate a game applying `true_rate` per held tick; returns the
    directions issued."""
    aim = fc.aim
    out = []
    for _ in range(steps):
        direction, _ = fc.command(desired, held_ticks)
        out.append(direction)
        if not freeze:
            aim = (aim + direction * true_rate * held_ticks) % fc.circle
        fc.observe(aim)
    return out


def test_learns_a_changed_rate_and_converges():
    fc = AdaptiveFireControl(circle=256, initial_rate=5)
    fc.observe(0)
    # the game actually rotates 40/tick now (the GV36 incident)
    drive(fc, true_rate=40, desired=127, steps=5)
    assert fc.rate == 40
    assert fc.lattice_spacing == 8 and fc.settle_band == 4


def test_parks_on_best_lattice_point_from_any_start():
    for start in range(0, 256, 17):
        fc = AdaptiveFireControl(circle=256, initial_rate=40)
        fc.observe(start)
        for _ in range(25):
            direction, err = fc.command(200)
            if direction == 0:
                break
            fc.observe((fc.aim) % 256)   # estimate is exact here
        else:
            pytest.fail(f"never parked from {start}")
        direction2, err2 = fc.command(200)
        assert direction2 == 0
        assert abs(err2) <= 4            # half the 8-unit lattice spacing


def test_windup_freeze_never_votes():
    fc = AdaptiveFireControl(circle=256, initial_rate=40)
    fc.observe(100)
    fc.command(0)
    fc.observe(100)                       # game froze the aim (windup lock)
    assert fc.rate == 40
    assert fc.aim == 100


def test_gap_discards_the_pending_sample():
    fc = AdaptiveFireControl(circle=256, initial_rate=5)
    fc.observe(0)
    fc.command(127)
    fc.observe(None)                      # death / dropped frame
    fc.observe(80)                        # rejoin at an arbitrary aim
    assert fc.rate == 5                   # the bracketing was broken: no vote


def test_generalizes_to_other_circles():
    # 360-degree game, 3 degrees/tick actual, wrong initial guess
    fc = AdaptiveFireControl(circle=360, initial_rate=1)
    fc.observe(0)
    drive(fc, true_rate=3, desired=179, steps=5)
    assert fc.rate == 3
    # and a coarse 32-position game
    fc2 = AdaptiveFireControl(circle=32, initial_rate=1, min_settle_band=0)
    fc2.observe(0)
    d, err = fc2.command(9)
    assert d == 1


def test_held_ticks_scale_the_plan():
    # deciding every 2 ticks at rate 5 = 10 units per command
    fc = AdaptiveFireControl(circle=256, initial_rate=5)
    fc.observe(0)
    direction, err = fc.command(3, held_ticks=2)
    # a 10-unit step past a 3-unit error is worse than holding
    assert direction == 0 and err == 3


def test_wrapping_walks_reach_hidden_lattice_points():
    # rate 40 on 256: +24 net requires seven wrapping steps; the greedy
    # single-step answer parks 24 away, the planner gets within 4
    fc = AdaptiveFireControl(circle=256, initial_rate=40)
    fc.observe(0)
    directions = drive(fc, true_rate=40, desired=24, steps=20)
    _, err = fc.command(24)
    assert abs(err) <= 4
    assert any(d != 0 for d in directions)


def test_circular_delta_convention():
    assert circular_delta(0, 128, 256) == -128   # opposite point maps negative
    assert circular_delta(0, 129, 256) == -127
    assert circular_delta(250, 6, 256) == 12
