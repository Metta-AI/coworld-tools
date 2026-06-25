#!/usr/bin/env python3
from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


def _color_close(a: tuple[int, int, int], b: tuple[int, int, int], tol: int) -> bool:
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol


def _flood_fill_alpha_zero(arr: np.ndarray, is_bg: np.ndarray) -> np.ndarray:
    h, w = is_bg.shape
    seen = np.zeros((h, w), dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        if 0 <= x < w and 0 <= y < h and is_bg[y, x] and not seen[y, x]:
            seen[y, x] = True
            q.append((x, y))

    for x in range(w):
        enqueue(x, 0)
        enqueue(x, h - 1)
    for y in range(h):
        enqueue(0, y)
        enqueue(w - 1, y)

    while q:
        x, y = q.popleft()
        enqueue(x - 1, y)
        enqueue(x + 1, y)
        enqueue(x, y - 1)
        enqueue(x, y + 1)

    if seen.any():
        arr[:, :, 3][seen] = 0
    return arr


def _crop_to_content(img: Image.Image, target_size: int, padding_frac: float = 0.1) -> Image.Image:
    arr = np.array(img.convert("RGBA"))
    alpha = arr[:, :, 3]
    ys, xs = np.where(alpha > 0)
    if len(xs) == 0:
        return img.resize((target_size, target_size), Image.LANCZOS) if target_size else img

    min_x, max_x = int(xs.min()), int(xs.max()) + 1
    min_y, max_y = int(ys.min()), int(ys.max()) + 1
    box_w = max_x - min_x
    box_h = max_y - min_y
    side = max(box_w, box_h)
    pad = int(round(side * padding_frac))
    side = side + 2 * pad

    cx = (min_x + max_x) // 2
    cy = (min_y + max_y) // 2
    left = max(0, cx - side // 2)
    top = max(0, cy - side // 2)
    right = min(arr.shape[1], left + side)
    bottom = min(arr.shape[0], top + side)
    if right - left < side:
        left = max(0, right - side)
    if bottom - top < side:
        top = max(0, bottom - side)

    cropped = img.crop((left, top, right, bottom))
    if target_size and cropped.size != (target_size, target_size):
        cropped = cropped.resize((target_size, target_size), Image.LANCZOS)
    return cropped


def _remove_corner_background(img: Image.Image, tol: int = 24) -> Image.Image:
    arr = np.array(img.convert("RGBA"))
    h, w = arr.shape[:2]
    corners = [arr[0, 0, :3], arr[0, w - 1, :3], arr[h - 1, 0, :3], arr[h - 1, w - 1, :3]]
    # Median corner color is usually the generated background.
    bg = tuple(int(v) for v in np.median(np.array(corners), axis=0))

    is_bg = np.zeros((h, w), dtype=bool)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    for y in range(h):
        for x in range(w):
            if alpha[y, x] == 0:
                is_bg[y, x] = True
                continue
            c = (int(rgb[y, x, 0]), int(rgb[y, x, 1]), int(rgb[y, x, 2]))
            if _color_close(c, bg, tol):
                is_bg[y, x] = True

    arr = _flood_fill_alpha_zero(arr, is_bg)
    return Image.fromarray(arr, "RGBA")


def _remove_purple_bg(img: Image.Image) -> Image.Image:
    arr = np.array(img.convert("RGBA"))
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    # Key out vivid purple background used by asset prompts.
    is_bg = (alpha > 0) & (rgb[:, :, 0] >= 100) & (rgb[:, :, 0] <= 190) & (rgb[:, :, 1] <= 90) & (rgb[:, :, 2] >= 150)
    arr = _flood_fill_alpha_zero(arr, is_bg)
    return Image.fromarray(arr, "RGBA")


def apply_postprocess(
    img: Image.Image,
    target_size: int,
    tol: int = 24,
    purple_to_white: bool = False,
    purple_bg: bool = False,
) -> Image.Image:
    out = img.convert("RGBA")
    if purple_bg:
        out = _remove_purple_bg(out)
    else:
        out = _remove_corner_background(out, tol)
    out = _crop_to_content(out, target_size)

    if purple_to_white:
        arr = np.array(out)
        r = arr[:, :, 0]
        g = arr[:, :, 1]
        b = arr[:, :, 2]
        a = arr[:, :, 3]
        mask = (a > 0) & (r >= 180) & (b >= 180) & (g <= 120)
        arr[mask, 0:3] = 255
        out = Image.fromarray(arr, "RGBA")
    return out


def tmp_path_for(target: Path, out_dir: Path, tmp_dir: Path) -> Path:
    try:
        relative = target.relative_to(out_dir)
    except ValueError:
        return tmp_dir / target.name
    return tmp_dir / relative


def postprocess_to_target(
    source: Path,
    target: Path,
    size: int,
    tol: int,
    purple_to_white: bool,
    purple_bg: bool,
) -> None:
    with Image.open(source) as existing:
        img = existing.convert("RGBA")
    img = apply_postprocess(
        img,
        target_size=size,
        tol=tol,
        purple_to_white=purple_to_white,
        purple_bg=purple_bg,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target)
