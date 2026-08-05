"""Tests for players.player_sdk.nav_mesh (model / io / A* / follower).

Ported from swgy-crewrift ``packages/swgy-base/tests/test_nav.py``. The
handful of tests that exercised the vendored Croatoan map asset (not shipped
here) are dropped or rebuilt on synthetic fixtures; everything else is 1:1.
"""

from __future__ import annotations

import base64
import json
import math
import struct
import zlib

import numpy as np
import pytest

from players.player_sdk import nav_mesh as nav
from players.player_sdk.nav_mesh import io
from players.player_sdk.nav_mesh.params import NavParams
from players.player_sdk.nav_mesh.plan import NavPlan


def _interchange() -> dict:
    # 4x3 walkability: row 0 fully walkable, the rest blocked except (1, 2).
    mask = np.zeros((3, 4), dtype=bool)
    mask[0, :] = True
    mask[2, 1] = True
    bits = np.packbits(mask.reshape(-1), bitorder="little").tobytes()
    return {
        "format": io.INTERCHANGE_FORMAT,
        "version": 1,
        "map": {"width": 4, "height": 3, "void_rgba": [29, 43, 83, 255], "source": "sprite:map"},
        "density": {"grid": 1, "edge_max": 3, "node_clear": 0, "edge_clear": 0},
        "walk_bits_b64": base64.b64encode(bits).decode("ascii"),
        "nodes": [
            {"id": 0, "x": 0, "y": 0, "tags": ["room:Cafeteria"]},
            {"id": 1, "x": 3, "y": 0, "tags": ["corridor"]},
            {"id": 2, "x": 1, "y": 2, "tags": []},
        ],
        "edges": [
            {"src": 0, "dst": 1, "weight": 3.0, "directed": False, "tags": ["walk"]},
            {"src": 1, "dst": 2, "weight": 5.5, "directed": True, "tags": ["walk", "door"]},
        ],
        "tasks": [
            {"id": 0, "x": 3, "y": 0, "room": "Cafeteria", "name": "wires"},
            {"id": 1, "x": 1, "y": 2, "room": None, "name": "task"},
        ],
        "vents": [
            {"id": 0, "x": 0, "y": 0, "room": "Cafeteria", "group": "vent:1"},
            {"id": 1, "x": 1, "y": 2, "room": None, "group": "vent:2"},
        ],
        "provenance": {"by": "test"},
    }


# --- NavGrid --------------------------------------------------------------


def test_grid_from_mask_roundtrip_and_walkable():
    mask = np.zeros((3, 4), dtype=bool)
    mask[0, :] = True
    mask[2, 1] = True
    grid = nav.NavGrid.from_mask(mask)
    assert (grid.width, grid.height) == (4, 3)
    assert grid.is_walkable(0, 0) and grid.is_walkable(3, 0)
    assert grid.is_walkable(1, 2)
    assert not grid.is_walkable(0, 1)
    assert not grid.is_walkable(-1, 0) and not grid.is_walkable(4, 0)
    assert np.array_equal(grid.to_mask(), mask)


def test_grid_rejects_wrong_length():
    with pytest.raises(ValueError, match="bits length"):
        nav.NavGrid(width=4, height=3, bits=b"\x00")


# --- interchange ----------------------------------------------------------


def test_mesh_from_interchange_builds_model():
    mesh = nav.mesh_from_interchange(_interchange())
    assert len(mesh) == 3
    assert mesh.node(0).tags == frozenset({"room:Cafeteria"})
    assert mesh.is_walkable(1, 2) and not mesh.is_walkable(2, 2)
    assert mesh.nodes_with_tag("room:Cafeteria") == [mesh.node(0)]


def test_interchange_reads_vents():
    mesh = nav.mesh_from_interchange(_interchange())
    assert [(v.id, v.x, v.y, v.room, v.group) for v in mesh.vents] == [
        (0, 0, 0, "Cafeteria", "vent:1"),
        (1, 1, 2, None, "vent:2"),
    ]
    # A mesh with no vents key stays empty (backward compatible).
    obj = _interchange()
    del obj["vents"]
    assert nav.mesh_from_interchange(obj).vents == []


def test_interchange_rejects_bad_format():
    with pytest.raises(ValueError, match="not a nav interchange"):
        nav.mesh_from_interchange({"format": "nope"})


def test_neighbors_directed_vs_undirected():
    mesh = nav.mesh_from_interchange(_interchange())
    # Edge 0-1 undirected: both directions present.
    assert any(n == 1 for n, _w, _t in mesh.neighbors(0))
    assert any(n == 0 for n, _w, _t in mesh.neighbors(1))
    # Edge 1->2 directed: only forward.
    assert any(n == 2 for n, _w, _t in mesh.neighbors(1))
    assert all(n != 1 for n, _w, _t in mesh.neighbors(2))


def test_nearest_node():
    mesh = nav.mesh_from_interchange(_interchange())
    assert mesh.nearest_node(0, 0) == 0
    assert mesh.nearest_node(3, 1) == 1  # closest to (3,0)
    assert mesh.nearest_node(1, 3) == 2


# --- canonical I/O --------------------------------------------------------


def test_save_load_roundtrip(tmp_path):
    mesh = nav.mesh_from_interchange(_interchange())
    walk = tmp_path / "c.walk"
    graph = tmp_path / "c.graph"
    nav.save_mesh(mesh, walk, graph)
    rt = nav.load_mesh(walk, graph)

    assert len(rt) == len(mesh)
    assert np.array_equal(rt.grid.to_mask(), mesh.grid.to_mask())
    assert {n.id: n.tags for n in rt.nodes} == {n.id: n.tags for n in mesh.nodes}
    assert [(e.src, e.dst, e.weight, e.directed, e.tags) for e in rt.edges] == [
        (e.src, e.dst, e.weight, e.directed, e.tags) for e in mesh.edges
    ]
    assert [(t.id, t.x, t.y, t.room, t.name) for t in rt.tasks] == [
        (0, 3, 0, "Cafeteria", "wires"),
        (1, 1, 2, None, "task"),
    ]
    assert [(v.id, v.x, v.y, v.room, v.group) for v in rt.vents] == [
        (0, 0, 0, "Cafeteria", "vent:1"),
        (1, 1, 2, None, "vent:2"),
    ]
    assert rt.meta["density"]["grid"] == 1


# --- task-arrow query -----------------------------------------------------


def test_points_toward_cone_and_ranking():
    origin = (0, 0)
    bearing = (1, 0)  # pointing +x
    cands = [(10, 0), (10, 1), (0, 10), (-10, 0), (5, 0)]
    out = nav.points_toward(origin, bearing, cands, half_angle_deg=20)
    assert (0, 10) not in out and (-10, 0) not in out  # outside the cone
    # Equally-aligned (5,0) and (10,0) rank nearest-first; (10,1) is off-axis.
    assert out == [(5, 0), (10, 0), (10, 1)]


def test_points_toward_max_dist():
    out = nav.points_toward((0, 0), (1, 0), [(5, 0), (50, 0)], max_dist=10)
    assert out == [(5, 0)]


def test_tasks_toward_picks_arrow_target():
    mesh = nav.mesh_from_interchange(_interchange())
    # task 0 is at (3,0); from origin (0,0) the arrow bearing points +x.
    target = mesh.tasks[0]
    out = mesh.tasks_toward((0, 0), (3, 0), half_angle_deg=20)
    assert out and out[0].id == target.id
    assert mesh.task_node(target) is not None


# --- visibility (exposure / witnesses) ------------------------------------


def test_interchange_reads_visibility():
    obj = _interchange()
    obj["nodes"][0]["exposure"] = 0.25
    obj["nodes"][0]["witnesses"] = 4
    mesh = nav.mesh_from_interchange(obj)
    assert mesh.node(0).exposure == pytest.approx(0.25)
    assert mesh.node(0).witnesses == 4
    # Nodes without the fields stay None (backward compatible).
    assert mesh.node(1).exposure is None and mesh.node(1).witnesses is None


def test_roundtrip_preserves_visibility(tmp_path):
    base = nav.mesh_from_interchange(_interchange())
    vis = {0: (0.0, 3), 1: (0.5, 0)}  # node 2 left as (None, None)
    nodes = [
        nav.NavNode(
            id=n.id,
            x=n.x,
            y=n.y,
            tags=n.tags,
            exposure=vis.get(n.id, (None, None))[0],
            witnesses=vis.get(n.id, (None, None))[1],
        )
        for n in base.nodes
    ]
    mesh = nav.NavMesh(base.grid, nodes, base.edges, base.meta, base.tasks)
    walk, graph = tmp_path / "c.walk", tmp_path / "c.graph"
    nav.save_mesh(mesh, walk, graph)
    rt = nav.load_mesh(walk, graph)

    got = {n.id: (n.exposure, n.witnesses) for n in rt.nodes}
    assert got[0] == (pytest.approx(0.0), 3)
    assert got[1] == (pytest.approx(0.5), 0)
    assert got[2] == (None, None)  # NaN/sentinel decode back to None


def _v2_graph_bytes(mesh) -> bytes:
    """A pre-visibility (version 2) graph file: nodes are id/x/y + tags only."""
    table: list[str] = []
    index: dict[str, int] = {}

    def intern(s: str) -> int:
        if s not in index:
            index[s] = len(table)
            table.append(s)
        return index[s]

    for tagset in [n.tags for n in mesh.nodes] + [e.tags for e in mesh.edges]:
        for t in tagset:
            intern(t)
    for t in mesh.tasks:
        if t.room is not None:
            intern(t.room)
        if t.name:
            intern(t.name)

    def pack_tags(tags):
        ids = sorted(index[t] for t in tags)
        return struct.pack("<H", len(ids)) + b"".join(struct.pack("<H", i) for i in ids)

    out = bytearray(struct.pack("<H", len(table)))
    for s in table:
        raw = s.encode("utf-8")
        out += struct.pack("<H", len(raw)) + raw
    out += struct.pack("<I", len(mesh.nodes))
    for n in mesh.nodes:
        out += struct.pack("<Iii", n.id, n.x, n.y) + pack_tags(n.tags)  # v2: no exposure
    out += struct.pack("<I", len(mesh.edges))
    for e in mesh.edges:
        out += struct.pack("<IIfB", e.src, e.dst, e.weight, 1 if e.directed else 0)
        out += pack_tags(e.tags)
    out += struct.pack("<I", len(mesh.tasks))
    for t in mesh.tasks:
        room = index[t.room] if t.room is not None else 0xFFFF
        name = index[t.name] if t.name else 0xFFFF
        out += struct.pack("<IiiHH", t.id, t.x, t.y, room, name)
    meta_raw = json.dumps(mesh.meta, sort_keys=True).encode("utf-8")
    out += struct.pack("<I", len(meta_raw)) + meta_raw

    body = zlib.compress(bytes(out), 9)
    return struct.pack("<8sHI", b"SWGYGRAF", 2, len(body)) + body


def test_loads_legacy_v2_graph(tmp_path):
    mesh = nav.mesh_from_interchange(_interchange())
    walk, graph = tmp_path / "c.walk", tmp_path / "c.graph"
    nav.save_grid(mesh.grid, walk)  # grid body is version-agnostic
    graph.write_bytes(_v2_graph_bytes(mesh))

    rt = nav.load_mesh(walk, graph)
    assert len(rt) == len(mesh)
    assert {n.id: n.tags for n in rt.nodes} == {n.id: n.tags for n in mesh.nodes}
    assert all(n.exposure is None and n.witnesses is None for n in rt.nodes)
    assert rt.vents == []  # pre-v4 files have no vents section


def _v3_graph_bytes(mesh) -> bytes:
    """A pre-vents (version 3) graph: vis nodes + tasks, but no vents section."""
    table: list[str] = []
    index: dict[str, int] = {}

    def intern(s: str) -> int:
        if s not in index:
            index[s] = len(table)
            table.append(s)
        return index[s]

    for tagset in [n.tags for n in mesh.nodes] + [e.tags for e in mesh.edges]:
        for t in tagset:
            intern(t)
    for t in mesh.tasks:
        if t.room is not None:
            intern(t.room)
        if t.name:
            intern(t.name)

    def pack_tags(tags):
        ids = sorted(index[t] for t in tags)
        return struct.pack("<H", len(ids)) + b"".join(struct.pack("<H", i) for i in ids)

    out = bytearray(struct.pack("<H", len(table)))
    for s in table:
        raw = s.encode("utf-8")
        out += struct.pack("<H", len(raw)) + raw
    out += struct.pack("<I", len(mesh.nodes))
    for n in mesh.nodes:  # v3: id, x, y, exposure:f32, witnesses:u32
        out += struct.pack("<IiifI", n.id, n.x, n.y, float("nan"), 0xFFFFFFFF) + pack_tags(n.tags)
    out += struct.pack("<I", len(mesh.edges))
    for e in mesh.edges:
        out += struct.pack("<IIfB", e.src, e.dst, e.weight, 1 if e.directed else 0)
        out += pack_tags(e.tags)
    out += struct.pack("<I", len(mesh.tasks))
    for t in mesh.tasks:
        room = index[t.room] if t.room is not None else 0xFFFF
        name = index[t.name] if t.name else 0xFFFF
        out += struct.pack("<IiiHH", t.id, t.x, t.y, room, name)
    meta_raw = json.dumps(mesh.meta, sort_keys=True).encode("utf-8")
    out += struct.pack("<I", len(meta_raw)) + meta_raw

    body = zlib.compress(bytes(out), 9)
    return struct.pack("<8sHI", b"SWGYGRAF", 3, len(body)) + body


def test_loads_v3_graph_without_vents(tmp_path):
    mesh = nav.mesh_from_interchange(_interchange())
    walk, graph = tmp_path / "c.walk", tmp_path / "c.graph"
    nav.save_grid(mesh.grid, walk)
    graph.write_bytes(_v3_graph_bytes(mesh))

    rt = nav.load_mesh(walk, graph)
    assert [(t.id, t.x, t.y) for t in rt.tasks] == [(0, 3, 0), (1, 1, 2)]  # tasks intact
    assert rt.vents == []  # v3 reader path yields no vents, meta still decodes
    assert rt.meta["density"]["grid"] == 1


# --- visibility query interface -------------------------------------------


def _vis_mesh() -> nav.NavMesh:
    """Open grid with three nodes: a hidden one, a mid one, an open one."""
    grid = nav.NavGrid.from_mask(np.ones((64, 64), dtype=bool))
    nodes = [
        nav.NavNode(id=0, x=5, y=5, exposure=0.1, witnesses=2),
        nav.NavNode(id=1, x=30, y=30, exposure=0.5, witnesses=8),
        nav.NavNode(id=2, x=60, y=60, exposure=0.9, witnesses=20),
    ]
    return nav.NavMesh(grid, nodes, [])


def test_has_visibility_flag():
    assert not nav.mesh_from_interchange(_interchange()).has_visibility
    assert _vis_mesh().has_visibility


def test_visibility_at_snaps_to_nearest_node():
    mesh = _vis_mesh()
    r = mesh.visibility_at(7, 6)  # nearest to node 0 at (5,5)
    assert isinstance(r, nav.VisReading)
    assert r.node_id == 0
    assert r.exposure == pytest.approx(0.1)
    assert r.witnesses == 2
    assert r.restriction == pytest.approx(0.9)
    assert r.distance == pytest.approx(np.hypot(2, 1))


def test_exposure_and_witnesses_shortcuts():
    mesh = _vis_mesh()
    assert mesh.exposure_at(31, 29) == pytest.approx(0.5)  # near node 1
    assert mesh.witnesses_at(31, 29) == 8


def test_visibility_queries_none_without_data():
    mesh = nav.mesh_from_interchange(_interchange())  # no baked visibility
    assert mesh.visibility_at(0, 0) is None
    assert mesh.exposure_at(0, 0) is None
    assert mesh.witnesses_at(0, 0) is None
    # An empty mesh has nothing to resolve to.
    empty = nav.NavMesh(nav.NavGrid.from_mask(np.ones((4, 4), bool)), [], [])
    assert not empty.has_visibility
    assert empty.visibility_at(0, 0) is None


def test_nodes_by_exposure_filters_both_bounds():
    mesh = _vis_mesh()
    assert [n.id for n in mesh.nodes_by_exposure(max_exposure=0.3)] == [0]  # cover
    assert [n.id for n in mesh.nodes_by_exposure(min_exposure=0.7)] == [2]  # open
    mid = mesh.nodes_by_exposure(min_exposure=0.2, max_exposure=0.6)
    assert [n.id for n in mid] == [1]
    # Nodes lacking visibility data are skipped.
    assert nav.mesh_from_interchange(_interchange()).nodes_by_exposure(max_exposure=1.0) == []


def test_load_rejects_bad_walk_magic(tmp_path):
    p = tmp_path / "bad.walk"
    p.write_bytes(b"XXXXXXXX" + b"\x00" * 16)
    with pytest.raises(ValueError, match="bad walk magic"):
        nav.load_grid(p)


def test_load_rejects_bad_graph_magic(tmp_path):
    mesh = nav.mesh_from_interchange(_interchange())
    walk = tmp_path / "c.walk"
    graph = tmp_path / "c.graph"
    nav.save_mesh(mesh, walk, graph)
    graph.write_bytes(b"BADMAGIC" + graph.read_bytes()[8:])
    with pytest.raises(ValueError, match="bad graph magic"):
        nav.load_mesh(walk, graph)


# --- rooms ----------------------------------------------------------------


def _room_mesh() -> nav.NavMesh:
    """A tiny mesh whose nodes carry ``room:`` tags (plus noise tags)."""
    grid = nav.NavGrid.from_mask(np.ones((64, 64), dtype=bool))
    nodes = [
        nav.NavNode(id=0, x=10, y=10, tags=frozenset({"room:Bridge", "walk"})),
        nav.NavNode(id=1, x=20, y=30, tags=frozenset({"room:Bridge"})),
        nav.NavNode(id=2, x=40, y=40, tags=frozenset({"room:Reactor", "vent"})),
        nav.NavNode(id=3, x=50, y=50, tags=frozenset({"walk"})),  # no room -> ignored
        nav.NavNode(id=4, x=60, y=60, tags=frozenset({"room:"})),  # empty name -> ignored
    ]
    return nav.NavMesh(grid, nodes, [])


def test_rooms_lists_distinct_names_sorted():
    assert _room_mesh().rooms() == ["Bridge", "Reactor"]  # empty/untagged skipped


def test_room_nodes_and_centroid_is_mean():
    mesh = _room_mesh()
    assert {n.id for n in mesh.room_nodes("Bridge")} == {0, 1}
    assert mesh.room_centroid("Bridge") == (15, 20)  # mean of (10,10),(20,30)
    assert mesh.room_centroid("Reactor") == (40, 40)  # single node


def test_room_centroids_maps_all_rooms():
    assert _room_mesh().room_centroids() == {"Bridge": (15, 20), "Reactor": (40, 40)}


def test_room_queries_robust_to_missing_and_untagged():
    mesh = _room_mesh()
    assert mesh.room_centroid("Cafeteria") is None  # unknown room, no raise
    assert mesh.room_nodes("Cafeteria") == []
    # A mesh rebuilt from a bare walk grid carries no room tags -> everything empty.
    untagged = _mesh([(0, 0, 0), (1, 10, 10)], [])
    assert untagged.rooms() == []
    assert untagged.room_centroids() == {}
    assert untagged.room_centroid("Bridge") is None
    # An empty mesh is fine too.
    assert nav.NavMesh(nav.NavGrid.from_mask(np.ones((4, 4), bool)), [], []).rooms() == []


def test_room_graph_quotient_adjacency():
    # A -corridor- B -longer- C: rooms connect only through corridor nodes, which get
    # claimed by their nearest room, making the bordering rooms adjacent.
    grid = nav.NavGrid.from_mask(np.ones((64, 64), dtype=bool))
    nodes = [
        nav.NavNode(0, 0, 0, frozenset({"room:A"})),
        nav.NavNode(1, 10, 0, frozenset()),  # corridor -> nearest A
        nav.NavNode(2, 20, 0, frozenset()),  # corridor -> nearest B
        nav.NavNode(3, 30, 0, frozenset({"room:B"})),
        nav.NavNode(4, 30, 40, frozenset({"room:C"})),
    ]
    edges = [
        nav.NavEdge(0, 1, 10.0),
        nav.NavEdge(1, 2, 10.0),
        nav.NavEdge(2, 3, 10.0),
        nav.NavEdge(3, 4, 40.0),
    ]
    g = nav.NavMesh(grid, nodes, edges).room_graph()
    assert g == {"A": {"B"}, "B": {"A", "C"}, "C": {"B"}}


def test_room_graph_empty_when_untagged():
    # No room tags (rebuilt-from-walk-grid case) -> empty graph, no raise.
    assert _mesh([(0, 0, 0), (1, 10, 10)], [(0, 1, 14.0)]).room_graph() == {}


def test_room_graph_symmetric_and_self_loop_free():
    # Symmetry/self-loop invariants on a synthetic three-room ring.
    grid = nav.NavGrid.from_mask(np.ones((64, 64), dtype=bool))
    nodes = [
        nav.NavNode(0, 0, 0, frozenset({"room:A"})),
        nav.NavNode(1, 20, 0, frozenset({"room:B"})),
        nav.NavNode(2, 10, 20, frozenset({"room:C"})),
    ]
    edges = [nav.NavEdge(0, 1, 20.0), nav.NavEdge(1, 2, 22.0), nav.NavEdge(2, 0, 22.0)]
    g = nav.NavMesh(grid, nodes, edges).room_graph()
    assert set(g) == {"A", "B", "C"}
    assert all(r not in nbrs for r, nbrs in g.items())  # no self-loops
    for a, nbrs in g.items():
        for b in nbrs:
            assert a in g[b]  # symmetric


# --- A* routing -----------------------------------------------------------


def _mesh(nodes, edges, *, w=64, h=64) -> nav.NavMesh:
    """A NavMesh from (id, x, y) nodes and (src, dst, weight[, directed, tags])
    edges over a fully-walkable wxh grid."""
    grid = nav.NavGrid.from_mask(np.ones((h, w), dtype=bool))
    ns = [nav.NavNode(id=i, x=x, y=y) for i, x, y in nodes]
    es = [
        nav.NavEdge(
            src=e[0],
            dst=e[1],
            weight=e[2],
            directed=e[3] if len(e) > 3 else False,
            tags=frozenset(e[4]) if len(e) > 4 else frozenset(),
        )
        for e in edges
    ]
    return nav.NavMesh(grid, ns, es)


def test_find_path_straight_line():
    mesh = _mesh([(0, 0, 0), (1, 10, 0), (2, 20, 0)], [(0, 1, 10.0), (1, 2, 10.0)])
    plan = nav.find_path(mesh, 0, 2)
    assert plan is not None
    assert plan.nodes == (0, 1, 2)
    assert plan.waypoints == ((0, 0), (10, 0), (20, 0))
    assert plan.cost == pytest.approx(20.0)
    assert plan.goal == 2


def test_find_path_detour_when_no_direct_edge():
    # Square 0-1-3 and 0-2-3, but no direct 0-3 edge.
    mesh = _mesh(
        [(0, 0, 0), (1, 10, 0), (2, 0, 10), (3, 10, 10)],
        [(0, 1, 10.0), (1, 3, 10.0), (0, 2, 10.0), (2, 3, 10.0)],
    )
    plan = nav.find_path(mesh, 0, 3)
    assert plan is not None and plan.nodes[0] == 0 and plan.nodes[-1] == 3
    assert len(plan) == 3  # one intermediate node
    assert plan.cost == pytest.approx(20.0)


def test_find_path_unreachable_returns_none():
    mesh = _mesh([(0, 0, 0), (1, 10, 0), (9, 40, 40)], [(0, 1, 10.0)])
    assert nav.find_path(mesh, 0, 9) is None


def test_find_path_start_equals_goal():
    mesh = _mesh([(0, 5, 5), (1, 10, 0)], [(0, 1, 11.0)])
    plan = nav.find_path(mesh, 0, 0)
    assert plan is not None
    assert plan.nodes == (0,) and plan.waypoints == ((5, 5),)
    assert plan.cost == 0.0


def test_find_path_respects_directed_edges():
    mesh = _mesh([(0, 0, 0), (1, 10, 0)], [(0, 1, 10.0, True)])  # 0 -> 1 only
    assert nav.find_path(mesh, 0, 1) is not None
    assert nav.find_path(mesh, 1, 0) is None


def test_find_path_soft_tag_avoidance():
    # Cheap tagged shortcut (5) vs clean detour (6+6=12).
    mesh = _mesh(
        [(0, 0, 0), (1, 20, 0), (2, 0, 10)],
        [(0, 1, 5.0, False, ["vent"]), (0, 2, 6.0), (2, 1, 6.0)],
    )
    assert nav.find_path(mesh, 0, 1).nodes == (0, 1)  # default: take the shortcut
    avoid = NavParams(avoid_tags=frozenset({"vent"}), avoid_penalty=50.0)
    assert nav.find_path(mesh, 0, 1, avoid).nodes == (0, 2, 1)  # routed around it


def test_find_path_hard_avoidance_prunes_only_bridge():
    mesh = _mesh([(0, 0, 0), (1, 20, 0)], [(0, 1, 5.0, False, ["vent"])])
    params = NavParams(avoid_tags=frozenset({"vent"}), allow_avoided=False)
    assert nav.find_path(mesh, 0, 1, params) is None


def test_find_path_snaps_coordinate_inputs():
    mesh = _mesh([(0, 0, 0), (1, 10, 0), (2, 20, 0)], [(0, 1, 10.0), (1, 2, 10.0)])
    plan = nav.find_path(mesh, (1, 1), (19, 2))  # near nodes 0 and 2
    assert plan is not None and plan.nodes == (0, 1, 2)


def test_find_path_weighted_heuristic_still_connects():
    mesh = _mesh(
        [(0, 0, 0), (1, 10, 0), (2, 20, 0), (3, 30, 0)],
        [(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0)],
    )
    plan = nav.find_path(mesh, 0, 3, NavParams(heuristic_weight=3.0))
    assert plan is not None and plan.nodes[0] == 0 and plan.nodes[-1] == 3


def test_diagonal_bias_costs_edge_by_travel_time():
    # A 45-deg edge: its Euclidean length is sqrt(2)x its true travel time, since
    # the engine drives both axes at once. diagonal_bias trades one for the other.
    diag = math.hypot(20, 20)
    mesh = _mesh([(0, 0, 0), (1, 20, 20)], [(0, 1, diag)])
    assert nav.find_path(mesh, 0, 1).cost == pytest.approx(diag)  # default bias 0: length
    one = NavParams(diagonal_bias=1.0)
    assert nav.find_path(mesh, 0, 1, one).cost == pytest.approx(20.0)  # bias 1: travel time


def test_diagonal_bias_leaves_cardinal_edges_unchanged():
    # A cardinal edge has Chebyshev == Euclidean, so the bias never moves its cost.
    mesh = _mesh([(0, 0, 0), (1, 20, 0)], [(0, 1, 20.0)])
    assert nav.find_path(mesh, 0, 1).cost == pytest.approx(20.0)
    assert nav.find_path(mesh, 0, 1, NavParams(diagonal_bias=0.0)).cost == pytest.approx(20.0)


# --- NavState following ---------------------------------------------------


def _line_plan() -> NavPlan:
    pts = ((0, 0), (10, 0), (20, 0))
    return NavPlan(nodes=(0, 1, 2), waypoints=pts, cost=20.0, goal=2)


def test_navstate_cursor_advances_to_arrived():
    state = nav.NavState(plan=_line_plan(), params=NavParams(arrival_radius=2.0))
    assert not state.arrived
    for pos in [(0, 0), (10, 0), (20, 0)]:
        state.update(pos)
    assert state.cursor == 3 and state.arrived
    assert state.target() is None


def test_navstate_update_collapses_waypoint_cluster():
    plan = NavPlan(
        nodes=(0, 1, 2, 3), waypoints=((0, 0), (5, 0), (10, 0), (100, 0)), cost=0.0, goal=3
    )
    state = nav.NavState(plan=plan, params=NavParams(arrival_radius=12.0))
    state.update((0, 0))  # within 12px of (0,0),(5,0),(10,0) but not (100,0)
    assert state.cursor == 3 and not state.arrived


def test_navstate_heading_seek_direction():
    # Pure seek (no inertia): target up-left of me -> (-1, -1) diagonally.
    state = nav.NavState(plan=_line_plan(), params=NavParams(inertia=False))
    state.plan = NavPlan(nodes=(0,), waypoints=((-10, -10),), cost=0.0, goal=0)
    assert state.heading((0, 0)) == (-1, -1)
    # 4-way collapses to the dominant axis.
    state.params = NavParams(inertia=False, diagonal=False)
    state.plan = NavPlan(nodes=(0,), waypoints=((-10, -3),), cost=0.0, goal=0)
    assert state.heading((0, 0)) == (-1, 0)


def test_crew_buffer_off_by_default():
    # No crew-to-crew collision in CrewRift: the buffer is a pure preference, off
    # unless min_follow_distance > 0. By default a nearby crewmate is ignored.
    state = nav.NavState(params=NavParams(inertia=False))
    state.plan = NavPlan(nodes=(0,), waypoints=((10, 0),), cost=0.0, goal=0)
    assert state.heading((0, 0)) == (1, 0)
    assert state.heading((0, 0), others=[(3, 3)]) == (1, 0)  # crew nearby: no bend


def test_navstate_crew_separation_bends_heading():
    params = NavParams(inertia=False, min_follow_distance=16.0, avoidance_weight=1.0)
    state = nav.NavState(params=params)
    state.plan = NavPlan(nodes=(0,), waypoints=((10, 0),), cost=0.0, goal=0)
    assert state.heading((0, 0)) == (1, 0)  # no crew: pure seek +x
    # A crewmate close on the lower-right pushes us up.
    bent = state.heading((0, 0), others=[(3, 3)])
    assert bent == (1, -1)
    # At/beyond the threshold there is no force.
    assert state.heading((0, 0), others=[(0, 16)]) == (1, 0)


def test_heading_never_steers_away_from_waypoint():
    # PROVES the wedge bug. Real trace: agent at (166,269), waypoint (182,266) -- 16px RIGHT and
    # 3px UP -- carrying up-right velocity from a prior diagonal. The old inertia velocity-error
    # braking saw the y-velocity exceed the tiny y-desired and pressed DOWN (away from the UP
    # waypoint) to bleed it, which stalled the agent in place (the 1900-changes/game "wiggle").
    # The follower must HOLD toward the waypoint and never steer away from it on an axis.
    plan = NavPlan(nodes=(0, 1), waypoints=((0, 0), (182, 266)), cost=0.0, goal=1)
    state = nav.NavState(plan=plan, params=NavParams())  # inertia default True, no grid
    state.cursor = 1
    state.velocity = (2.0, -2.0)  # moving up-right (carries y-velocity)
    dx, dy = state.heading((166, 269))
    assert dx == 1, "must hold full speed toward the rightward waypoint"
    assert dy != 1, "must NOT press DOWN, away from an UP waypoint (the brake-stall bug)"


def test_navstate_stops_at_goal_without_braking():
    # New contract: hold the button toward the waypoint at full speed (NO velocity-error
    # braking -- that stalled the agent mid-path), and simply STOP once within arrival_radius
    # of the final goal. Never press the opposite way.
    plan = NavPlan(nodes=(0, 1), waypoints=((0, 0), (20, 0)), cost=20.0, goal=1)
    state = nav.NavState(plan=plan, params=NavParams(arrival_radius=12.0))
    state.cursor = 1
    state.velocity = (3.0, 0.0)  # fast toward the goal -- old code braked (-1) here
    assert state.heading((18, 0)) == (0, 0)  # 2px from goal, within arrival -> stop, not brake
    assert state.heading((0, 0)) == (1, 0)  # far from goal -> hold full speed toward it


def test_navstate_inertia_holds_cruise_against_friction():
    # Far from goal at terminal speed -> keep pressing toward it (hold, not coast).
    plan = NavPlan(nodes=(0, 1), waypoints=((0, 0), (200, 0)), cost=200.0, goal=1)
    state = nav.NavState(plan=plan)
    state.cursor = 1
    state.velocity = (2.75, 0.0)  # the origin engine's per-axis terminal speed
    assert state.heading((0, 0)) == (1, 0)
    # And from a standstill far away it accelerates toward the goal.
    state.velocity = (0.0, 0.0)
    assert state.heading((0, 0)) == (1, 0)


def test_navstate_estimates_velocity_from_positions():
    state = nav.NavState(plan=_line_plan(), params=NavParams(arrival_radius=1.0))
    state.update((0, 0))
    state.update((3, -1))
    assert state.velocity == (3.0, -1.0)


def test_navstate_stuck_detection_and_reset():
    params = NavParams(stuck_window=4, stuck_epsilon=2.0, arrival_radius=1.0)
    plan = NavPlan(nodes=(0, 1), waypoints=((0, 0), (50, 0)), cost=50.0, goal=1)
    state = nav.NavState(plan=plan, params=params)
    for _ in range(4):
        state.update((5, 5))  # not moving
    assert state.stuck and state.needs_replan
    state.set_plan(plan)  # reinstalling clears the flags + history
    assert not state.stuck and not state.needs_replan
