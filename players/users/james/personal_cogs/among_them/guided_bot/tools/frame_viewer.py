#!/usr/bin/env python3
"""Interactive frame viewer for guided_bot trace recordings.

Loads a ``frames.bin`` file (raw 128x128 uint8 palette-indexed frames)
from a trace session directory and displays them in a scaleable pygame
window with keyboard/mouse scrolling.

Usage:
    PYTHONPATH=among_them .venv/bin/python \\
        among_them/guided_bot/tools/frame_viewer.py <trace_session_dir>

    # Or point directly at a frames.bin:
    PYTHONPATH=among_them .venv/bin/python \\
        among_them/guided_bot/tools/frame_viewer.py path/to/frames.bin

Controls:
    Right / D / Space   — Next frame
    Left  / A          — Previous frame
    Shift+Right        — Skip forward 10 frames
    Shift+Left         — Skip backward 10 frames
    Page Down          — Skip forward 100 frames
    Page Up            — Skip backward 100 frames
    Home               — Jump to first frame
    End                — Jump to last frame
    +/=                — Zoom in (increase scale)
    -                  — Zoom out (decrease scale)
    G                  — Go to frame (type number in terminal)
    S                  — Save current frame as PNG
    I                  — Toggle info overlay (frame index, tick, etc.)
    O                  — Toggle perception overlay
    N                  — Toggle navigation overlay
    Q / Escape         — Quit

Mouse:
    Scroll wheel       — Next/previous frame

Requires: pygame, numpy
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pygame

# ---------------------------------------------------------------------------
# PICO-8 palette (matches modulabot/data.py and the Nim-side palette.bin)
# ---------------------------------------------------------------------------

PICO8_PALETTE = np.array(
    [
        (0x00, 0x00, 0x00),  #  0 black
        (0xC2, 0xC3, 0xC7),  #  1 light grey
        (0xFF, 0xF1, 0xE8),  #  2 white
        (0xFF, 0x00, 0x4D),  #  3 red
        (0xFF, 0x77, 0xA8),  #  4 pink
        (0x5F, 0x57, 0x4F),  #  5 dark grey
        (0xAB, 0x52, 0x36),  #  6 brown
        (0xFF, 0xA3, 0x00),  #  7 orange
        (0xFF, 0xEC, 0x27),  #  8 yellow
        (0x7E, 0x25, 0x53),  #  9 dark purple
        (0x00, 0x87, 0x51),  # 10 dark green
        (0x00, 0xE4, 0x36),  # 11 green
        (0x1D, 0x2B, 0x53),  # 12 dark navy
        (0x83, 0x76, 0x9C),  # 13 indigo
        (0x29, 0xAD, 0xFF),  # 14 blue
        (0xFF, 0xCC, 0xAA),  # 15 peach
    ],
    dtype=np.uint8,
)

FRAME_W = 128
FRAME_H = 128
FRAME_BYTES = FRAME_W * FRAME_H
PLAYER_COLORS = [3, 7, 8, 14, 4, 11, 13, 15]

# ---------------------------------------------------------------------------
# Frame loading
# ---------------------------------------------------------------------------


def load_frames(path: Path) -> np.ndarray:
    """Load frames.bin and return as (N, 128, 128) uint8 array."""
    data = np.fromfile(path, dtype=np.uint8)
    if data.size == 0:
        print(f"Error: {path} is empty.", file=sys.stderr)
        sys.exit(1)
    if data.size % FRAME_BYTES != 0:
        print(
            f"Warning: {path} size ({data.size}) is not a multiple of "
            f"{FRAME_BYTES}. Truncating to nearest whole frame.",
            file=sys.stderr,
        )
        n = data.size // FRAME_BYTES
        data = data[: n * FRAME_BYTES]
    return data.reshape(-1, FRAME_H, FRAME_W)


def load_manifest(session_dir: Path) -> dict | None:
    """Load manifest.json if present, for metadata overlay."""
    manifest_path = session_dir / "manifest.json"
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def load_perception(session_dir: Path) -> dict[int, dict] | None:
    """Load perception.jsonl and index entries by zero-based frame index."""
    perception_path = session_dir / "perception.jsonl"
    if not perception_path.exists():
        return None

    entries: list[dict] = []
    try:
        with perception_path.open() as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(
                        f"Warning: {perception_path}:{line_no}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                if isinstance(rec, dict):
                    entries.append(rec)
    except OSError as exc:
        print(
            f"Warning: could not read {perception_path}: {exc}",
            file=sys.stderr,
        )
        return None

    index: dict[int, dict] = {}
    for rec in entries:
        tick = rec.get("t")
        if isinstance(tick, int):
            index[tick - 1] = rec

    print(f"Loaded {len(index)} perception entries from {perception_path}")
    return index


def load_decisions(session_dir: Path) -> dict[int, dict] | None:
    """Load decisions.jsonl and index entries by zero-based frame index."""
    decisions_path = session_dir / "decisions.jsonl"
    if not decisions_path.exists():
        return None

    index: dict[int, dict] = {}
    try:
        with decisions_path.open() as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    print(
                        f"Warning: {decisions_path}:{line_no}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                if not isinstance(rec, dict):
                    continue
                tick = rec.get("t")
                if isinstance(tick, int):
                    index[tick - 1] = rec
    except OSError as exc:
        print(
            f"Warning: could not read {decisions_path}: {exc}",
            file=sys.stderr,
        )
        return None

    print(f"Loaded {len(index)} decision entries from {decisions_path}")
    return index


def load_nav_graph() -> dict[int, tuple[int, int]]:
    """Load baked waypoint coordinates by stable waypoint ID."""
    graph_path = (
        Path(__file__).resolve().parent.parent
        / "perception"
        / "baked"
        / "nav_graph.json"
    )
    try:
        data = json.loads(graph_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: could not read {graph_path}: {exc}", file=sys.stderr)
        return {}

    coords: dict[int, tuple[int, int]] = {}
    for wp in data.get("waypoints", []):
        if not isinstance(wp, dict):
            continue
        wp_id = wp.get("id")
        x = wp.get("x")
        y = wp.get("y")
        if isinstance(wp_id, int) and isinstance(x, int) and isinstance(y, int):
            coords[wp_id] = (x, y)

    print(f"Loaded {len(coords)} navigation waypoints from {graph_path}")
    return coords


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def frame_to_surface(frame: np.ndarray, scale: int) -> pygame.Surface:
    """Convert a 128x128 palette-indexed frame to a scaled pygame Surface."""
    # Map palette indices to RGB.
    rgb = PICO8_PALETTE[frame]  # (128, 128, 3)
    # pygame wants (width, height, 3) with axes (x, y) but numpy is (row, col).
    surf = pygame.surfarray.make_surface(rgb.swapaxes(0, 1))
    if scale != 1:
        surf = pygame.transform.scale(surf, (FRAME_W * scale, FRAME_H * scale))
    return surf


def palette_rgb(palette_index: int) -> tuple[int, int, int]:
    """Return an RGB tuple from the PICO-8 palette."""
    rgb = PICO8_PALETTE[palette_index]
    return int(rgb[0]), int(rgb[1]), int(rgb[2])


def player_rgb(color_index: int) -> tuple[int, int, int]:
    """Map a player color index to RGB, falling back to white if unknown."""
    if 0 <= color_index < len(PLAYER_COLORS):
        return palette_rgb(PLAYER_COLORS[color_index])
    return (255, 255, 255)


def draw_sprite_box(
    screen: pygame.Surface,
    detection: dict,
    scale: int,
    color: tuple[int, int, int],
    width: int = 1,
) -> pygame.Rect:
    """Draw a scaled 12x12 detection box and return its screen rect."""
    x = int(detection.get("x", 0)) * scale
    y = int(detection.get("y", 0)) * scale
    rect = pygame.Rect(x, y, 12 * scale, 12 * scale)
    pygame.draw.rect(screen, color, rect, width=width)
    return rect


def draw_overlay(screen: pygame.Surface, percept: dict, scale: int) -> None:
    """Draw perception detections over the current frame."""
    red = palette_rgb(3)
    yellow = palette_rgb(8)
    green = palette_rgb(11)
    cyan = (0, 255, 255)
    ghost_color = (180, 160, 255)

    for crewmate in percept.get("crewmates", []):
        if isinstance(crewmate, dict):
            color_index = int(crewmate.get("color", -1))
            draw_sprite_box(screen, crewmate, scale, player_rgb(color_index))

    for body in percept.get("bodies", []):
        if isinstance(body, dict):
            rect = draw_sprite_box(screen, body, scale, red, width=2)
            pygame.draw.line(screen, red, rect.topleft, rect.bottomright, width=2)
            pygame.draw.line(screen, red, rect.topright, rect.bottomleft, width=2)

    for ghost in percept.get("ghosts", []):
        if isinstance(ghost, dict):
            draw_sprite_box(screen, ghost, scale, ghost_color)

    for icon in percept.get("task_icons", []):
        if isinstance(icon, dict):
            draw_sprite_box(screen, icon, scale, cyan)

    dot_size = max(1, 5 * scale)
    for dot in percept.get("radar_dots", []):
        if isinstance(dot, dict):
            center_x = int(dot.get("x", 0)) * scale
            center_y = int(dot.get("y", 0)) * scale
            rect = pygame.Rect(
                center_x - dot_size // 2,
                center_y - dot_size // 2,
                dot_size,
                dot_size,
            )
            pygame.draw.rect(screen, yellow, rect)

    localized = bool(percept.get("localized", False))
    if localized:
        anchor_x = 63 * scale
        anchor_y = 60 * scale
        arm = max(4, 3 * scale)
        pygame.draw.line(
            screen, green, (anchor_x - arm, anchor_y), (anchor_x + arm, anchor_y), 2
        )
        pygame.draw.line(
            screen, green, (anchor_x, anchor_y - arm), (anchor_x, anchor_y + arm), 2
        )

    font = pygame.font.SysFont("monospace", 14)
    crew_count = len(percept.get("crewmates", []))
    body_count = len(percept.get("bodies", []))
    radar_count = len(percept.get("radar_dots", []))
    lines: list[tuple[str, tuple[int, int, int]]] = [
        (
            f"{percept.get('phase', '?')}  role:{percept.get('role', '?')}",
            (230, 230, 230),
        )
    ]
    if localized:
        lines.append(
            (
                f"cam:{percept.get('camera_x', '?')},{percept.get('camera_y', '?')}",
                (210, 255, 210),
            )
        )
    else:
        lines.append(("NOT LOCALIZED", red))
    lines.append(
        (
            f"{crew_count} crew, {body_count} bodies, {radar_count} radar",
            (230, 230, 230),
        )
    )

    rendered = [font.render(text, True, color) for text, color in lines]
    padding = 4
    line_gap = 2
    box_w = max(surf.get_width() for surf in rendered) + padding * 2
    box_h = (
        sum(surf.get_height() for surf in rendered)
        + line_gap * max(0, len(rendered) - 1)
        + padding * 2
    )
    bg = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 170))
    screen.blit(bg, (2, 2))

    y = 2 + padding
    for surf in rendered:
        screen.blit(surf, (2 + padding, y))
        y += surf.get_height() + line_gap


def world_to_screen(wx: int, wy: int, cam_x: int, cam_y: int) -> tuple[int, int]:
    """Convert world-space coordinates to 128x128 screen-space coordinates."""
    return wx - cam_x, wy - cam_y


def screen_visible(sx: int, sy: int) -> bool:
    """Return True when a screen-space point is within the raw 128x128 frame."""
    return 0 <= sx < FRAME_W and 0 <= sy < FRAME_H


def scaled_point(sx: int, sy: int, scale: int) -> tuple[int, int]:
    """Scale a raw screen-space point for drawing on the pygame surface."""
    return sx * scale, sy * scale


def int_or_none(value: object) -> int | None:
    """Return value as int only when it is already an int-like JSON number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def waypoint_screen_point(
    waypoint_id: int,
    waypoint_coords: dict[int, tuple[int, int]],
    cam_x: int,
    cam_y: int,
) -> tuple[int, int] | None:
    """Look up a waypoint ID and return its screen-space point if known."""
    world = waypoint_coords.get(waypoint_id)
    if world is None:
        return None
    return world_to_screen(world[0], world[1], cam_x, cam_y)


def draw_nav_overlay(
    screen: pygame.Surface,
    decision: dict,
    perception_entry: dict,
    waypoint_coords: dict[int, tuple[int, int]],
    scale: int,
) -> None:
    """Draw waypoint-route navigation diagnostics over the current frame."""
    nav = decision.get("nav")
    if not isinstance(nav, dict):
        return

    cam_x = int_or_none(perception_entry.get("camera_x"))
    cam_y = int_or_none(perception_entry.get("camera_y"))
    if cam_x is None or cam_y is None:
        return

    blue = (40, 120, 255)
    cyan = (0, 255, 255)
    green = (0, 255, 70)
    magenta = (255, 0, 255)
    line_w = max(1, 2 * scale)
    edge_w = max(1, 3 * scale)

    raw_path = nav.get("strategic_path", [])
    path_ids = (
        [wp for wp in (int_or_none(item) for item in raw_path) if wp is not None]
        if isinstance(raw_path, list)
        else []
    )

    for a, b in zip(path_ids, path_ids[1:]):
        p1 = waypoint_screen_point(a, waypoint_coords, cam_x, cam_y)
        p2 = waypoint_screen_point(b, waypoint_coords, cam_x, cam_y)
        if p1 is None or p2 is None:
            continue
        if not (screen_visible(*p1) and screen_visible(*p2)):
            continue
        pygame.draw.line(
            screen,
            blue,
            scaled_point(*p1, scale),
            scaled_point(*p2, scale),
            line_w,
        )

    current_from = int_or_none(nav.get("current_wp_from"))
    current_to = int_or_none(nav.get("current_wp"))
    if (
        current_from is not None
        and current_to is not None
        and current_from >= 0
        and current_to >= 0
    ):
        p1 = waypoint_screen_point(current_from, waypoint_coords, cam_x, cam_y)
        p2 = waypoint_screen_point(current_to, waypoint_coords, cam_x, cam_y)
        if p1 is not None and p2 is not None:
            if screen_visible(*p1) and screen_visible(*p2):
                pygame.draw.line(
                    screen,
                    cyan,
                    scaled_point(*p1, scale),
                    scaled_point(*p2, scale),
                    edge_w,
                )

    marker_size = max(1, 3 * scale)
    for wp_id in path_ids:
        p = waypoint_screen_point(wp_id, waypoint_coords, cam_x, cam_y)
        if p is None or not screen_visible(*p):
            continue
        px, py = scaled_point(*p, scale)
        rect = pygame.Rect(
            px - marker_size // 2,
            py - marker_size // 2,
            marker_size,
            marker_size,
        )
        pygame.draw.rect(screen, blue, rect)

    look_x = int_or_none(nav.get("lookahead_x"))
    look_y = int_or_none(nav.get("lookahead_y"))
    if look_x is not None and look_y is not None:
        p = world_to_screen(look_x, look_y, cam_x, cam_y)
        if screen_visible(*p):
            pygame.draw.circle(
                screen,
                green,
                scaled_point(*p, scale),
                max(1, 4 * scale),
            )

    goal_x = int_or_none(nav.get("goal_x"))
    goal_y = int_or_none(nav.get("goal_y"))
    if goal_x is not None and goal_y is not None:
        p = world_to_screen(goal_x, goal_y, cam_x, cam_y)
        if screen_visible(*p):
            cx, cy = scaled_point(*p, scale)
            radius = max(1, 4 * scale)
            points = [
                (cx, cy - radius),
                (cx + radius, cy),
                (cx, cy + radius),
                (cx - radius, cy),
            ]
            pygame.draw.lines(screen, magenta, True, points, max(1, 2 * scale))


# ---------------------------------------------------------------------------
# Main viewer loop
# ---------------------------------------------------------------------------


def run_viewer(
    frames: np.ndarray,
    manifest: dict | None,
    session_dir: Path,
    perception: dict[int, dict] | None,
    decisions: dict[int, dict] | None,
    waypoint_coords: dict[int, tuple[int, int]],
    start_frame: int = 0,
    initial_scale: int = 4,
) -> None:
    """Main pygame event loop."""
    n_frames = len(frames)
    current = max(0, min(start_frame, n_frames - 1))
    scale = max(1, min(initial_scale, 8))
    show_info = True
    show_overlay = perception is not None
    show_nav_overlay = decisions is not None
    playback_active = False
    playback_fps = 24

    pygame.init()
    pygame.display.set_caption("guided_bot frame viewer")

    def resize_window():
        nonlocal screen
        screen = pygame.display.set_mode(
            (FRAME_W * scale, FRAME_H * scale + INFO_BAR_H)
        )

    INFO_BAR_H = 30
    screen = None
    resize_window()

    font = pygame.font.SysFont("monospace", 14)
    clock = pygame.time.Clock()

    def draw():
        surf = frame_to_surface(frames[current], scale)
        screen.fill((0, 0, 0))
        screen.blit(surf, (0, 0))

        if show_overlay and perception is not None and current in perception:
            draw_overlay(screen, perception[current], scale)

        if (
            show_nav_overlay
            and decisions is not None
            and perception is not None
            and current in decisions
            and current in perception
            and waypoint_coords
        ):
            draw_nav_overlay(
                screen,
                decisions[current],
                perception[current],
                waypoint_coords,
                scale,
            )

        if show_info:
            # Info bar at the bottom.
            bar_y = FRAME_H * scale
            pygame.draw.rect(
                screen, (20, 20, 20), (0, bar_y, FRAME_W * scale, INFO_BAR_H)
            )
            role = manifest.get("role", "?") if manifest else "?"
            status = f"Frame {current}/{n_frames - 1}  Scale:{scale}x  Role:{role}"
            if show_overlay and perception is not None:
                status += "  OVL"
            if show_nav_overlay and decisions is not None:
                status += "  NAV"
            if playback_active:
                status += f"  PLAY({playback_fps}fps)"
            text_surf = font.render(status, True, (200, 200, 200))
            screen.blit(text_surf, (4, bar_y + 6))

            # Progress bar.
            bar_w = FRAME_W * scale - 8
            progress = current / max(n_frames - 1, 1)
            pygame.draw.rect(screen, (60, 60, 60), (4, bar_y + 22, bar_w, 4))
            pygame.draw.rect(
                screen, (100, 200, 100), (4, bar_y + 22, int(bar_w * progress), 4)
            )

        pygame.display.flip()

    def clamp(idx: int) -> int:
        return max(0, min(n_frames - 1, idx))

    running = True
    draw()

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            elif event.type == pygame.KEYDOWN:
                mods = pygame.key.get_mods()
                shift = mods & pygame.KMOD_SHIFT

                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    running = False

                elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_SPACE):
                    step = 10 if shift else 1
                    current = clamp(current + step)
                    draw()

                elif event.key in (pygame.K_LEFT, pygame.K_a):
                    step = 10 if shift else 1
                    current = clamp(current - step)
                    draw()

                elif event.key == pygame.K_PAGEDOWN:
                    current = clamp(current + 100)
                    draw()

                elif event.key == pygame.K_PAGEUP:
                    current = clamp(current - 100)
                    draw()

                elif event.key == pygame.K_HOME:
                    current = 0
                    draw()

                elif event.key == pygame.K_END:
                    current = n_frames - 1
                    draw()

                elif event.key in (pygame.K_EQUALS, pygame.K_PLUS):
                    scale = min(scale + 1, 8)
                    resize_window()
                    draw()

                elif event.key == pygame.K_MINUS:
                    scale = max(scale - 1, 1)
                    resize_window()
                    draw()

                elif event.key == pygame.K_g:
                    # Go-to-frame prompt (uses terminal input).
                    try:
                        target = int(input(f"Go to frame [0-{n_frames-1}]: "))
                        current = clamp(target)
                    except (ValueError, EOFError):
                        pass
                    draw()

                elif event.key == pygame.K_s:
                    # Save current frame as PNG.
                    out_path = session_dir / f"frame_{current:06d}.png"
                    surf = frame_to_surface(frames[current], scale)
                    pygame.image.save(surf, str(out_path))
                    print(f"Saved: {out_path}")

                elif event.key == pygame.K_i:
                    show_info = not show_info
                    draw()

                elif event.key == pygame.K_o:
                    if perception is not None:
                        show_overlay = not show_overlay
                    draw()

                elif event.key == pygame.K_n:
                    if decisions is not None:
                        show_nav_overlay = not show_nav_overlay
                    draw()

                elif event.key == pygame.K_p:
                    playback_active = not playback_active
                    draw()

                elif event.key == pygame.K_PERIOD:
                    # Increase playback speed.
                    playback_fps = min(playback_fps + 4, 120)
                    draw()

                elif event.key == pygame.K_COMMA:
                    # Decrease playback speed.
                    playback_fps = max(playback_fps - 4, 1)
                    draw()

            elif event.type == pygame.MOUSEWHEEL:
                if event.y > 0:
                    current = clamp(current - 1)
                else:
                    current = clamp(current + 1)
                draw()

        # Auto-playback mode.
        if playback_active:
            current = clamp(current + 1)
            if current >= n_frames - 1:
                playback_active = False
            draw()
            clock.tick(playback_fps)
        else:
            clock.tick(60)

    pygame.quit()


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive viewer for guided_bot frame recordings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "target",
        help=(
            "Path to a trace session directory (containing frames.bin) "
            "or a frames.bin file directly."
        ),
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=4,
        help="Initial display scale (1-8, default 4).",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Starting frame index.",
    )
    args = parser.parse_args()

    target = Path(args.target)

    # Resolve frames.bin path.
    if target.is_file() and target.name == "frames.bin":
        frames_path = target
        session_dir = target.parent
    elif target.is_dir():
        frames_path = target / "frames.bin"
        if not frames_path.exists():
            # Maybe the user passed a bot_N dir — look for the latest session.
            sessions = sorted(target.iterdir())
            sessions = [s for s in sessions if s.is_dir()]
            if sessions:
                frames_path = sessions[-1] / "frames.bin"
                session_dir = sessions[-1]
            if not frames_path.exists():
                print(
                    f"Error: No frames.bin found in {target}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            session_dir = target
    else:
        print(
            f"Error: {target} is not a valid directory or frames.bin file.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not frames_path.exists():
        print(f"Error: {frames_path} does not exist.", file=sys.stderr)
        sys.exit(1)

    session_dir = frames_path.parent

    print(f"Loading {frames_path} ...")
    frames = load_frames(frames_path)
    print(f"Loaded {len(frames)} frames ({frames.nbytes / 1024 / 1024:.1f} MB)")

    manifest = load_manifest(session_dir)
    if manifest:
        role = manifest.get("role", "?")
        ticks = manifest.get("end_tick", "?")
        print(f"Session: role={role}, end_tick={ticks}")

    perception = load_perception(session_dir)
    decisions = load_decisions(session_dir)
    waypoint_coords = load_nav_graph()

    # Apply starting frame.
    start = max(0, min(args.start, len(frames) - 1))

    run_viewer(
        frames,
        manifest,
        session_dir,
        perception,
        decisions,
        waypoint_coords,
        start_frame=start,
        initial_scale=args.scale,
    )


if __name__ == "__main__":
    main()
