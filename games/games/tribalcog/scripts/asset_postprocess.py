#!/usr/bin/env python3
from __future__ import annotations

from collections import deque
from pathlib import Path

import cv2  # type: ignore
import numpy as np  # type: ignore
from PIL import Image


def flood_fill_bg_cv2(img: Image.Image, tol: int = 18) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    w, h = img.size
    px = img.load()
    border_colors: dict[tuple[int, int, int], int] = {}
    for x in range(w):
        for y in (0, h - 1):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            key = (r // 8, g // 8, b // 8)
            border_colors[key] = border_colors.get(key, 0) + 1
    for y in range(h):
        for x in (0, w - 1):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            key = (r // 8, g // 8, b // 8)
            border_colors[key] = border_colors.get(key, 0) + 1

    if border_colors:
        top = sorted(border_colors.items(), key=lambda item: item[1], reverse=True)[:4]
        bg_colors = [(k[0] * 8, k[1] * 8, k[2] * 8) for k, _ in top]
    else:
        bg_colors = [px[x, y][:3] for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]

    def color_close(c, ref) -> bool:
        return all(abs(int(c[i]) - int(ref[i])) <= tol for i in range(3))

    arr = np.array(img)
    rgb = arr[:, :, :3].copy()
    alpha = arr[:, :, 3]
    if bg_colors:
        rgb[alpha == 0] = bg_colors[0]

    mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    lo = (tol, tol, tol)
    up = (tol, tol, tol)
    flags = cv2.FLOODFILL_MASK_ONLY | (255 << 8)

    for x in range(w):
        for y in (0, h - 1):
            if mask[y + 1, x + 1] != 0:
                continue
            r, g, b, a = px[x, y]
            if a == 0 or any(color_close((r, g, b), ref) for ref in bg_colors):
                cv2.floodFill(rgb, mask, (x, y), (0, 0, 0), loDiff=lo, upDiff=up, flags=flags)
    for y in range(h):
        for x in (0, w - 1):
            if mask[y + 1, x + 1] != 0:
                continue
            r, g, b, a = px[x, y]
            if a == 0 or any(color_close((r, g, b), ref) for ref in bg_colors):
                cv2.floodFill(rgb, mask, (x, y), (0, 0, 0), loDiff=lo, upDiff=up, flags=flags)

    fill_mask = mask[1:-1, 1:-1] != 0
    arr[:, :, 3][fill_mask] = 0
    return Image.fromarray(arr, "RGBA")


def flood_fill_bg(img: Image.Image, tol: int = 18) -> Image.Image:
    return flood_fill_bg_cv2(img, tol)


def alpha_bbox_cv2(
    alpha: np.ndarray,
    min_border_fraction: float = 0.004,
    min_border_pixels: int = 64,
    min_alpha: int = 1,
) -> tuple[int, int, int, int] | None:
    mask = (alpha >= min_alpha).astype("uint8")
    if not mask.any():
        return None
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        return None
    total_area = int(mask.sum())
    min_border_area = max(min_border_pixels, int(total_area * min_border_fraction))
    h, w = mask.shape
    keep: list[int] = []
    for idx in range(1, num):
        left = stats[idx, cv2.CC_STAT_LEFT]
        top = stats[idx, cv2.CC_STAT_TOP]
        width = stats[idx, cv2.CC_STAT_WIDTH]
        height = stats[idx, cv2.CC_STAT_HEIGHT]
        area = stats[idx, cv2.CC_STAT_AREA]
        touches_border = (
            left == 0
            or top == 0
            or left + width >= w
            or top + height >= h
        )
        if touches_border and area < min_border_area:
            continue
        keep.append(idx)
    if not keep:
        ys, xs = np.where(mask)
        if len(xs) == 0:
            return None
        return (int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1))
    left = int(min(stats[idx, cv2.CC_STAT_LEFT] for idx in keep))
    top = int(min(stats[idx, cv2.CC_STAT_TOP] for idx in keep))
    right = int(max(stats[idx, cv2.CC_STAT_LEFT] + stats[idx, cv2.CC_STAT_WIDTH] for idx in keep))
    bottom = int(max(stats[idx, cv2.CC_STAT_TOP] + stats[idx, cv2.CC_STAT_HEIGHT] for idx in keep))
    return (left, top, right, bottom)


def crop_to_content(
    img: Image.Image,
    target_size: int,
    padding_frac: float = 0.1,
) -> Image.Image:
    w, h = img.size
    alpha = img.getchannel("A")
    bbox = alpha_bbox_cv2(np.array(alpha))
    if not bbox:
        return img
    minx, miny, maxx, maxy = bbox
    box_w = maxx - minx
    box_h = maxy - miny
    side = max(box_w, box_h)
    if padding_frac > 0:
        pad = int(round(side * padding_frac))
        side = side + pad * 2
    cx = minx + box_w // 2
    cy = miny + box_h // 2
    half = side // 2
    left = max(0, cx - half)
    top = max(0, cy - half)
    right = min(w, left + side)
    bottom = min(h, top + side)
    if right - left < side:
        left = max(0, right - side)
    if bottom - top < side:
        top = max(0, bottom - side)
    cropped = img.crop((left, top, right, bottom))
    if target_size and cropped.size != (target_size, target_size):
        cropped = cropped.resize((target_size, target_size), Image.LANCZOS)
    return cropped


def purple_bg_mask(arr: np.ndarray) -> np.ndarray:
    bgr = arr[:, :, :3][:, :, ::-1]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0]
    s = hsv[:, :, 1]
    v = hsv[:, :, 2]
    alpha = arr[:, :, 3]
    return (
        (alpha > 0)
        & (h >= 100)
        & (h <= 150)
        & (s >= 80)
        & (v >= 80)
    )


def flood_fill_purple_bg(img: Image.Image) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    arr = np.array(img)
    mask = purple_bg_mask(arr).astype("uint8")
    if not mask.any():
        return img
    h, w = mask.shape
    visited = np.zeros(mask.shape, dtype=bool)
    q: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        if mask[y, x] == 1 and not visited[y, x]:
            visited[y, x] = True
            q.append((x, y))

    for x in range(w):
        enqueue(x, 0)
        enqueue(x, h - 1)
    for y in range(h):
        enqueue(0, y)
        enqueue(w - 1, y)

    while q:
        x, y = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] == 1 and not visited[ny, nx]:
                visited[ny, nx] = True
                q.append((nx, ny))

    if visited.any():
        arr[:, :, 3][visited] = 0
    return Image.fromarray(arr, "RGBA")


def apply_postprocess(
    img: Image.Image,
    target_size: int,
    tol: int = 18,
    purple_to_white: bool = False,
    purple_bg: bool = False,
) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    if purple_bg:
        img = flood_fill_purple_bg(img)
        img = crop_to_content(img, target_size)
    else:
        img = flood_fill_bg(img, tol)
        img = crop_to_content(img, target_size)
    if purple_to_white:
        px = img.load()
        w, h = img.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a == 0:
                    continue
                if r >= 180 and b >= 180 and g <= 120:
                    px[x, y] = (255, 255, 255, a)
    return img


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
    img = apply_postprocess(img, size, tol, purple_to_white, purple_bg)
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target)
