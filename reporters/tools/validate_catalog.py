"""Validate the repo-root CATALOG.yaml against the spec-0045 schema.

Spec source of truth: docs/specs/0045-coworld-role-repos.md in metta
(§"CATALOG.yaml schema").

Checks, per entry:
- All required fields are present and non-empty
  (`name`, `image`, `source`, `source_url`, `status`, `target`,
   `owner`, `description`).
- `status` is one of the spec-0045 enum values
  (`active`, `starter`, `experimental`, `archived`).
- `source` is a relative path that exists on disk under the repo root.
- `image` is a non-empty string. We do NOT check whether the image
  actually pulls — that's a separate concern (image-publish CI).
- `name` values are unique.

Exits 0 on success, 1 with a clear error on failure. Usage:

    python tools/validate_catalog.py                  # validate CATALOG.yaml at repo root
    python tools/validate_catalog.py path/to/cat.yaml # validate an explicit catalog

Run via CI in .github/workflows/validate-catalog.yml.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FIELDS = (
    "name",
    "image",
    "source",
    "source_url",
    "status",
    "target",
    "owner",
    "description",
)

# Spec 0045 status enum (docs/specs/0045-coworld-role-repos.md §CATALOG.yaml).
ALLOWED_STATUSES = frozenset({"active", "starter", "experimental", "archived"})


def validate_catalog(catalog_path: Path) -> list[str]:
    """Return a list of error messages; empty list means valid."""
    errors: list[str] = []

    if not catalog_path.exists():
        return [f"CATALOG file not found: {catalog_path}"]

    try:
        data = yaml.safe_load(catalog_path.read_text())
    except yaml.YAMLError as exc:
        return [f"CATALOG YAML parse error: {exc}"]

    if not isinstance(data, dict) or "entries" not in data:
        return ["CATALOG must be a mapping with a top-level `entries:` key"]

    entries = data["entries"]
    if not isinstance(entries, list) or not entries:
        return ["CATALOG `entries` must be a non-empty list"]

    repo_root = catalog_path.resolve().parent
    seen_names: set[str] = set()

    for i, entry in enumerate(entries):
        prefix = f"entry[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: must be a mapping, got {type(entry).__name__}")
            continue

        name = entry.get("name")
        if isinstance(name, str) and name:
            prefix = f"entry[{i}] {name!r}"
            if name in seen_names:
                errors.append(f"{prefix}: duplicate name (names must be unique)")
            seen_names.add(name)

        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}: missing or empty required field {field!r}")

        status = entry.get("status")
        if isinstance(status, str) and status not in ALLOWED_STATUSES:
            errors.append(
                f"{prefix}: status {status!r} not in {sorted(ALLOWED_STATUSES)}"
            )

        source = entry.get("source")
        if isinstance(source, str) and source:
            source_path = repo_root / source
            if not source_path.exists():
                errors.append(
                    f"{prefix}: source path {source!r} does not exist on disk "
                    f"(resolved to {source_path})"
                )

    return errors


def _self_test() -> None:
    """Tiny self-test: confirm validator catches at least one failure mode.

    Runs in-memory against a known-bad catalog. Used by the `--self-test`
    CLI flag and by tools/tests/test_validate_catalog.py for proper
    pytest coverage of the catch paths.
    """
    import tempfile

    bad = {
        "entries": [
            {
                # missing several required fields; bad status; nonexistent source
                "name": "broken",
                "image": "ghcr.io/example:latest",
                "source": "definitely/does/not/exist",
                "status": "scaffold",  # not in enum
            }
        ]
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as tmp:
        yaml.safe_dump(bad, tmp)
        tmp_path = Path(tmp.name)
    try:
        errors = validate_catalog(tmp_path)
    finally:
        tmp_path.unlink()
    if not errors:
        raise SystemExit("self-test failed: validator did not flag obvious errors")
    print(f"self-test ok: validator flagged {len(errors)} error(s) on a bad catalog")


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "--self-test":
        _self_test()
        return 0

    catalog_path = (
        Path(argv[1])
        if len(argv) > 1
        else Path(__file__).resolve().parent.parent / "CATALOG.yaml"
    )

    errors = validate_catalog(catalog_path)
    if errors:
        print(f"CATALOG validation FAILED ({catalog_path}):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # Brief positive output so CI logs show what we validated.
    data: dict[str, Any] = yaml.safe_load(catalog_path.read_text())
    n = len(data.get("entries", []))
    print(f"CATALOG validation ok: {n} entr{'y' if n == 1 else 'ies'} ({catalog_path})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
