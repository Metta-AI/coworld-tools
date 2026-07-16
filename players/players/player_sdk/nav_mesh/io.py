"""Canonical nav-mesh serialization + interchange ingest.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift; original module ``swgy_base.nav.io``). The binary magics
(``SWGYWALK``/``SWGYGRAF``) and interchange format string are kept
byte-identical so existing assets stay loadable.

This module owns the canonical on-disk format: two files, a split of
``walks.bin`` (grid) and ``navgraph.bin`` (graph):

    <name>.walk   b"SWGYWALK" u16 ver u32 W u32 H u32 clen  zlib(packed bits)
    <name>.graph  b"SWGYGRAF" u16 ver u32 clen  zlib(body)

The graph body (string-table + nodes + edges + meta) is zlib-compressed so the
vendored asset stays small. We use stdlib ``zlib`` (symmetric, dependency-free)
for our own format; ``protocol.snappy`` only decodes the wire format.

``mesh_from_interchange`` is the *only* reader of the tool's simple JSON
interchange -- everything downstream uses the canonical files.
"""

from __future__ import annotations

import base64
import json
import math
import struct
import zlib
from pathlib import Path

from .model import NavEdge, NavGrid, NavMesh, NavNode, TaskStation, Vent

WALK_MAGIC = b"SWGYWALK"
GRAPH_MAGIC = b"SWGYGRAF"
FORMAT_VERSION = 4  # v4 added a vents section; v3 (exposure/witnesses) & v2 still load
_SUPPORTED_VERSIONS = frozenset({2, 3, 4})
INTERCHANGE_FORMAT = "swgy-navmesh-interchange"

_U16 = struct.Struct("<H")
_U32 = struct.Struct("<I")
_NO_STRING = 0xFFFF  # string-table sentinel for "no room"
_NO_WITNESS = 0xFFFFFFFF  # node sentinel for "witnesses unknown" (-> None)
_WALK_HEADER = struct.Struct("<8sHIII")  # magic, ver, width, height, clen
_GRAPH_HEADER = struct.Struct("<8sHI")  # magic, ver, clen
_NODE = struct.Struct("<Iii")  # v2: id, x, y  (tags follow)
_NODE_VIS = struct.Struct("<IiifI")  # v3: id, x, y, exposure:f32, witnesses:u32
_EDGE = struct.Struct("<IIfB")  # src, dst, weight, directed  (tags follow)
_TASK = struct.Struct("<IiiHH")  # id, x, y, room_str_idx, name_str_idx
_VENT = struct.Struct("<IiiHH")  # v4: id, x, y, room_str_idx, group_str_idx


# --- interchange (tool JSON -> model) -------------------------------------


def mesh_from_interchange(source: str | Path | dict) -> NavMesh:
    """Build a NavMesh from the tool's self-described JSON interchange."""
    if isinstance(source, dict):
        obj = source
    else:
        obj = json.loads(Path(source).read_text())

    fmt = obj.get("format")
    if fmt != INTERCHANGE_FORMAT:
        raise ValueError(f"not a nav interchange: format={fmt!r}")

    m = obj["map"]
    bits = base64.b64decode(obj["walk_bits_b64"])
    grid = NavGrid(width=int(m["width"]), height=int(m["height"]), bits=bits)

    nodes = [
        NavNode(
            id=int(n["id"]),
            x=int(n["x"]),
            y=int(n["y"]),
            tags=frozenset(n.get("tags", ())),
            exposure=None if n.get("exposure") is None else float(n["exposure"]),
            witnesses=None if n.get("witnesses") is None else int(n["witnesses"]),
        )
        for n in obj["nodes"]
    ]
    edges = [
        NavEdge(
            src=int(e["src"]),
            dst=int(e["dst"]),
            weight=float(e["weight"]),
            directed=bool(e.get("directed", False)),
            tags=frozenset(e.get("tags", ())),
        )
        for e in obj["edges"]
    ]
    tasks = [
        TaskStation(
            id=int(t["id"]),
            x=int(t["x"]),
            y=int(t["y"]),
            room=t.get("room"),
            name=t.get("name", ""),
        )
        for t in obj.get("tasks", [])
    ]
    vents = [
        Vent(
            id=int(v["id"]),
            x=int(v["x"]),
            y=int(v["y"]),
            room=v.get("room"),
            group=v.get("group", ""),
        )
        for v in obj.get("vents", [])
    ]
    meta = {
        "density": obj.get("density", {}),
        "map": {k: m[k] for k in m if k != "width" and k != "height"},
        "provenance": obj.get("provenance", {}),
    }
    return NavMesh(grid=grid, nodes=nodes, edges=edges, meta=meta, tasks=tasks, vents=vents)


# --- canonical grid file --------------------------------------------------


def save_grid(grid: NavGrid, path: str | Path) -> None:
    body = zlib.compress(grid.bits, 9)
    with Path(path).open("wb") as f:
        f.write(_WALK_HEADER.pack(WALK_MAGIC, FORMAT_VERSION, grid.width, grid.height, len(body)))
        f.write(body)


def load_grid(path: str | Path) -> NavGrid:
    data = Path(path).read_bytes()
    magic, ver, width, height, clen = _WALK_HEADER.unpack_from(data, 0)
    if magic != WALK_MAGIC:
        raise ValueError(f"bad walk magic {magic!r}")
    if ver not in _SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported walk version {ver}")
    off = _WALK_HEADER.size
    bits = zlib.decompress(data[off : off + clen])
    return NavGrid(width=width, height=height, bits=bits)


# --- canonical graph file -------------------------------------------------


def _pack_tags(tags: frozenset[str], index: dict[str, int]) -> bytes:
    ids = sorted(index[t] for t in tags)
    return _U16.pack(len(ids)) + b"".join(_U16.pack(i) for i in ids)


def _unpack_tags(data: bytes, off: int, table: list[str]) -> tuple[frozenset[str], int]:
    (count,) = _U16.unpack_from(data, off)
    off += _U16.size
    tags = []
    for _ in range(count):
        (i,) = _U16.unpack_from(data, off)
        off += _U16.size
        tags.append(table[i])
    return frozenset(tags), off


def save_graph(mesh: NavMesh, path: str | Path) -> None:
    # Collect every referenced string, then order the table by sort. A sorted table
    # is independent of set/hash iteration order (PYTHONHASHSEED), so the serialized
    # asset is byte-reproducible across machines and re-saves are idempotent.
    strings: set[str] = set()
    for n in mesh.nodes:
        strings |= n.tags
    for e in mesh.edges:
        strings |= e.tags
    for t in mesh.tasks:
        if t.room is not None:
            strings.add(t.room)
        if t.name:
            strings.add(t.name)
    for v in mesh.vents:
        if v.room is not None:
            strings.add(v.room)
        if v.group:
            strings.add(v.group)
    table: list[str] = sorted(strings)
    index: dict[str, int] = {s: i for i, s in enumerate(table)}

    out = bytearray()
    out += _U16.pack(len(table))
    for s in table:
        raw = s.encode("utf-8")
        out += _U16.pack(len(raw)) + raw

    out += _U32.pack(len(mesh.nodes))
    for n in mesh.nodes:
        exposure = float("nan") if n.exposure is None else float(n.exposure)
        witnesses = _NO_WITNESS if n.witnesses is None else int(n.witnesses)
        out += _NODE_VIS.pack(n.id, n.x, n.y, exposure, witnesses)
        out += _pack_tags(n.tags, index)

    out += _U32.pack(len(mesh.edges))
    for e in mesh.edges:
        out += _EDGE.pack(e.src, e.dst, e.weight, 1 if e.directed else 0)
        out += _pack_tags(e.tags, index)

    out += _U32.pack(len(mesh.tasks))
    for t in mesh.tasks:
        room_idx = index[t.room] if t.room is not None else _NO_STRING
        name_idx = index[t.name] if t.name else _NO_STRING
        out += _TASK.pack(t.id, t.x, t.y, room_idx, name_idx)

    # v4 vents section (must stay after tasks and before meta; readers gate on ver>=4).
    out += _U32.pack(len(mesh.vents))
    for v in mesh.vents:
        room_idx = index[v.room] if v.room is not None else _NO_STRING
        group_idx = index[v.group] if v.group else _NO_STRING
        out += _VENT.pack(v.id, v.x, v.y, room_idx, group_idx)

    meta_raw = json.dumps(mesh.meta, sort_keys=True).encode("utf-8")
    out += _U32.pack(len(meta_raw)) + meta_raw

    body = zlib.compress(bytes(out), 9)
    with Path(path).open("wb") as f:
        f.write(_GRAPH_HEADER.pack(GRAPH_MAGIC, FORMAT_VERSION, len(body)))
        f.write(body)


def _load_graph_body(grid: NavGrid, body: bytes, ver: int) -> NavMesh:
    off = 0
    (table_len,) = _U16.unpack_from(body, off)
    off += _U16.size
    table: list[str] = []
    for _ in range(table_len):
        (slen,) = _U16.unpack_from(body, off)
        off += _U16.size
        table.append(body[off : off + slen].decode("utf-8"))
        off += slen

    (node_count,) = _U32.unpack_from(body, off)
    off += _U32.size
    nodes: list[NavNode] = []
    for _ in range(node_count):
        if ver >= 3:
            nid, x, y, exposure, witnesses = _NODE_VIS.unpack_from(body, off)
            off += _NODE_VIS.size
            exp = None if math.isnan(exposure) else exposure
            wit = None if witnesses == _NO_WITNESS else witnesses
        else:
            nid, x, y = _NODE.unpack_from(body, off)
            off += _NODE.size
            exp = wit = None
        tags, off = _unpack_tags(body, off, table)
        nodes.append(NavNode(id=nid, x=x, y=y, tags=tags, exposure=exp, witnesses=wit))

    (edge_count,) = _U32.unpack_from(body, off)
    off += _U32.size
    edges: list[NavEdge] = []
    for _ in range(edge_count):
        src, dst, weight, directed = _EDGE.unpack_from(body, off)
        off += _EDGE.size
        tags, off = _unpack_tags(body, off, table)
        edges.append(NavEdge(src=src, dst=dst, weight=weight, directed=bool(directed), tags=tags))

    (task_count,) = _U32.unpack_from(body, off)
    off += _U32.size
    tasks: list[TaskStation] = []
    for _ in range(task_count):
        tid, x, y, room_idx, name_idx = _TASK.unpack_from(body, off)
        off += _TASK.size
        tasks.append(
            TaskStation(
                id=tid,
                x=x,
                y=y,
                room=table[room_idx] if room_idx != _NO_STRING else None,
                name=table[name_idx] if name_idx != _NO_STRING else "",
            )
        )

    # v4 added a vents section here; v2/v3 files have none, so meta follows tasks directly.
    vents: list[Vent] = []
    if ver >= 4:
        (vent_count,) = _U32.unpack_from(body, off)
        off += _U32.size
        for _ in range(vent_count):
            vid, x, y, room_idx, group_idx = _VENT.unpack_from(body, off)
            off += _VENT.size
            vents.append(
                Vent(
                    id=vid,
                    x=x,
                    y=y,
                    room=table[room_idx] if room_idx != _NO_STRING else None,
                    group=table[group_idx] if group_idx != _NO_STRING else "",
                )
            )

    (meta_len,) = _U32.unpack_from(body, off)
    off += _U32.size
    meta = json.loads(body[off : off + meta_len].decode("utf-8")) if meta_len else {}
    return NavMesh(grid=grid, nodes=nodes, edges=edges, meta=meta, tasks=tasks, vents=vents)


# --- combined mesh I/O ----------------------------------------------------


def save_mesh(mesh: NavMesh, walk_path: str | Path, graph_path: str | Path) -> None:
    save_grid(mesh.grid, walk_path)
    save_graph(mesh, graph_path)


def load_mesh(walk_path: str | Path, graph_path: str | Path) -> NavMesh:
    grid = load_grid(walk_path)
    data = Path(graph_path).read_bytes()
    magic, ver, clen = _GRAPH_HEADER.unpack_from(data, 0)
    if magic != GRAPH_MAGIC:
        raise ValueError(f"bad graph magic {magic!r}")
    if ver not in _SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported graph version {ver}")
    off = _GRAPH_HEADER.size
    body = zlib.decompress(data[off : off + clen])
    return _load_graph_body(grid, body, ver)

