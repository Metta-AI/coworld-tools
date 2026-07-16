"""Tests for the engine line-of-sight visibility computation
(players.player_sdk.nav_mesh.builder.visibility).

Ported 1:1 from swgy-crewrift ``packages/swgy-tools/tests/test_visibility.py``
(the SightParams defaults are the same reference-engine profile).
"""

from __future__ import annotations

import numpy as np

from players.player_sdk.nav_mesh.builder import visibility as vis


def test_tdiv_truncates_toward_zero():
    # The crux: Python floor-div would give -4 here; the engine's `div` gives -3.
    assert int(vis._tdiv(np.array(-7), 2)) == -3
    assert int(vis._tdiv(np.array(7), 2)) == 3
    assert int(vis._tdiv(np.array(0), 3)) == 0


def test_is_visible_clear_and_blocked():
    wall = np.zeros((200, 200), dtype=bool)
    # Clear line of sight across open floor (within the 128px frame).
    assert vis.is_visible(100, 100, 130, 100, wall)
    # A wall column between viewer and target blocks it.
    wall[:, 115] = True
    assert not vis.is_visible(100, 100, 130, 100, wall)
    # A target outside the 128px screen frame is never visible.
    assert not vis.is_visible(100, 100, 100, 199, np.zeros((200, 200), dtype=bool))


def test_is_visible_up_left_ray():
    # Up/left ray exercises the negative-numerator path (the _tdiv detail).
    wall = np.zeros((200, 200), dtype=bool)
    assert vis.is_visible(100, 100, 70, 70, wall)
    wall[85, 85] = True  # plant an occluder on the diagonal
    # Some pixel on the up-left diagonal is now blocked (engine-exact geometry).
    blocked_any = any(not vis.is_visible(100, 100, 100 - d, 100 - d, wall) for d in range(1, 31))
    assert blocked_any


def test_exposure_open_vs_boxed():
    wall = np.zeros((200, 200), dtype=bool)
    walk = np.ones((200, 200), dtype=bool)
    templates = vis.build_ray_templates()

    open_count = vis.exposure_counts([(100, 100)], wall, walk, templates)[0]
    assert open_count > 1000  # an open spot sees lots of floor

    boxed_wall = wall.copy()
    boxed_wall[99:102, 99:102] = True
    boxed_wall[100, 100] = False  # the node's own tile stays floor
    boxed_count = vis.exposure_counts([(100, 100)], boxed_wall, walk, templates)[0]
    assert boxed_count < 10  # walled-in: sees almost nothing
    assert open_count > boxed_count


def test_exposure_parallel_matches_serial():
    wall = np.zeros((200, 200), dtype=bool)
    wall[120:140, :] = True
    walk = np.ones((200, 200), dtype=bool)
    templates = vis.build_ray_templates()
    coords = [(80, 80), (100, 100), (60, 110), (130, 90)]
    serial = vis.exposure_counts(coords, wall, walk, templates, workers=1)
    parallel = vis.exposure_counts(coords, wall, walk, templates, workers=2)
    assert serial == parallel


def test_witness_counts_open_cluster():
    wall = np.zeros((200, 200), dtype=bool)
    coords = [(100, 100), (110, 100), (100, 110)]  # all mutually within frame, open
    counts = vis.witness_counts(coords, wall)
    assert counts == [2, 2, 2]  # each is seen by the other two


def test_visibility_matrix_matches_predicate_and_witnesses():
    wall = np.zeros((200, 200), dtype=bool)
    coords = [(100, 100), (110, 100), (100, 110), (180, 100)]  # 4th is out of frame
    m = vis.visibility_matrix(coords, wall, workers=1)
    n = len(coords)
    assert m.shape == (n, n)
    assert m.diagonal().all()  # everyone sees themselves
    # Every cell equals the engine predicate (viewer i -> target j).
    for i in range(n):
        for j in range(n):
            expected = i == j or vis.is_visible(*coords[i], *coords[j], wall)
            assert bool(m[i, j]) == expected
    # The far node is in nobody else's frame.
    assert not m[3, :3].any() and not m[:3, 3].any()
    # Column sums (minus self) reproduce witness_counts exactly.
    colsum = m.sum(axis=0) - 1
    assert list(colsum) == vis.witness_counts(coords, wall)


def test_visibility_matrix_blocked_by_wall():
    wall = np.zeros((200, 200), dtype=bool)
    coords = [(100, 100), (130, 100)]
    assert vis.visibility_matrix(coords, wall, workers=1)[0, 1]
    wall[:, 115] = True  # occluder between them
    assert not vis.visibility_matrix(coords, wall, workers=1)[0, 1]


def test_enrich_nodes_normalizes_and_counts():
    wall = np.zeros((200, 200), dtype=bool)
    walk = np.ones((200, 200), dtype=bool)
    # One open node and one boxed node.
    wall[59:62, 59:62] = True
    wall[60, 60] = False
    nodes = [
        {"id": 0, "x": 100, "y": 100, "tags": []},  # open
        {"id": 1, "x": 60, "y": 60, "tags": []},  # boxed-in
    ]
    enriched, stats = vis.enrich_nodes(nodes, wall, walk, workers=1)
    exps = {n["id"]: n["exposure"] for n in enriched}
    assert exps[0] == 1.0  # most-open node normalizes to 1.0
    assert 0.0 <= exps[1] < exps[0]
    assert all(isinstance(n["witnesses"], int) for n in enriched)
    assert stats["exposure_raw_max"] > 0
