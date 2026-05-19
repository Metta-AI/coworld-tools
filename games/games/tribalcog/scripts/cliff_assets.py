#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from PIL import Image

from sprite_transforms import apply_transforms

CLIFF_EDGE_SOURCE = "cliff_edge_ew.png"
CLIFF_CORNER_IN_SOURCE = "oriented/cliff_corner_in_nw.png"
CLIFF_CORNER_OUT_SOURCE = "oriented/cliff_corner_out_se.png"

CLIFF_VARIANT_KIND_TO_SOURCE = {
    "in": CLIFF_CORNER_IN_SOURCE,
    "out": CLIFF_CORNER_OUT_SOURCE,
}

CLIFF_PREVIEW_SPECS: tuple[tuple[str, str, set[tuple[int, int]]], ...] = (
    ("Edge N", "cliff_edge_ew_s.png", {(0, -1)}),
    ("Edge E", "cliff_edge_ns_w.png", {(1, 0)}),
    ("Edge S", "cliff_edge_ew.png", {(0, 1)}),
    ("Edge W", "cliff_edge_ns.png", {(-1, 0)}),
    ("Corner In NE", "oriented/cliff_corner_in_ne.png", {(0, -1), (1, 0)}),
    ("Corner In SE", "oriented/cliff_corner_in_se.png", {(1, 0), (0, 1)}),
    ("Corner In SW", "oriented/cliff_corner_in_sw.png", {(0, 1), (-1, 0)}),
    ("Corner In NW", "oriented/cliff_corner_in_nw.png", {(-1, 0), (0, -1)}),
    ("Corner Out NE", "oriented/cliff_corner_out_ne.png", {(1, -1)}),
    ("Corner Out SE", "oriented/cliff_corner_out_se.png", {(1, 1)}),
    ("Corner Out SW", "oriented/cliff_corner_out_sw.png", {(-1, 1)}),
    ("Corner Out NW", "oriented/cliff_corner_out_nw.png", {(-1, -1)}),
)

CLIFF_REQUIRED_KEYS = {sprite.removesuffix(".png") for _, sprite, _ in CLIFF_PREVIEW_SPECS}

_DERIVATIONS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    CLIFF_CORNER_IN_SOURCE: (
        ("cliff_corner_in_ne.png", ("flip_x",)),
        ("cliff_corner_in_sw.png", ("rot90",)),
        ("cliff_corner_in_se.png", ("rot90", "flip_x")),
    ),
    CLIFF_CORNER_OUT_SOURCE: (
        ("cliff_corner_out_sw.png", ("flip_x",)),
        ("cliff_corner_out_ne.png", ("rot90",)),
        ("cliff_corner_out_nw.png", ("rot90", "flip_x")),
    ),
    CLIFF_EDGE_SOURCE: (
        ("cliff_edge_ew_s.png", ("rot180",)),
        ("cliff_edge_ns_w.png", ("rot90",)),
        ("cliff_edge_ns.png", ("rot270",)),
    ),
}


def _relative_target(target: Path, out_dir: Path) -> str:
    try:
        return target.relative_to(out_dir).as_posix()
    except ValueError:
        return target.as_posix()


def maybe_derive_cliff_variants(target: Path, out_dir: Path) -> None:
    relative = _relative_target(target, out_dir)
    derivations = _DERIVATIONS.get(relative)
    if not derivations:
        return

    with Image.open(target) as existing:
        base = existing.convert("RGBA")
    target.parent.mkdir(parents=True, exist_ok=True)

    for name, ops in derivations:
        variant = apply_transforms(base, ops)
        variant.save(target.parent / name)
