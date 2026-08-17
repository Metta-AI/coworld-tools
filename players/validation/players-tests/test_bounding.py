import math
import random

from players.player_sdk.worldmodel.bounding import (
    MOVE, OVERWATCH, SOLO, WAIT_ACK, BoundingSM, pair_ranks)


def _cover(me, goal, bl):
    gx, gy = goal[0] - me[0], goal[1] - me[1]
    d = math.hypot(gx, gy) or 1.0
    if d <= bl:
        return goal
    return (me[0] + gx / d * bl, me[1] + gy / d * bl)


def _sm(rank=0, buddy=1, **kw):
    sm = BoundingSM(rank, buddy, **kw)
    sm.note_contact(0)
    return sm


def test_pair_ranks_xor():
    assert [pair_ranks(r) for r in range(8)] == [1, 0, 3, 2, 5, 4, 7, 6]


def test_handshake_happy_path():
    sent = []
    sm = _sm(0, 1)
    goal = (1000.0, 0.0)
    ov, hold = sm.step(0, (0, 0), goal, True, [], _cover,
                       lambda v, r: sent.append((v, r)))
    assert sm.state == WAIT_ACK and hold and sent == [("cover", 0)]
    ov, hold = sm.step(2, (0, 0), goal, True, [("got_u", 0, 2)], _cover,
                       lambda v, r: sent.append((v, r)))
    assert sm.state == MOVE and ov == (300.0, 0.0)
    ov, hold = sm.step(40, (280.0, 0.0), goal, True, [], _cover,
                       lambda v, r: sent.append((v, r)))
    assert sm.state == OVERWATCH and hold and sent[-1] == ("ready", 0)


def test_timeout_bounds_anyway():
    sm = _sm(0, 1, wait_ticks=36)
    goal = (1000.0, 0.0)
    sm.step(0, (0, 0), goal, True, [], _cover, lambda v, r: None)
    sm.step(35, (0, 0), goal, True, [], _cover, lambda v, r: None)
    assert sm.state == WAIT_ACK
    ov, _ = sm.step(36, (0, 0), goal, True, [], _cover, lambda v, r: None)
    assert sm.state == MOVE and ov is not None and sm.dbg["timeouts"] == 1


def test_overwatch_acks_and_takes_turn():
    sent = []
    sm = _sm(1, 0)
    goal = (1000.0, 0.0)
    _, hold = sm.step(0, (0, 0), goal, True, [], _cover,
                      lambda v, r: sent.append((v, r)))
    assert sm.state == OVERWATCH and hold
    sm.step(5, (0, 0), goal, True, [("cover", 0, 5)], _cover,
            lambda v, r: sent.append((v, r)))
    assert sent[-1] == ("got_u", 0)
    ov, _ = sm.step(60, (0, 0), goal, True, [("ready", 0, 60)], _cover,
                    lambda v, r: sent.append((v, r)))
    assert sm.state == MOVE and ov is not None and sent[-1] == ("bound", 1)


def test_cold_or_dead_buddy_goes_solo():
    sm = _sm(0, 1)
    goal = (1000.0, 0.0)
    sm.step(0, (0, 0), goal, True, [], _cover, lambda v, r: None)
    ov, hold = sm.step(200, (0, 0), goal, False, [], _cover, lambda v, r: None)
    assert sm.state == SOLO and ov is None and not hold
    sm2 = _sm(0, 1, dead_ticks=180)
    sm2.note_buddy_sign(0)
    ov, hold = sm2.step(400, (0, 0), goal, True, [], _cover, lambda v, r: None)
    assert sm2.state == SOLO and ov is None and not hold


def test_progress_guard_forfeits_bounding():
    sm = _sm(0, 1)
    goal = (5000.0, 0.0)
    for t in range(0, 700, 2):
        sm.note_contact(t)
        sm.step(t, (0, 0), goal, True, [], _cover, lambda v, r: None)
    assert sm.dbg["solo_progress"] >= 1


def test_no_starvation_fuzz():
    rng = random.Random(7)
    for trial in range(50):
        r = rng.randint(0, 1)
        sm = BoundingSM(r, r ^ 1, wait_ticks=24, dead_ticks=120,
                        contested_ticks=90)
        goal = (2000.0, 0.0)
        me = [0.0, 0.0]
        last_live = 0
        for t in range(0, 1200, 2):
            if rng.random() < 0.4:
                sm.note_contact(t)
            inbox = []
            if rng.random() < 0.15:
                inbox.append((rng.choice(["cover", "got_u", "ready", "bound"]),
                              rng.randint(0, 1), t))
            ov, _hold = sm.step(t, tuple(me), goal, rng.random() < 0.5,
                                inbox, _cover, lambda v, rk: None)
            if ov is not None:
                me[0] = min(goal[0], me[0] + 40)
            if sm.state in (MOVE, SOLO) or ov is not None:
                last_live = t
            assert t - last_live <= 3 * 24 + 8, \
                f"trial {trial}: starved at t={t} in {sm.state}"
