#!/usr/bin/env python3
from __future__ import annotations

from typing import Iterable

from PIL import Image


def apply_transform(img: Image.Image, op: str) -> Image.Image:
    if op == "copy":
        return img.copy()
    if op == "flip_x":
        return img.transpose(Image.FLIP_LEFT_RIGHT)
    if op == "rot90":
        return img.transpose(Image.ROTATE_90)
    if op == "rot180":
        return img.transpose(Image.ROTATE_180)
    if op == "rot270":
        return img.transpose(Image.ROTATE_270)
    raise ValueError(f"Unsupported transform: {op}")


def apply_transforms(img: Image.Image, ops: Iterable[str]) -> Image.Image:
    out = img
    for op in ops:
        out = apply_transform(out, op)
    return out
