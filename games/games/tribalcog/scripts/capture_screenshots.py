#!/usr/bin/env python3
"""Headless screenshot capture harness for Tribal Village.

Loads the environment via Python FFI, runs the game with random actions,
and captures RGB frames as PNGs and ANSI terminal renders at configurable
intervals.

Usage:
    python scripts/capture_screenshots.py --steps 500 --interval 10 --output renders/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture headless screenshots from Tribal Village"
    )
    parser.add_argument(
        "--steps", type=int, default=500, help="Number of simulation steps to run"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Capture a frame every N steps",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="renders/",
        help="Output directory for captured frames",
    )
    parser.add_argument(
        "--render-scale",
        type=int,
        default=4,
        help="Render scale factor (pixels per tile)",
    )
    parser.add_argument(
        "--gif",
        action="store_true",
        help="Create an animated GIF from captured frames",
    )
    parser.add_argument(
        "--gif-fps",
        type=int,
        default=10,
        help="Frames per second for the output GIF",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Lazy imports so argparse --help is fast
    from tribal_village_env.config import EnvironmentConfig
    from tribal_village_env.environment import TribalVillageEnv

    out_dir = Path(args.output)
    rgb_dir = out_dir / "rgb"
    ansi_dir = out_dir / "ansi"
    rgb_dir.mkdir(parents=True, exist_ok=True)
    ansi_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(args.seed)

    config = EnvironmentConfig(
        ai_mode="builtin",
        render_mode="rgb_array",
        render_scale=args.render_scale,
    )
    env = TribalVillageEnv(config=config)

    print(
        f"Environment: {env.total_agents} agents, "
        f"map {env.map_width}x{env.map_height}, "
        f"render scale {env.render_scale}"
    )

    env.reset()

    captured = 0
    for step in range(1, args.steps + 1):
        actions = {
            f"agent_{i}": rng.integers(0, env.single_action_space.n)
            for i in range(env.num_agents)
        }
        _obs, _rewards, terminated, truncated, _infos = env.step(actions)

        if step % args.interval == 0:
            # RGB capture
            env._render_mode = "rgb_array"
            rgb_frame = env.render()
            if isinstance(rgb_frame, np.ndarray) and rgb_frame.size > 0:
                import cv2

                png_path = rgb_dir / f"step_{step:06d}.png"
                cv2.imwrite(str(png_path), cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR))

            # ANSI capture
            env._render_mode = "ansi"
            ansi_text = env.render()
            if ansi_text:
                ansi_path = ansi_dir / f"step_{step:06d}.txt"
                ansi_path.write_text(ansi_text, encoding="utf-8")

            captured += 1
            print(f"  step {step}/{args.steps} — captured frame {captured}")

        # Check if all agents are done
        all_done = all(
            terminated.get(f"agent_{i}", False) or truncated.get(f"agent_{i}", False)
            for i in range(env.num_agents)
        )
        if all_done:
            print(f"  all agents done at step {step}")
            break

    env.close()

    print(f"\nCaptured {captured} frames to {out_dir}")
    print(f"  RGB PNGs:  {rgb_dir}")
    print(f"  ANSI text: {ansi_dir}")

    if args.gif and captured > 0:
        _make_gif(rgb_dir, out_dir / "animation.gif", args.gif_fps)


def _make_gif(rgb_dir: Path, out_path: Path, fps: int) -> None:
    import cv2

    png_files = sorted(rgb_dir.glob("step_*.png"))
    if not png_files:
        print("No PNG files found for GIF creation")
        return

    frames = []
    for f in png_files:
        img = cv2.imread(str(f))
        if img is not None:
            frames.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

    if not frames:
        print("Failed to read any frames for GIF")
        return

    try:
        from PIL import Image

        pil_frames = [Image.fromarray(f) for f in frames]
        duration_ms = max(1, 1000 // fps)
        pil_frames[0].save(
            str(out_path),
            save_all=True,
            append_images=pil_frames[1:],
            duration=duration_ms,
            loop=0,
        )
        print(f"  GIF saved: {out_path} ({len(frames)} frames, {fps} fps)")
    except ImportError:
        print("  Pillow not installed — skipping GIF creation (pip install Pillow)")


if __name__ == "__main__":
    main()
