#!/usr/bin/env python3
"""GUI element audit script for tribal_village.

Systematically tests all GUI/renderer elements by running the game in headless
RGB mode and validating rendered frames at key moments.

Usage:
    python scripts/audit_gui.py --seed 42 --steps 500 --output /tmp/tv_audit/
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from pathlib import Path

import numpy as np

from script_paths import DATA_DIR, REPO_ROOT

# ---------------------------------------------------------------------------
# Constants mirroring Nim types/constants
# ---------------------------------------------------------------------------

MAP_WIDTH = 306
MAP_HEIGHT = 192
NUM_TEAMS = 8

# Expected team palette RGB values (from src/colors.nim WarmTeamPalette,
# converted to 0-255 integers via console_viz.nim TeamFg).
TEAM_COLORS_RGB = [
    (232, 107, 107),  # 0: red
    (240, 166, 107),  # 1: orange
    (240, 209, 107),  # 2: yellow
    (153, 214, 128),  # 3: olive-lime
    (199, 97, 224),   # 4: magenta
    (107, 184, 240),  # 5: sky
    (222, 222, 222),  # 6: gray
    (237, 143, 209),  # 7: pink
]

# Capture schedule: (step, label)
CAPTURE_SCHEDULE = [
    (0, "initial"),
    (50, "early_game"),
    (200, "mid_game"),
    (500, "late_game"),
]

# Frame validation thresholds
MIN_PIXEL_VARIANCE = 25.0           # Minimum std-dev across pixel values
MIN_DISTINCT_COLORS = 20            # Minimum distinct quantized colors
TEAM_COLOR_TOLERANCE = 40           # L2 distance tolerance for team color matching
MIN_TEAMS_VISIBLE = 2               # Minimum teams with visible colors at step 0


# ---------------------------------------------------------------------------
# Sprite atlas audit (static — no library needed)
# ---------------------------------------------------------------------------

def get_required_sprite_keys() -> set[str]:
    """Collect sprite keys that MUST exist for the game to work.

    The game has fallback logic for oriented units: if a specific direction
    doesn't exist, it uses the .s (south) variant. So only .s is required;
    other directions are optional enhancements.
    """
    keys: set[str] = set()

    # Core rendering sprites
    keys.update([
        "floor", "grid", "selection", "frozen", "heart", "cave", "dungeon",
    ])

    # Terrain
    keys.update([
        "water", "shallow_water", "bridge", "fertile", "road",
        "grass", "dune", "sand", "snow", "mud",
    ])

    # Buildings
    keys.update([
        "altar", "town_center", "house", "door", "clay_oven", "weaving_loom",
        "outpost", "guard_tower", "barrel", "mill", "granary", "lumber_camp",
        "quarry", "mining_camp", "barracks", "archery_range", "stable",
        "siege_workshop", "mangonel_workshop", "trebuchet_workshop",
        "blacksmith", "market", "dock", "monastery", "university",
        "castle", "wonder", "goblin_hive", "goblin_hut", "goblin_totem",
    ])

    # Things
    keys.update([
        "tree", "wheat", "fish", "stone", "gold", "bush", "cactus",
        "stalagmite", "magma", "spawner", "corpse", "skeleton", "stump",
        "stubble", "lantern", "temple", "control_point", "goblet",
    ])

    # Items
    keys.update([
        "bar", "droplet", "bushel", "wood", "spear", "shield", "bread",
        "plant", "meat",
    ])

    # UI
    keys.update([
        "ui/play", "ui/pause", "ui/stepForward", "ui/turtle",
        "ui/speed", "ui/rabbit",
    ])

    # Oriented units — only .s (south) fallback is required
    unit_bases = [
        "gatherer", "builder", "fighter", "man_at_arms", "archer", "scout",
        "knight", "monk", "battering_ram", "mangonel", "trebuchet_packed",
        "trebuchet_unpacked", "goblin", "boat", "trade_cog", "samurai",
        "longbowman", "cataphract", "woad_raider", "teutonic_knight",
        "huskarl", "mameluke", "janissary", "king", "cow", "bear", "wolf",
    ]
    for base in unit_bases:
        keys.add(f"oriented/{base}.s")

    # Walls (all 16 bitmask combinations + fill)
    for i in range(16):
        suffix = ""
        if i & 8:
            suffix += "n"
        if i & 4:
            suffix += "w"
        if i & 2:
            suffix += "s"
        if i & 1:
            suffix += "e"
        keys.add(f"oriented/wall.{suffix}" if suffix else "oriented/wall")
    keys.add("oriented/wall.fill")

    # Tumors
    for prefix in ["oriented/tumor", "oriented/tumor.expired"]:
        for d in ["n", "s", "e", "w"]:
            keys.add(f"{prefix}.{d}")

    # Cliff edges (registry.nim ThingCatalog)
    keys.update([
        "cliff_edge_ew", "cliff_edge_ew_s", "cliff_edge_ns", "cliff_edge_ns_w",
    ])

    # Cliff corners (registry.nim ThingCatalog)
    for kind in ["in", "out"]:
        for d in ["ne", "se", "sw", "nw"]:
            keys.add(f"oriented/cliff_corner_{kind}_{d}")

    # Ramps (registry.nim TerrainThingCatalog)
    for direction in ["up", "down"]:
        for d in ["n", "s", "e", "w"]:
            keys.add(f"oriented/ramp_{direction}_{d}")

    # Waterfalls (registry.nim ThingCatalog)
    for d in ["n", "e", "s", "w"]:
        keys.add(f"waterfall_{d}")

    return keys


def get_optional_sprite_keys(on_disk: set[str]) -> set[str]:
    """Return optional sprite keys that exist on disk and are used when present.

    These are direction variants beyond .s — loaded if available, not required.
    """
    optional: set[str] = set()
    unit_bases = [
        "gatherer", "builder", "fighter", "man_at_arms", "archer", "scout",
        "knight", "monk", "battering_ram", "mangonel", "trebuchet_packed",
        "trebuchet_unpacked", "goblin", "boat", "trade_cog", "samurai",
        "longbowman", "cataphract", "woad_raider", "teutonic_knight",
        "huskarl", "mameluke", "janissary", "king", "cow", "bear", "wolf",
    ]
    for base in unit_bases:
        for d in ["n", "e", "w", "ne", "nw", "se", "sw", "r"]:
            key = f"oriented/{base}.{d}"
            if key in on_disk:
                optional.add(key)
    return optional


def audit_sprite_atlas() -> dict:
    """Check all sprite atlas entries against data/ directory.

    Required sprites must exist (fail if missing). Optional direction variants
    are tracked but don't cause failure. Orphaned sprites are on disk but
    unreferenced by either set.
    """
    required = get_required_sprite_keys()

    on_disk: set[str] = set()
    for png in DATA_DIR.rglob("*.png"):
        if "df_view" in png.parts:
            continue
        key = png.relative_to(DATA_DIR).as_posix().removesuffix(".png")
        on_disk.add(key)

    optional_used = get_optional_sprite_keys(on_disk)
    all_referenced = required | optional_used

    orphaned = sorted(on_disk - all_referenced)
    missing_required = sorted(required - on_disk)

    return {
        "total_required": len(required),
        "total_optional_used": len(optional_used),
        "total_on_disk": len(on_disk),
        "orphaned_count": len(orphaned),
        "orphaned_keys": orphaned,
        "missing_required_count": len(missing_required),
        "missing_required_keys": missing_required,
        "pass": len(missing_required) == 0,
    }


# ---------------------------------------------------------------------------
# Frame validation helpers
# ---------------------------------------------------------------------------

def check_not_blank(frame: np.ndarray) -> dict:
    """Verify the frame is not blank/black by checking pixel variance."""
    variance = float(np.std(frame.astype(np.float32)))
    is_pass = variance > MIN_PIXEL_VARIANCE
    return {
        "check": "not_blank",
        "pixel_std_dev": round(variance, 2),
        "threshold": MIN_PIXEL_VARIANCE,
        "pass": is_pass,
    }


def check_color_diversity(frame: np.ndarray) -> dict:
    """Verify expected number of distinct colors (terrain variety)."""
    # Quantize to reduce noise: divide by 16, so similar shades merge
    quantized = (frame // 16).reshape(-1, 3)
    unique = np.unique(quantized, axis=0)
    n_colors = len(unique)
    is_pass = n_colors >= MIN_DISTINCT_COLORS
    return {
        "check": "color_diversity",
        "distinct_colors_quantized": n_colors,
        "threshold": MIN_DISTINCT_COLORS,
        "pass": is_pass,
    }


def check_team_colors(frame: np.ndarray) -> dict:
    """Check that team colors are visible in the frame."""
    # Flatten frame to list of RGB pixels
    pixels = frame.reshape(-1, 3).astype(np.float32)

    teams_found = []
    for team_id, (tr, tg, tb) in enumerate(TEAM_COLORS_RGB):
        target = np.array([tr, tg, tb], dtype=np.float32)
        # Compute L2 distance for each pixel to team color
        dists = np.linalg.norm(pixels - target, axis=1)
        min_dist = float(np.min(dists))
        count = int(np.sum(dists < TEAM_COLOR_TOLERANCE))
        teams_found.append({
            "team": team_id,
            "closest_distance": round(min_dist, 1),
            "pixel_count_within_tolerance": count,
            "found": count > 0,
        })

    n_found = sum(1 for t in teams_found if t["found"])
    return {
        "check": "team_colors",
        "teams_visible": n_found,
        "min_teams_required": MIN_TEAMS_VISIBLE,
        "teams": teams_found,
        "pass": n_found >= MIN_TEAMS_VISIBLE,
    }


def check_ui_panels(frame: np.ndarray, render_scale: int) -> dict:
    """Check that UI panel regions (resource bar, minimap) have content.

    The resource bar occupies the top ~30px strip. The minimap occupies a
    ~200x200 region in the bottom-right corner. We check that these regions
    are not uniform (i.e., they contain rendered content).
    """
    h, w, _ = frame.shape

    # Resource bar: top strip (approximately 30 * scale pixels tall)
    resource_bar_h = min(30 * render_scale, h // 4)
    resource_bar = frame[:resource_bar_h, :, :]
    rb_std = float(np.std(resource_bar.astype(np.float32)))
    rb_pass = rb_std > 5.0

    # Minimap: bottom-right corner (200 * scale / MAP_WIDTH approximately)
    minimap_size = min(200, h // 3, w // 3)
    minimap_region = frame[h - minimap_size:, w - minimap_size:, :]
    mm_std = float(np.std(minimap_region.astype(np.float32)))
    mm_pass = mm_std > 5.0

    return {
        "check": "ui_panels",
        "resource_bar_std": round(rb_std, 2),
        "resource_bar_present": rb_pass,
        "minimap_region_std": round(mm_std, 2),
        "minimap_present": mm_pass,
        "pass": rb_pass and mm_pass,
    }


def compute_visual_diff(frame_a: np.ndarray, frame_b: np.ndarray) -> dict:
    """Compare two frames and report changed regions.

    Returns summary statistics and a heatmap of per-pixel L2 diff.
    """
    if frame_a.shape != frame_b.shape:
        return {
            "error": "shape_mismatch",
            "shape_a": list(frame_a.shape),
            "shape_b": list(frame_b.shape),
        }

    diff = np.abs(frame_a.astype(np.float32) - frame_b.astype(np.float32))
    per_pixel_l2 = np.sqrt(np.sum(diff ** 2, axis=2))

    changed_mask = per_pixel_l2 > 10.0
    total_pixels = changed_mask.size
    changed_pixels = int(np.sum(changed_mask))
    pct = round(100.0 * changed_pixels / total_pixels, 2) if total_pixels else 0.0

    return {
        "total_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "changed_pct": pct,
        "max_diff": round(float(np.max(per_pixel_l2)), 2),
        "mean_diff": round(float(np.mean(per_pixel_l2)), 2),
    }


# ---------------------------------------------------------------------------
# Environment runner
# ---------------------------------------------------------------------------

def load_library() -> ctypes.CDLL | None:
    """Try to load the Nim shared library."""
    import platform

    if platform.system() == "Darwin":
        lib_name = "libtribal_village.dylib"
    elif platform.system() == "Windows":
        lib_name = "libtribal_village.dll"
    else:
        lib_name = "libtribal_village.so"

    candidate_paths = [
        REPO_ROOT / lib_name,
        REPO_ROOT / "tribal_village_env" / lib_name,
    ]

    for path in candidate_paths:
        if path.exists():
            return ctypes.CDLL(str(path))
    return None


def setup_lib(lib: ctypes.CDLL) -> None:
    """Configure ctypes signatures for the functions we need."""
    specs: list[tuple[str, list, type | None, bool]] = [
        ("tribal_village_create", [], ctypes.c_void_p, False),
        (
            "tribal_village_reset_and_get_obs",
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
             ctypes.c_void_p, ctypes.c_void_p],
            ctypes.c_int32, False,
        ),
        (
            "tribal_village_step_with_pointers",
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p],
            ctypes.c_int32, False,
        ),
        ("tribal_village_destroy", [ctypes.c_void_p], None, False),
        ("tribal_village_get_num_agents", [], ctypes.c_int32, False),
        ("tribal_village_get_obs_layers", [], ctypes.c_int32, False),
        ("tribal_village_get_obs_width", [], ctypes.c_int32, False),
        ("tribal_village_get_obs_height", [], ctypes.c_int32, False),
        ("tribal_village_set_ai_mode", [ctypes.c_int32], ctypes.c_int32, True),
        ("tribal_village_get_map_width", [], ctypes.c_int32, True),
        ("tribal_village_get_map_height", [], ctypes.c_int32, True),
        (
            "tribal_village_render_rgb",
            [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32],
            ctypes.c_int32, True,
        ),
    ]
    for name, argtypes, restype, optional in specs:
        func = getattr(lib, name, None)
        if func is None:
            if optional:
                continue
            raise AttributeError(f"Required symbol missing: {name}")
        func.argtypes = argtypes
        if restype is not None:
            func.restype = restype


def run_simulation(
    lib: ctypes.CDLL,
    max_step: int,
    render_scale: int,
    output_dir: Path | None,
) -> tuple[list[dict], list[dict]]:
    """Run the simulation, capturing and validating frames at scheduled steps.

    Returns (frame_results, visual_diffs).
    """
    num_agents = lib.tribal_village_get_num_agents()
    obs_layers = lib.tribal_village_get_obs_layers()
    obs_w = lib.tribal_village_get_obs_width()
    obs_h = lib.tribal_village_get_obs_height()

    map_w_fn = getattr(lib, "tribal_village_get_map_width", None)
    map_h_fn = getattr(lib, "tribal_village_get_map_height", None)
    if map_w_fn and map_h_fn:
        map_w = int(map_w_fn())
        map_h = int(map_h_fn())
    else:
        map_w, map_h = MAP_WIDTH, MAP_HEIGHT

    render_w = map_w * render_scale
    render_h = map_h * render_scale

    has_rgb = hasattr(lib, "tribal_village_render_rgb")

    # Allocate buffers
    obs = np.zeros(num_agents * obs_layers * obs_w * obs_h, dtype=np.uint8)
    rewards = np.zeros(num_agents, dtype=np.float32)
    terminals = np.zeros(num_agents, dtype=np.uint8)
    truncations = np.zeros(num_agents, dtype=np.uint8)
    actions = np.zeros(num_agents, dtype=np.uint16)
    rgb_frame = np.zeros((render_h, render_w, 3), dtype=np.uint8)

    env_ptr = lib.tribal_village_create()
    if not env_ptr:
        raise RuntimeError("tribal_village_create returned null")

    # Enable builtin AI so scripted behavior drives the simulation
    set_ai = getattr(lib, "tribal_village_set_ai_mode", None)
    if set_ai is not None:
        set_ai(ctypes.c_int32(1))  # 1 = BuiltinAI

    # Reset
    ok = lib.tribal_village_reset_and_get_obs(
        env_ptr,
        obs.ctypes.data_as(ctypes.c_void_p),
        rewards.ctypes.data_as(ctypes.c_void_p),
        terminals.ctypes.data_as(ctypes.c_void_p),
        truncations.ctypes.data_as(ctypes.c_void_p),
    )
    if not ok:
        lib.tribal_village_destroy(env_ptr)
        raise RuntimeError("Reset failed")

    # Build capture targets
    targets = {step: label for step, label in CAPTURE_SCHEDULE if step <= max_step}
    if max_step not in targets:
        targets[max_step] = f"step_{max_step}"

    frame_results: list[dict] = []
    captured_frames: dict[str, np.ndarray] = {}

    def capture_and_validate(step: int, label: str) -> dict:
        result: dict = {"step": step, "label": label, "checks": []}

        if not has_rgb:
            result["checks"].append({"check": "rgb_render", "pass": False,
                                      "reason": "tribal_village_render_rgb not available"})
            return result

        rgb_frame[:] = 0
        rgb_ok = lib.tribal_village_render_rgb(
            env_ptr,
            rgb_frame.ctypes.data_as(ctypes.c_void_p),
            ctypes.c_int32(render_w),
            ctypes.c_int32(render_h),
        )
        if not rgb_ok:
            result["checks"].append({"check": "rgb_render", "pass": False,
                                      "reason": "render_rgb returned 0"})
            return result

        frame_copy = rgb_frame.copy()
        captured_frames[label] = frame_copy

        # Save frame as raw numpy if output dir provided
        if output_dir:
            np.save(output_dir / f"frame_{label}.npy", frame_copy)
            # Also save as PPM for easy viewing
            _save_ppm(output_dir / f"frame_{label}.ppm", frame_copy)

        # Run all checks
        result["checks"].append(check_not_blank(frame_copy))
        result["checks"].append(check_color_diversity(frame_copy))
        result["checks"].append(check_team_colors(frame_copy))
        result["checks"].append(check_ui_panels(frame_copy, render_scale))

        return result

    # Step 0 capture (after reset)
    if 0 in targets:
        frame_results.append(capture_and_validate(0, targets[0]))

    # Run simulation
    for step in range(1, max_step + 1):
        # Random actions (action 0 = idle is fine for audit)
        actions[:] = 0
        ok = lib.tribal_village_step_with_pointers(
            env_ptr,
            actions.ctypes.data_as(ctypes.c_void_p),
            obs.ctypes.data_as(ctypes.c_void_p),
            rewards.ctypes.data_as(ctypes.c_void_p),
            terminals.ctypes.data_as(ctypes.c_void_p),
            truncations.ctypes.data_as(ctypes.c_void_p),
        )
        if not ok:
            frame_results.append({
                "step": step, "label": f"step_{step}",
                "error": "step returned 0",
                "checks": [],
            })
            break

        if step in targets:
            frame_results.append(capture_and_validate(step, targets[step]))

    # Visual diffs between consecutive captures
    diffs = []
    labels = list(captured_frames.keys())
    for i in range(1, len(labels)):
        prev_label = labels[i - 1]
        curr_label = labels[i]
        diff_result = compute_visual_diff(
            captured_frames[prev_label], captured_frames[curr_label]
        )
        diff_result["from"] = prev_label
        diff_result["to"] = curr_label
        diffs.append(diff_result)

    lib.tribal_village_destroy(env_ptr)

    return frame_results, diffs


def _save_ppm(path: Path, frame: np.ndarray) -> None:
    """Save an RGB frame as a PPM image (no external deps needed)."""
    h, w, _ = frame.shape
    with open(path, "wb") as f:
        f.write(f"P6\n{w} {h}\n255\n".encode())
        f.write(frame.tobytes())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit tribal_village GUI/renderer elements"
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    parser.add_argument("--steps", type=int, default=500, help="Number of simulation steps")
    parser.add_argument("--output", type=str, default="/tmp/tv_audit", help="Output directory")
    parser.add_argument("--render-scale", type=int, default=4, help="Render scale factor")
    parser.add_argument("--static-only", action="store_true",
                        help="Only run static checks (no simulation)")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "seed": args.seed,
        "steps": args.steps,
        "render_scale": args.render_scale,
        "output_dir": str(output_dir),
        "sections": {},
    }

    # ── Section 1: Sprite atlas audit (always runs) ──────────────────────
    print("=== Sprite Atlas Audit ===")
    sprite_result = audit_sprite_atlas()
    report["sections"]["sprite_atlas"] = sprite_result
    print(f"  Required:   {sprite_result['total_required']}")
    print(f"  Optional:   {sprite_result['total_optional_used']}")
    print(f"  On disk:    {sprite_result['total_on_disk']}")
    print(f"  Missing:    {sprite_result['missing_required_count']}")
    print(f"  Orphaned:   {sprite_result['orphaned_count']}")
    if sprite_result["missing_required_keys"]:
        for k in sprite_result["missing_required_keys"][:10]:
            print(f"    MISSING: data/{k}.png")
        if len(sprite_result["missing_required_keys"]) > 10:
            print(f"    ... and {len(sprite_result['missing_required_keys']) - 10} more")
    print(f"  Result: {'PASS' if sprite_result['pass'] else 'FAIL'}")
    print()

    # ── Section 2: Simulation frame audit ────────────────────────────────
    if args.static_only:
        print("=== Skipping simulation (--static-only) ===")
        report["sections"]["frames"] = {"skipped": True}
        report["sections"]["visual_diffs"] = {"skipped": True}
    else:
        print("=== Loading Nim Library ===")
        lib = load_library()
        if lib is None:
            print("  WARNING: Nim library not found. Run `make lib` first.")
            print("  Skipping simulation checks.")
            report["sections"]["frames"] = {
                "skipped": True,
                "reason": "library_not_found",
            }
            report["sections"]["visual_diffs"] = {"skipped": True}
        else:
            print("  Library loaded successfully.")
            setup_lib(lib)

            print(f"\n=== Running Simulation ({args.steps} steps) ===")
            frame_results, diffs = run_simulation(
                lib, args.steps, args.render_scale, output_dir
            )

            report["sections"]["frames"] = {"results": frame_results}
            report["sections"]["visual_diffs"] = {"diffs": diffs}

            for fr in frame_results:
                all_pass = all(c.get("pass", False) for c in fr["checks"])
                status = "PASS" if all_pass else "FAIL"
                print(f"  Step {fr['step']:>5} ({fr['label']}): {status}")
                for c in fr["checks"]:
                    if not c.get("pass", False):
                        reason = c.get("reason", "")
                        print(f"    FAIL: {c['check']} {reason}")
            print()

            if diffs:
                print("=== Visual Diffs ===")
                for d in diffs:
                    print(f"  {d['from']} -> {d['to']}: "
                          f"{d.get('changed_pct', '?')}% changed, "
                          f"max_diff={d.get('max_diff', '?')}")
                print()

    # ── Summary ──────────────────────────────────────────────────────────
    all_sections_pass = True
    for name, section in report["sections"].items():
        if section.get("skipped"):
            continue
        if "pass" in section and not section["pass"]:
            all_sections_pass = False
        if "results" in section:
            for fr in section["results"]:
                if not all(c.get("pass", False) for c in fr.get("checks", [])):
                    all_sections_pass = False

    report["overall_pass"] = all_sections_pass

    # Write JSON report
    report_path = output_dir / "audit_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report written to {report_path}")
    print(f"Overall: {'PASS' if all_sections_pass else 'FAIL'}")

    return 0 if all_sections_pass else 1


if __name__ == "__main__":
    sys.exit(main())
