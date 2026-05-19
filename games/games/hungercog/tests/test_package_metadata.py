from __future__ import annotations

from pathlib import Path
import tomllib


def test_standalone_package_depends_on_unpinned_shared_packages() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text())

    dependencies = pyproject["project"]["dependencies"]

    assert "cogames" in dependencies
    assert "mettagrid" in dependencies
    assert "cogames>=0.25.0" not in dependencies
    assert "mettagrid>=0.25.4" not in dependencies
