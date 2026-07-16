"""Emit the self-described JSON interchange the ``nav_mesh`` runtime ingests.

Origin: extracted from Ron Dahlgren's (swgy) agent libraries
(swgy-crewrift; original modules ``swgy_tools.navmesh.interchange`` +
``walkgrid.pack_bits``). The format string is kept byte-identical.

Deliberately simple and independent of the runtime model: just the walk grid
(base64 packed bits), the nodes/edges, the density params, and provenance.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np

from .build import BuildParams

INTERCHANGE_FORMAT = "swgy-navmesh-interchange"
INTERCHANGE_VERSION = 1


def build_interchange(
    mask: np.ndarray,
    nodes: list[dict],
    edges: list[dict],
    params: BuildParams,
    tasks: list[dict] | None = None,
    vents: list[dict] | None = None,
    source: str = "aseprite:croatoan#walkLayer",
    provenance: dict | None = None,
) -> dict:
    h, w = mask.shape
    return {
        "format": INTERCHANGE_FORMAT,
        "version": INTERCHANGE_VERSION,
        "map": {"width": int(w), "height": int(h), "source": source},
        "density": {
            "grid": params.grid,
            "edge_max": params.edge_max,
            "node_clear": params.node_clear,
            "edge_clear": params.edge_clear,
        },
        "walk_bits_b64": base64.b64encode(pack_bits(mask)).decode("ascii"),
        "nodes": nodes,
        "edges": edges,
        "tasks": tasks or [],
        "vents": vents or [],
        "provenance": provenance or {},
    }


def write_interchange(obj: dict, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


def pack_bits(mask: np.ndarray) -> bytes:
    """Pack a 2-D bool mask into LSB-first bits, row-major."""
    return np.packbits(mask.astype(bool).reshape(-1), bitorder="little").tobytes()
