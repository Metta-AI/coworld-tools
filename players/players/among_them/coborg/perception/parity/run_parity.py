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
- **S4** will bump the schema again to add the deferred task-icon scan
  plus ``ocr``, ``voting``, ``interstitial``, ``localize``, and
  ``ignore`` percept fields.

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

from ..data import load_sprite_atlas
from ..frame import SCREEN_HEIGHT, SCREEN_WIDTH
from ..sprite_match import actor_color_index_all, match_actor_sprite_all

FIXTURES_DIR: Path = (Path(__file__).resolve().parent / "fixtures").resolve()

_SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1, 2})


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
        f"{total_checks - total_fails}/{total_checks} kernel checks ok"
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
