"""Tests for tools/validate_catalog.py.

These exercise the validator's catch paths against synthetic catalogs.
The "happy path" test runs against the real repo-root CATALOG.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from validate_catalog import REQUIRED_FIELDS, validate_catalog

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _write_catalog(tmp_path: Path, data: dict) -> Path:
    """Write `data` to a CATALOG.yaml under `tmp_path`. The validator
    resolves `source` relative to the catalog's parent directory, so we
    place the file at tmp_path/CATALOG.yaml and create source dirs as
    siblings."""
    catalog_path = tmp_path / "CATALOG.yaml"
    catalog_path.write_text(yaml.safe_dump(data))
    return catalog_path


def _minimal_entry(tmp_path: Path, **overrides) -> dict:
    """Return a valid catalog entry, creating its source dir on disk."""
    source = "impls/example"
    (tmp_path / source).mkdir(parents=True, exist_ok=True)
    entry = {
        "name": "example-reporter",
        "image": "ghcr.io/example/reporters-example:latest",
        "source": source,
        "source_url": "https://github.com/Metta-AI/coworld-tools/tree/main/reporters/impls/example",
        "status": "active",
        "target": "paint_arena",
        "owner": "jboggs",
        "description": "Example reporter for tests.",
    }
    entry.update(overrides)
    return entry


def test_real_catalog_validates() -> None:
    """The real CATALOG.yaml at the repo root passes validation."""
    errors = validate_catalog(REPO_ROOT / "CATALOG.yaml")
    assert errors == [], f"real CATALOG.yaml failed validation: {errors}"


def test_missing_catalog_file(tmp_path: Path) -> None:
    errors = validate_catalog(tmp_path / "does-not-exist.yaml")
    assert errors and "not found" in errors[0]


def test_malformed_yaml(tmp_path: Path) -> None:
    bad = tmp_path / "CATALOG.yaml"
    bad.write_text(": this is not valid YAML: : :")
    errors = validate_catalog(bad)
    assert errors and "parse error" in errors[0]


def test_missing_entries_key(tmp_path: Path) -> None:
    catalog_path = _write_catalog(tmp_path, {"not_entries": []})
    errors = validate_catalog(catalog_path)
    assert errors and "entries" in errors[0]


def test_empty_entries(tmp_path: Path) -> None:
    catalog_path = _write_catalog(tmp_path, {"entries": []})
    errors = validate_catalog(catalog_path)
    assert errors and "non-empty" in errors[0]


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_missing_required_field(tmp_path: Path, field: str) -> None:
    entry = _minimal_entry(tmp_path)
    del entry[field]
    catalog_path = _write_catalog(tmp_path, {"entries": [entry]})
    errors = validate_catalog(catalog_path)
    assert any(field in err for err in errors), (
        f"validator did not flag missing {field!r}: {errors}"
    )


def test_invalid_status(tmp_path: Path) -> None:
    entry = _minimal_entry(tmp_path, status="scaffold")  # not in spec-0045 enum
    catalog_path = _write_catalog(tmp_path, {"entries": [entry]})
    errors = validate_catalog(catalog_path)
    assert any("status" in err and "scaffold" in err for err in errors), errors


def test_missing_source_path(tmp_path: Path) -> None:
    entry = _minimal_entry(tmp_path, source="does/not/exist")
    catalog_path = _write_catalog(tmp_path, {"entries": [entry]})
    errors = validate_catalog(catalog_path)
    assert any("does not exist" in err for err in errors), errors


def test_duplicate_names(tmp_path: Path) -> None:
    entry1 = _minimal_entry(tmp_path)
    entry2 = _minimal_entry(tmp_path)  # same name
    catalog_path = _write_catalog(tmp_path, {"entries": [entry1, entry2]})
    errors = validate_catalog(catalog_path)
    assert any("duplicate" in err for err in errors), errors
