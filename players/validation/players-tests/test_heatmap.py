from players.player_sdk.worldmodel.heatmap import DecayingHeatmap


def test_halflife_decay_preserves_split():
    h = DecayingHeatmap(cell=128, halflife=96)
    h.add((100, 100), 0)
    h.add((1200, 1200), 0)
    assert abs(h.frac_near((100, 100), 200, 0) - 0.5) < 1e-9
    assert abs(h.total(96) - 1.0) < 1e-9              # one half-life
    assert abs(h.frac_near((100, 100), 200, 96) - 0.5) < 1e-9


def test_quiet_map_reads_zero_not_elsewhere():
    h = DecayingHeatmap()
    assert h.frac_near((50, 50), 400, 10) == 0.0
    assert h.total(10) == 0.0


def test_near_radius_is_cell_granular():
    h = DecayingHeatmap(cell=100)
    h.add((50, 50), 0)
    h.add((950, 50), 0)
    assert h.near((50, 50), 99, 0) == 1.0
    assert h.near((50, 50), 2000, 0) == 2.0


def test_sparse_cells_are_pruned():
    h = DecayingHeatmap(halflife=10)
    for i in range(20):
        h.add((i * 500, 0), 0)
    assert len(h._cells) == 20
    h.total(1000)                                      # 100 half-lives
    assert not h._cells and h.total(1000) == 0.0


def test_monotone_clock_never_rewinds():
    h = DecayingHeatmap()
    h.add((0, 0), 100)
    before = h.total(100)
    assert h.total(50) == before                       # stale read: no rewind
