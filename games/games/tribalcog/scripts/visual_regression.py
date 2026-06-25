#!/usr/bin/env python3
"""Visual regression test harness for Tribal Village rendering.

Captures RGB frames at specific game steps, compares them against baselines
using SSIM (structural similarity), and generates HTML diff reports.

Usage:
    python scripts/visual_regression.py --baseline --seed 42 --output tests/visual_baselines/
    python scripts/visual_regression.py --compare --seed 42 --output /tmp/tv_vr_report/
    python scripts/visual_regression.py --update --seed 42 --output tests/visual_baselines/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

# SSIM: prefer scikit-image, fall back to manual implementation
try:
    from skimage.metrics import structural_similarity as _skimage_ssim

    def compute_ssim(img_a: np.ndarray, img_b: np.ndarray) -> float:
        """Compute SSIM using scikit-image."""
        return float(_skimage_ssim(img_a, img_b, channel_axis=2))

except ImportError:

    def compute_ssim(img_a: np.ndarray, img_b: np.ndarray) -> float:
        """Compute SSIM using a simple numpy implementation.

        Based on the simplified SSIM formula from Wang et al. (2004).
        Operates on the luminance channel for speed.
        """
        # Convert to float grayscale
        gray_a = np.mean(img_a.astype(np.float64), axis=2)
        gray_b = np.mean(img_b.astype(np.float64), axis=2)

        mu_a = gray_a.mean()
        mu_b = gray_b.mean()
        sigma_a_sq = gray_a.var()
        sigma_b_sq = gray_b.var()
        sigma_ab = ((gray_a - mu_a) * (gray_b - mu_b)).mean()

        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2

        numerator = (2 * mu_a * mu_b + c1) * (2 * sigma_ab + c2)
        denominator = (mu_a**2 + mu_b**2 + c1) * (sigma_a_sq + sigma_b_sq + c2)

        return float(numerator / denominator)


SSIM_PASS_THRESHOLD = 0.95
DEFAULT_CAPTURE_STEPS = [0, 50, 100, 200, 500]
DEFAULT_SEED = 42
DEFAULT_RENDER_SCALE = 2


def create_env(seed: int, render_scale: int):
    """Create a TribalVillageEnv configured for deterministic RGB capture."""
    from tribal_village_env.environment import TribalVillageEnv

    env = TribalVillageEnv(
        config={
            "render_mode": "rgb_array",
            "render_scale": render_scale,
            "max_steps": 10_000,
        }
    )
    env.reset(seed=seed)
    return env


def capture_frames(
    seed: int,
    steps: list[int],
    render_scale: int,
) -> dict[int, np.ndarray]:
    """Run the game and capture RGB frames at specified steps.

    Returns a dict mapping step number to HxWx3 uint8 numpy array.
    """
    env = create_env(seed, render_scale)
    noop_actions = {f"agent_{i}": 0 for i in range(env.num_agents)}

    frames: dict[int, np.ndarray] = {}
    max_step = max(steps)

    # Capture step 0 (initial state after reset)
    if 0 in steps:
        frame = env.render()
        if frame is not None and isinstance(frame, np.ndarray):
            frames[0] = frame.copy()

    for step_num in range(1, max_step + 1):
        env.step(noop_actions)
        if step_num in steps:
            frame = env.render()
            if frame is not None and isinstance(frame, np.ndarray):
                frames[step_num] = frame.copy()

    env.close()
    return frames


def save_baselines(
    output_dir: Path,
    frames: dict[int, np.ndarray],
    seed: int,
    steps: list[int],
) -> None:
    """Save captured frames as baseline PNGs with metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for step_num, frame in frames.items():
        img = Image.fromarray(frame)
        img.save(output_dir / f"step_{step_num:05d}.png")

    metadata = {
        "seed": seed,
        "steps": steps,
        "frame_shape": list(next(iter(frames.values())).shape) if frames else [],
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
    print(f"Saved {len(frames)} baseline frames to {output_dir}")


def load_baselines(baseline_dir: Path) -> dict[int, np.ndarray]:
    """Load baseline PNGs from a directory."""
    baselines: dict[int, np.ndarray] = {}
    for png_path in sorted(baseline_dir.glob("step_*.png")):
        step_str = png_path.stem.replace("step_", "")
        step_num = int(step_str)
        img = Image.open(png_path)
        baselines[step_num] = np.array(img)
    return baselines


def compute_diff_image(
    baseline: np.ndarray, current: np.ndarray
) -> np.ndarray:
    """Compute a highlighted diff image showing changed regions.

    Returns an RGB image where changed pixels are highlighted in red.
    """
    diff = np.abs(baseline.astype(np.int16) - current.astype(np.int16))
    # Threshold: any channel differing by more than 5 counts as changed
    changed_mask = diff.max(axis=2) > 5

    # Blend: unchanged pixels are dimmed, changed pixels highlighted red
    result = (current.astype(np.float32) * 0.3).astype(np.uint8)
    result[changed_mask] = [255, 0, 0]
    return result


def run_comparison(
    baseline_dir: Path,
    output_dir: Path,
    seed: int,
    steps: list[int],
    render_scale: int,
) -> list[dict]:
    """Compare current renders against baselines.

    Returns a list of per-frame result dicts with ssim, pass/fail, paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    baselines = load_baselines(baseline_dir)
    if not baselines:
        print(f"No baselines found in {baseline_dir}", file=sys.stderr)
        sys.exit(1)

    # Use steps from baselines if not explicitly overridden
    compare_steps = sorted(baselines.keys()) if not steps else steps

    current_frames = capture_frames(seed, compare_steps, render_scale)
    results = []

    for step_num in compare_steps:
        result: dict = {"step": step_num}

        if step_num not in baselines:
            result["status"] = "SKIP"
            result["reason"] = "no baseline"
            results.append(result)
            continue

        if step_num not in current_frames:
            result["status"] = "FAIL"
            result["reason"] = "capture failed"
            results.append(result)
            continue

        bl = baselines[step_num]
        cur = current_frames[step_num]

        # Handle shape mismatch
        if bl.shape != cur.shape:
            result["status"] = "FAIL"
            result["reason"] = f"shape mismatch: baseline {bl.shape} vs current {cur.shape}"
            results.append(result)
            continue

        ssim_val = compute_ssim(bl, cur)
        passed = ssim_val > SSIM_PASS_THRESHOLD

        # Save images
        cur_path = output_dir / f"current_step_{step_num:05d}.png"
        bl_path = output_dir / f"baseline_step_{step_num:05d}.png"
        diff_path = output_dir / f"diff_step_{step_num:05d}.png"

        Image.fromarray(cur).save(cur_path)
        Image.fromarray(bl).save(bl_path)
        diff_img = compute_diff_image(bl, cur)
        Image.fromarray(diff_img).save(diff_path)

        result["ssim"] = round(ssim_val, 6)
        result["status"] = "PASS" if passed else "FAIL"
        result["baseline_path"] = str(bl_path.name)
        result["current_path"] = str(cur_path.name)
        result["diff_path"] = str(diff_path.name)
        results.append(result)

    return results


def generate_html_report(results: list[dict], output_dir: Path) -> Path:
    """Generate an HTML report with side-by-side comparisons."""
    report_path = output_dir / "report.html"

    all_pass = all(r.get("status") == "PASS" for r in results)
    status_color = "#2d7d2d" if all_pass else "#c0392b"
    status_text = "ALL PASS" if all_pass else "FAILURES DETECTED"

    rows = []
    for r in results:
        step = r["step"]
        status = r.get("status", "UNKNOWN")
        ssim = r.get("ssim", "N/A")
        reason = r.get("reason", "")

        badge_color = "#2d7d2d" if status == "PASS" else "#c0392b" if status == "FAIL" else "#7f8c8d"

        if r.get("baseline_path") and r.get("current_path") and r.get("diff_path"):
            images_html = f"""
            <td><img src="{r['baseline_path']}" style="max-width:300px"></td>
            <td><img src="{r['current_path']}" style="max-width:300px"></td>
            <td><img src="{r['diff_path']}" style="max-width:300px"></td>
            """
        else:
            images_html = f"<td colspan='3'>{reason}</td>"

        rows.append(f"""
        <tr>
            <td>Step {step}</td>
            <td><span style="background:{badge_color};color:white;padding:2px 8px;border-radius:4px">{status}</span></td>
            <td>{ssim}</td>
            {images_html}
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Visual Regression Report</title>
    <style>
        body {{ font-family: monospace; margin: 20px; background: #1a1a1a; color: #e0e0e0; }}
        h1 {{ color: #e0e0e0; }}
        .status {{ color: {status_color}; font-weight: bold; font-size: 1.2em; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #444; padding: 8px; text-align: center; }}
        th {{ background: #2a2a2a; }}
        tr:nth-child(even) {{ background: #222; }}
        img {{ border: 1px solid #555; }}
    </style>
</head>
<body>
    <h1>Visual Regression Report</h1>
    <p class="status">{status_text}</p>
    <p>SSIM threshold: {SSIM_PASS_THRESHOLD}</p>
    <table>
        <tr>
            <th>Frame</th>
            <th>Status</th>
            <th>SSIM</th>
            <th>Baseline</th>
            <th>Current</th>
            <th>Diff</th>
        </tr>
        {"".join(rows)}
    </table>
</body>
</html>"""

    report_path.write_text(html)
    return report_path


def print_results(results: list[dict]) -> bool:
    """Print comparison results to stdout. Returns True if all passed."""
    all_pass = True
    for r in results:
        step = r["step"]
        status = r.get("status", "UNKNOWN")
        ssim = r.get("ssim", "N/A")
        reason = r.get("reason", "")

        if status != "PASS":
            all_pass = False

        extra = f" ({reason})" if reason else ""
        print(f"  Step {step:>5d}: {status:<4s}  SSIM={ssim}{extra}")

    return all_pass


def main():
    parser = argparse.ArgumentParser(
        description="Visual regression testing for Tribal Village rendering"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", action="store_true", help="Generate baseline images")
    mode.add_argument("--compare", action="store_true", help="Compare against baselines")
    mode.add_argument("--update", action="store_true", help="Update baseline images")

    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed for deterministic output")
    parser.add_argument("--output", type=str, required=True, help="Output directory")
    parser.add_argument(
        "--baseline-dir",
        type=str,
        default=None,
        help="Baseline directory (for --compare, defaults to tests/visual_baselines/)",
    )
    parser.add_argument(
        "--steps",
        type=str,
        default=None,
        help="Comma-separated capture steps (default: 0,50,100,200,500)",
    )
    parser.add_argument(
        "--render-scale",
        type=int,
        default=DEFAULT_RENDER_SCALE,
        help="Render scale factor (default: 2)",
    )

    args = parser.parse_args()
    output_dir = Path(args.output)

    if args.steps:
        steps = [int(s.strip()) for s in args.steps.split(",")]
    else:
        steps = list(DEFAULT_CAPTURE_STEPS)

    if args.baseline or args.update:
        print(f"Capturing frames at steps {steps} with seed={args.seed}...")
        frames = capture_frames(args.seed, steps, args.render_scale)
        save_baselines(output_dir, frames, args.seed, steps)
        print("Done.")

    elif args.compare:
        baseline_dir = Path(args.baseline_dir) if args.baseline_dir else Path("tests/visual_baselines")
        if not baseline_dir.exists():
            print(f"Baseline directory not found: {baseline_dir}", file=sys.stderr)
            print("Run with --baseline first to generate baselines.", file=sys.stderr)
            sys.exit(1)

        print(f"Comparing against baselines in {baseline_dir}...")
        results = run_comparison(baseline_dir, output_dir, args.seed, steps, args.render_scale)

        all_pass = print_results(results)
        report_path = generate_html_report(results, output_dir)
        print(f"\nHTML report: {report_path}")

        # Save results as JSON too
        json_path = output_dir / "results.json"
        json_path.write_text(json.dumps(results, indent=2))

        if not all_pass:
            print("\nFAILED: Visual regression detected.")
            sys.exit(1)
        else:
            print("\nPASSED: No visual regression detected.")


if __name__ == "__main__":
    main()
