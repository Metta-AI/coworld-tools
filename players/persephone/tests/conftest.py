"""Shared fixtures and helpers for perception integration tests.

Loads .npy frame fixtures and their associated .json expected-output files
from the tests/fixtures/ directory. Provides parametrization helpers and
assertion utilities for the test suite.
"""

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from perception import parse_frame
from perception.types import FramePerception, View

# ---------------------------------------------------------------------------
# Fixture directory
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"


# ---------------------------------------------------------------------------
# Fixture data class
# ---------------------------------------------------------------------------


class FixtureData:
    """A loaded test fixture: frame + expected assertions."""

    def __init__(self, name: str, frame: np.ndarray, expected: dict):
        self.name = name
        self.frame = frame
        self.expected = expected
        self.view = expected["view"]
        self.assertions = expected.get("assertions", {})
        self.known_bugs = expected.get("known_bugs", [])
        self.note = expected.get("note", "")

    def __repr__(self) -> str:
        return f"Fixture({self.name!r}, view={self.view})"


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def load_manifest() -> list[dict]:
    """Load the fixture manifest."""
    if not MANIFEST_PATH.is_file():
        return []
    with open(MANIFEST_PATH) as f:
        data = json.load(f)
    return data.get("fixtures", [])


def load_fixture(name: str) -> FixtureData:
    """Load a single fixture by name."""
    npy_path = FIXTURES_DIR / f"{name}.npy"
    json_path = FIXTURES_DIR / f"{name}.json"

    if not npy_path.is_file():
        raise FileNotFoundError(f"Fixture frame not found: {npy_path}")
    if not json_path.is_file():
        raise FileNotFoundError(f"Fixture expected not found: {json_path}")

    frame = np.load(npy_path)
    with open(json_path) as f:
        expected = json.load(f)

    return FixtureData(name, frame, expected)


def all_fixtures() -> list[FixtureData]:
    """Load all fixtures listed in the manifest."""
    manifest = load_manifest()
    fixtures = []
    for entry in manifest:
        try:
            fixtures.append(load_fixture(entry["name"]))
        except FileNotFoundError as e:
            pytest.skip(f"Fixture not found: {e}")
    return fixtures


def fixtures_for_view(view: str) -> list[FixtureData]:
    """Load all fixtures for a specific view type."""
    return [f for f in all_fixtures() if f.view == view]


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def get_nested(obj: Any, path: str) -> Any:
    """Resolve a dot-separated path on an object.

    Example: get_nested(perc, "overworld.room") returns perc.overworld.room
    """
    parts = path.split(".")
    current = obj
    for part in parts:
        if current is None:
            return None
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def assert_field(result: FramePerception, path: str, spec: Any) -> None:
    """Evaluate a hybrid assertion spec against a nested field.

    Spec types:
      - bare value: exact equality
      - {"not_none": true}: field is not None
      - {"gte": N}: field >= N
      - {"lte": N}: field <= N
      - {"gte": N, "lte": M}: N <= field <= M
      - {"startswith": S}: str(field).startswith(S)
      - {"in": [...]}: field in list
    """
    val = get_nested(result, path)

    if isinstance(spec, dict):
        if spec.get("not_none"):
            assert val is not None, f"{path} expected not None, got None"
        if "gte" in spec:
            assert val is not None, f"{path} expected >= {spec['gte']}, got None"
            assert val >= spec["gte"], f"{path} expected >= {spec['gte']}, got {val}"
        if "lte" in spec:
            assert val is not None, f"{path} expected <= {spec['lte']}, got None"
            assert val <= spec["lte"], f"{path} expected <= {spec['lte']}, got {val}"
        if "startswith" in spec:
            assert val is not None, f"{path} expected startswith {spec['startswith']!r}, got None"
            assert str(val).startswith(spec["startswith"]), (
                f"{path} expected startswith {spec['startswith']!r}, got {val!r}"
            )
        if "in" in spec:
            assert val in spec["in"], f"{path} expected in {spec['in']}, got {val!r}"
    else:
        # Exact match
        # Handle enum values: if val has a .value attribute, compare against that
        actual = val.value if hasattr(val, "value") else val
        assert actual == spec, f"{path} expected {spec!r}, got {actual!r}"


def assert_fixture(result: FramePerception, fixture: FixtureData) -> None:
    """Run all assertions from a fixture against a parse result."""
    for path, spec in fixture.assertions.items():
        # Handle count suffixes: "overworld.minimap_dot_count" means
        # len(overworld.minimap_dots) -- but only if the direct field
        # doesn't exist.  Fields like "lobby.player_count" are direct
        # integer fields, not derived list counts.
        if path.endswith("_count"):
            # First try the direct field path
            direct_val = get_nested(result, path)
            if direct_val is not None:
                # Direct field exists -- assert against it normally
                assert_field(result, path, spec)
                continue

            # Fall back to list-counting. Try multiple patterns:
            # foo_count -> foos, foo_count -> foo (for already-plural names)
            base_path = path[:-6]  # strip "_count"
            val = get_nested(result, base_path + "s")
            if val is None:
                val = get_nested(result, base_path)
            # Also try common list field patterns (e.g., occupant_count -> occupant_colors)
            if val is None:
                # Try stripping further to find the actual list
                parts = base_path.rsplit(".", 1)
                if len(parts) == 2:
                    parent = get_nested(result, parts[0])
                    if parent is not None:
                        # Look for any list attribute starting with the field stem
                        stem = parts[1]
                        for attr_name in dir(parent):
                            if attr_name.startswith(stem) and not attr_name.startswith("_"):
                                candidate = getattr(parent, attr_name, None)
                                if isinstance(candidate, (list, tuple)):
                                    val = candidate
                                    break

            actual_count = len(val) if val is not None else 0
            if isinstance(spec, dict):
                if "gte" in spec:
                    assert actual_count >= spec["gte"], (
                        f"{path} expected >= {spec['gte']}, got {actual_count}"
                    )
                if "lte" in spec:
                    assert actual_count <= spec["lte"], (
                        f"{path} expected <= {spec['lte']}, got {actual_count}"
                    )
            else:
                assert actual_count == spec, (
                    f"{path} expected {spec}, got {actual_count}"
                )
        else:
            assert_field(result, path, spec)


# ---------------------------------------------------------------------------
# Pytest parametrize IDs
# ---------------------------------------------------------------------------


def fixture_ids(fixtures: list[FixtureData]) -> list[str]:
    """Generate readable test IDs from fixture names."""
    return [f.name for f in fixtures]
