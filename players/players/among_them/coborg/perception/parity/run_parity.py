"""Parity gate: run every ported Python perception kernel against every
checked-in fixture and compare the result to the Nim oracle sidecar.

Usable two ways:

1. As a CLI for ad-hoc developer inspection during the port::

       uv run python -m players.among_them.coborg.perception.parity.run_parity

   Prints one line per fixture (``OK`` / ``FAIL``), followed by a per-kind
   diff for each failure, then a summary line. Exits 0 iff every fixture
   parity-greens.

2. As an importable helper from ``tests/test_perception_parity.py``, which
   asserts the same condition as the CI gate.

Schema scope:

- **v1 (S2):** kernel-level outputs for the player sprite at crewmate
  budgets, both flips. Checked by ``_check_sprite_match`` and
  ``_check_actor_color_index``.
- **v2 (S3 kickoff, this harness):** kernel-level coverage widened to
  body + ghost sprites at their own budgets. The same kernel-level
  checks run unchanged — they iterate the per-(sprite, flip) entries
  in ``sprite_matches`` / ``actor_color_index``, which now contain 5
  entries (player×2 flips + body×1 + ghost×2 flips) instead of 2.
  v2 also introduces orchestrated fields (``role``, ``self_color``,
  ``crewmates``, ``bodies``, ``ghosts``, ``radar_dots``) that are
  emitted by the Nim oracle but **not yet checked here**; concrete
  check functions land alongside the matching Python ports in S3.2
  (``actors.py``) and S3.3 (``tasks.py`` radar-dot half).
- **v3 (S4.1):** adds the upstream ``interstitial.detect_interstitial``
  output (black-pixel count + is/is-not + kind). Checked by
  ``_check_interstitial``.
- **S4.2 onward** extend v3 with ignore-mask stamps, then v4 with
  localize / task-icons, then v5 with ocr and voting.

Tolerance policy: every assertion in S2 is **exact** equality. The Nim
oracle and the Python port are both deterministic over integer
operations on palette-index data; there is nothing to be tolerant about.
Later stack entries may introduce sub-pixel localize fields with an
explicit tolerance; that will be documented inline when it lands.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

import hashlib

from ..actors import ActorPercept, compute_actor_percept
from ..data import load_map_pixels, load_sprite_atlas
from ..frame import SCREEN_HEIGHT, SCREEN_WIDTH
from ..ignore import build_phase_1_0_ignore_mask
from ..interstitial import InterstitialObservation, detect_interstitial
from ..localize import (
    FULL_FRAME_FIT_MAX_ERRORS,
    PATCH_TOTAL_COUNT,
    get_patch_index,
    hash_frame_patches,
    score_camera,
    update_location,
    vote_camera_candidates,
)
from ..sprite_match import actor_color_index_all, match_actor_sprite_all
from ..tasks import scan_radar_dots

FIXTURES_DIR: Path = (Path(__file__).resolve().parent / "fixtures").resolve()

_SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2, 3, 4})


@dataclass
class CheckResult:
    """One kernel comparison's outcome for one fixture."""

    label: str
    ok: bool
    detail: str = ""

    @property
    def line(self) -> str:
        return f"OK   {self.label}" if self.ok else f"FAIL {self.label}: {self.detail}"


@dataclass
class FixtureResult:
    """Aggregated parity outcome for one fixture."""

    name: str
    schema_version: int
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.ok)


def _load_unpacked_frame(path: Path) -> np.ndarray:
    return np.frombuffer(path.read_bytes(), dtype=np.uint8).reshape(
        (SCREEN_HEIGHT, SCREEN_WIDTH)
    )


def _check_sprite_match(frame: np.ndarray, sprite: np.ndarray, entry: dict) -> CheckResult:
    label = f"sprite_match[{entry['sprite']}, flip_h={entry['flip_h']}]"
    mask = match_actor_sprite_all(
        frame,
        sprite,
        flip_h=entry["flip_h"],
        max_misses=entry["max_misses"],
        min_stable=entry["min_stable"],
        min_tint=entry["min_tint"],
    )
    ys, xs = np.where(mask)
    actual = sorted(zip(ys.tolist(), xs.tolist()))
    expected = [tuple(a) for a in entry["anchors"]]
    if actual == expected:
        return CheckResult(label=label, ok=True)
    return CheckResult(
        label=label,
        ok=False,
        detail=f"got {actual!r}, expected {expected!r}",
    )


def _check_actor_color_index(frame: np.ndarray, sprite: np.ndarray, entry: dict) -> CheckResult:
    label = f"actor_color_index[{entry['sprite']}, flip_h={entry['flip_h']}]"
    ci = actor_color_index_all(frame, sprite, flip_h=entry["flip_h"])
    mismatches: list[str] = []
    for ay, ax, expected_idx in entry["indices"]:
        got = int(ci[ay, ax])
        if got != int(expected_idx):
            mismatches.append(f"({ay},{ax}): got {got}, want {expected_idx}")
    if not mismatches:
        return CheckResult(label=label, ok=True)
    return CheckResult(
        label=label,
        ok=False,
        detail="; ".join(mismatches),
    )


# --- v2 orchestrated checks (actors.py outputs) ----------------------------


def _check_role(percept: ActorPercept, expected: dict) -> CheckResult:
    actual = {
        "ghost_icon_frames": percept.ghost_icon_frames,
        "kill_icon_frames": percept.kill_icon_frames,
        "is_ghost": percept.is_ghost,
        "kill_ready": percept.kill_ready,
        "role_updated": percept.role_updated,
        "new_role": percept.new_role.value,
    }
    if actual == expected:
        return CheckResult(label="role", ok=True)
    return CheckResult(label="role", ok=False, detail=f"got {actual!r}, expected {expected!r}")


def _check_self_color(percept: ActorPercept, expected: dict) -> CheckResult:
    actual = {"updated": percept.self_color_updated, "color_index": percept.new_self_color}
    if actual == expected:
        return CheckResult(label="self_color", ok=True)
    return CheckResult(
        label="self_color", ok=False, detail=f"got {actual!r}, expected {expected!r}"
    )


def _check_crewmates(percept: ActorPercept, expected: list[dict]) -> CheckResult:
    actual = [
        {"x": m.x, "y": m.y, "color_index": m.color_index, "flip_h": m.flip_h}
        for m in percept.crewmates
    ]
    if actual == expected:
        return CheckResult(label="crewmates", ok=True)
    return CheckResult(
        label="crewmates",
        ok=False,
        detail=f"got {len(actual)} ({actual!r}), expected {len(expected)} ({expected!r})",
    )


def _check_bodies(percept: ActorPercept, expected: list[dict]) -> CheckResult:
    actual = [{"x": m.x, "y": m.y, "color_index": m.color_index} for m in percept.bodies]
    if actual == expected:
        return CheckResult(label="bodies", ok=True)
    return CheckResult(
        label="bodies",
        ok=False,
        detail=f"got {len(actual)} ({actual!r}), expected {len(expected)} ({expected!r})",
    )


def _check_ghosts(percept: ActorPercept, expected: list[dict]) -> CheckResult:
    actual = [{"x": m.x, "y": m.y, "flip_h": m.flip_h} for m in percept.ghosts]
    if actual == expected:
        return CheckResult(label="ghosts", ok=True)
    return CheckResult(
        label="ghosts",
        ok=False,
        detail=f"got {len(actual)} ({actual!r}), expected {len(expected)} ({expected!r})",
    )


def _check_radar_dots(frame: np.ndarray, expected: list[dict]) -> CheckResult:
    """Run ``scan_radar_dots`` against ``frame`` and compare against the
    oracle's ``radar_dots`` entry."""
    actual = [{"x": d.x, "y": d.y} for d in scan_radar_dots(frame)]
    if actual == expected:
        return CheckResult(label="radar_dots", ok=True)
    return CheckResult(
        label="radar_dots",
        ok=False,
        detail=f"got {len(actual)} ({actual!r}), expected {len(expected)} ({expected!r})",
    )


# --- v3 orchestrated checks (interstitial.py output) ----------------------


def _check_interstitial(obs: InterstitialObservation, expected: dict) -> CheckResult:
    actual = {
        "is_interstitial": obs.is_interstitial,
        "kind": obs.kind.value,
        "black_pixel_count": obs.black_pixel_count,
    }
    if actual == expected:
        return CheckResult(label="interstitial", ok=True)
    return CheckResult(
        label="interstitial", ok=False, detail=f"got {actual!r}, expected {expected!r}"
    )


def _check_ignore_phase_1_0(frame: np.ndarray, expected: dict) -> CheckResult:
    """Build the phase-1.0 ignore mask in Python and compare against the
    oracle's stamped-pixel count + SHA-1 fingerprint over the raw mask
    bytes. The Nim side serialises ``IgnoreMask.data`` (uint8 0/1,
    row-major); ``mask.tobytes()`` on a numpy bool ndarray produces the
    same 16384-byte sequence, so the SHA-1 strings match exactly."""
    mask = build_phase_1_0_ignore_mask(frame)
    actual = {
        "stamped_pixel_count": int(mask.sum()),
        "sha1": hashlib.sha1(mask.tobytes()).hexdigest().upper(),
    }
    if actual == expected:
        return CheckResult(label="ignore_phase_1_0", ok=True)
    return CheckResult(
        label="ignore_phase_1_0",
        ok=False,
        detail=f"got {actual!r}, expected {expected!r}",
    )


# --- v4 orchestrated checks (localize.py output) --------------------------


def _check_score_camera_probes(
    frame: np.ndarray, ignore_mask: np.ndarray, expected_list: list[dict]
) -> CheckResult:
    """Run ``score_camera`` at the oracle-recorded probe positions and
    compare the full ``(score, errors, compared)`` triple per probe."""
    map_pixels = load_map_pixels()
    mismatches: list[str] = []
    for exp in expected_list:
        cx = int(exp["cam_x"])
        cy = int(exp["cam_y"])
        sc = score_camera(
            frame, map_pixels, ignore_mask, cx, cy, FULL_FRAME_FIT_MAX_ERRORS
        )
        actual = {
            "cam_x": cx,
            "cam_y": cy,
            "score": sc.score,
            "errors": sc.errors,
            "compared": sc.compared,
        }
        if actual != exp:
            mismatches.append(f"at ({cx},{cy}): got {actual!r} vs {exp!r}")
    if not mismatches:
        return CheckResult(label="score_camera_probes", ok=True)
    return CheckResult(
        label="score_camera_probes", ok=False, detail="; ".join(mismatches)
    )


def _check_frame_patch_hashes(
    frame: np.ndarray, ignore_mask: np.ndarray, expected: dict
) -> CheckResult:
    """Compare the full 16x16 grid of FNV patch hashes (as uint64 hex
    strings) plus the parallel validity bool array."""
    py_hashes, py_valid = hash_frame_patches(frame, ignore_mask)
    expected_hashes = [int(h, 16) for h in expected["hashes"]]
    expected_valid = [bool(v) for v in expected["valid"]]
    actual_hashes = [int(h) for h in py_hashes.tolist()]
    actual_valid = [bool(v) for v in py_valid.tolist()]
    if actual_hashes == expected_hashes and actual_valid == expected_valid:
        return CheckResult(label="frame_patch_hashes", ok=True)
    # Find the first mismatch for a concise diff.
    for i in range(PATCH_TOTAL_COUNT):
        if actual_hashes[i] != expected_hashes[i] or actual_valid[i] != expected_valid[i]:
            return CheckResult(
                label="frame_patch_hashes",
                ok=False,
                detail=(
                    f"first mismatch at patch {i}: "
                    f"got (hash={actual_hashes[i]:016X}, valid={actual_valid[i]}), "
                    f"expected (hash={expected_hashes[i]:016X}, valid={expected_valid[i]})"
                ),
            )
    return CheckResult(label="frame_patch_hashes", ok=False, detail="unknown mismatch")


def _check_patch_vote_top_candidates(
    frame: np.ndarray, ignore_mask: np.ndarray, expected_list: list[dict]
) -> CheckResult:
    """Compare the top-K output of the patch-vote kernel byte-for-byte."""
    frame_hashes, frame_valid = hash_frame_patches(frame, ignore_mask)
    candidates = vote_camera_candidates(frame_hashes, frame_valid, get_patch_index())
    actual_list = [
        {"cam_x": c.cx, "cam_y": c.cy, "votes": c.votes} for c in candidates
    ]
    if actual_list == expected_list:
        return CheckResult(label="patch_vote_top_candidates", ok=True)
    return CheckResult(
        label="patch_vote_top_candidates",
        ok=False,
        detail=(
            f"got {len(actual_list)} entries {actual_list!r}, "
            f"expected {len(expected_list)} entries {expected_list!r}"
        ),
    )


def _check_localize_first_frame(
    frame: np.ndarray, ignore_mask: np.ndarray, expected: dict
) -> CheckResult:
    """Run ``update_location`` from a fresh state and compare the
    camera-related fields against the oracle."""
    state = update_location(None, frame, ignore_mask, tick=0)
    actual = {
        "camera_x": state.camera_x,
        "camera_y": state.camera_y,
        "camera_score": state.camera_score,
        "camera_lock": state.camera_lock.value,
        "localized": state.localized,
        "self_x": state.self_x,
        "self_y": state.self_y,
    }
    if actual == expected:
        return CheckResult(label="localize_first_frame", ok=True)
    return CheckResult(
        label="localize_first_frame",
        ok=False,
        detail=f"got {actual!r}, expected {expected!r}",
    )


def check_fixture(bin_path: Path) -> FixtureResult:
    """Run every supported kernel against ``bin_path`` and compare to the
    sibling JSON sidecar. Returns a structured result; never raises on
    mismatch (callers decide how to surface failures).
    """
    json_path = bin_path.with_suffix(".json")
    sidecar = json.loads(json_path.read_text())
    schema_version = int(sidecar.get("schema_version", 0))
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        return FixtureResult(
            name=bin_path.stem,
            schema_version=schema_version,
            checks=[
                CheckResult(
                    label="schema_version",
                    ok=False,
                    detail=f"unsupported schema_version {schema_version}; "
                    f"run_parity knows {sorted(_SUPPORTED_SCHEMA_VERSIONS)}",
                )
            ],
        )

    frame = _load_unpacked_frame(bin_path)
    atlas = load_sprite_atlas()
    result = FixtureResult(name=bin_path.stem, schema_version=schema_version)
    for entry in sidecar["sprite_matches"]:
        result.checks.append(_check_sprite_match(frame, atlas[entry["atlas_index"]], entry))
    for entry in sidecar["actor_color_index"]:
        result.checks.append(_check_actor_color_index(frame, atlas[entry["atlas_index"]], entry))
    if schema_version >= 2:
        percept = compute_actor_percept(atlas, frame)
        result.checks.append(_check_role(percept, sidecar["role"]))
        result.checks.append(_check_self_color(percept, sidecar["self_color"]))
        result.checks.append(_check_crewmates(percept, sidecar["crewmates"]))
        result.checks.append(_check_bodies(percept, sidecar["bodies"]))
        result.checks.append(_check_ghosts(percept, sidecar["ghosts"]))
        result.checks.append(_check_radar_dots(frame, sidecar["radar_dots"]))
    if schema_version >= 3:
        result.checks.append(
            _check_interstitial(detect_interstitial(frame), sidecar["interstitial"])
        )
        if "ignore_phase_1_0" in sidecar:  # additive within v3; S4.2+ sidecars carry it
            result.checks.append(
                _check_ignore_phase_1_0(frame, sidecar["ignore_phase_1_0"])
            )
    if schema_version >= 4:
        # The localize kernels consume the phase-1.0 ignore mask. Build
        # it once here and feed all four v4 checks.
        ignore_mask = build_phase_1_0_ignore_mask(frame)
        result.checks.append(
            _check_score_camera_probes(frame, ignore_mask, sidecar["score_camera_probes"])
        )
        result.checks.append(
            _check_frame_patch_hashes(frame, ignore_mask, sidecar["frame_patch_hashes"])
        )
        result.checks.append(
            _check_patch_vote_top_candidates(
                frame, ignore_mask, sidecar["patch_vote_top_candidates"]
            )
        )
        result.checks.append(
            _check_localize_first_frame(
                frame, ignore_mask, sidecar["localize_first_frame"]
            )
        )
    return result



def run_all(fixtures_dir: Path = FIXTURES_DIR) -> list[FixtureResult]:
    """Run :func:`check_fixture` over every ``*.bin`` in ``fixtures_dir``,
    in stable sorted order. Returns the per-fixture results.
    """
    return [check_fixture(p) for p in sorted(fixtures_dir.glob("*.bin"))]


def _format_report(results: Iterable[FixtureResult], verbose: bool) -> str:
    lines: list[str] = []
    total_checks = 0
    total_fails = 0
    fixture_pass = 0
    fixture_total = 0
    for result in results:
        fixture_total += 1
        total_checks += len(result.checks)
        total_fails += result.fail_count
        if result.ok:
            fixture_pass += 1
            if verbose:
                lines.append(f"OK    {result.name}  ({len(result.checks)} checks)")
            else:
                lines.append(f"OK    {result.name}")
        else:
            lines.append(f"FAIL  {result.name}  ({result.fail_count}/{len(result.checks)} bad)")
            for check in result.checks:
                if not check.ok:
                    lines.append(f"        {check.line}")
    lines.append("")
    lines.append(
        f"{fixture_pass}/{fixture_total} fixture(s) parity-green; "
        f"{total_checks - total_fails}/{total_checks} parity checks ok"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the among-them-coborg perception parity rig over the fixture set.",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=FIXTURES_DIR,
        help=f"Directory of *.bin fixtures + *.json sidecars (default: {FIXTURES_DIR}).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print the per-fixture check count even on success.",
    )
    args = parser.parse_args(argv)
    results = run_all(args.fixtures_dir)
    print(_format_report(results, verbose=args.verbose))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":  # pragma: no cover -- exercised via tests/CLI
    sys.exit(main())
