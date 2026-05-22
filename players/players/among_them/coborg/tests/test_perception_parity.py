"""CI parity gate: assert every checked-in fixture parity-greens.

This is the canonical Sx done-criterion gate. Perception-layer changes
that break the oracle agreement get caught here. The test reuses the
same :mod:`run_parity` module that's exposed as the developer CLI, so a
human iterating on the port can run the exact same checks locally::

    uv run python -m players.among_them.coborg.perception.parity.run_parity

S2 first pass (sidecar ``schema_version == 1``) covers ``frame`` and
``sprite_match`` only -- the per-fixture check count reflects what the
oracle currently asserts (2 sprite_match entries + 2 actor_color_index
entries = 4 checks per fixture for 10 fixtures = 40 checks total). S3
and S4 widen this naturally as new schema fields land in the oracle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from players.among_them.coborg.perception.parity import run_parity
from players.among_them.coborg.perception.parity.run_parity import (
    FIXTURES_DIR,
    check_fixture,
    main,
    run_all,
)

_FIXTURE_BIN_NAMES = sorted(p.name for p in FIXTURES_DIR.glob("*.bin"))


def test_fixtures_dir_well_formed() -> None:
    """Every .bin must have a sibling .json sidecar and every .json must
    have a sibling .bin. Catches a mis-syncd commit in S3/S4 where someone
    adds a fixture but forgets to regenerate the oracle (or vice versa).
    """
    bins = {p.stem for p in FIXTURES_DIR.glob("*.bin")}
    jsons = {p.stem for p in FIXTURES_DIR.glob("*.json")}
    assert bins == jsons, f"orphan fixtures: bins-only={bins - jsons}, jsons-only={jsons - bins}"
    assert bins, "no fixtures found - did parity/fixtures/ get clobbered?"


@pytest.mark.parametrize("fixture_name", _FIXTURE_BIN_NAMES)
def test_each_fixture_parity_green(fixture_name: str) -> None:
    """Run the full parity rig per fixture and surface a useful diff if
    anything mismatches. Equivalent to a per-row of ``run_parity`` CLI.
    """
    result = check_fixture(FIXTURES_DIR / fixture_name)
    assert result.schema_version == 1, (
        f"{fixture_name}: schema_version {result.schema_version} not supported"
    )
    assert result.ok, "; ".join(
        c.line for c in result.checks if not c.ok
    )


def test_run_all_aggregates_every_fixture() -> None:
    results = run_all()
    assert len(results) == len(_FIXTURE_BIN_NAMES)
    assert all(r.ok for r in results)
    # Every fixture must contribute the same number of checks (the per-fixture
    # oracle is schema-rigid; a discrepancy points at a corrupt sidecar).
    counts = {len(r.checks) for r in results}
    assert len(counts) == 1, f"fixtures disagree on check count: {counts}"


def test_main_exits_zero_on_green(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0, f"main exited {rc}; output was:\n{captured.out}"
    assert "fixture(s) parity-green" in captured.out


def test_main_exits_nonzero_on_corrupt_sidecar(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Wire the CLI to a temp dir containing one fixture whose sidecar
    has been deliberately mangled. Must exit nonzero and surface the
    failing check in the report.
    """
    name = _FIXTURE_BIN_NAMES[0]
    bin_src = FIXTURES_DIR / name
    json_src = bin_src.with_suffix(".json")
    (tmp_path / name).write_bytes(bin_src.read_bytes())
    bad_sidecar = json.loads(json_src.read_text())
    # Mangle: claim the first sprite_match flip=False has one fake anchor.
    bad_sidecar["sprite_matches"][0]["anchors"] = [[123, 45]]
    (tmp_path / name).with_suffix(".json").write_text(json.dumps(bad_sidecar))

    rc = main(["--fixtures-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert f"FAIL  {bin_src.stem}" in captured.out
    assert "sprite_match" in captured.out


def test_main_handles_unsupported_schema_version(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An older / newer sidecar schema must fail loudly, not silently
    skip. Guards against S3/S4 regeneration accidents."""
    name = _FIXTURE_BIN_NAMES[0]
    bin_src = FIXTURES_DIR / name
    (tmp_path / name).write_bytes(bin_src.read_bytes())
    bad_sidecar = json.loads(bin_src.with_suffix(".json").read_text())
    bad_sidecar["schema_version"] = 999
    (tmp_path / name).with_suffix(".json").write_text(json.dumps(bad_sidecar))

    rc = main(["--fixtures-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "schema_version" in captured.out


def test_run_parity_module_is_importable_from_init() -> None:
    """The package-level import must succeed so the CLI invocation
    ``python -m players.among_them.coborg.perception.parity.run_parity``
    works from a fresh process."""
    assert run_parity.FIXTURES_DIR.exists()
    assert callable(run_parity.check_fixture)
    assert callable(run_parity.run_all)
    assert callable(run_parity.main)
