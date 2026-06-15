from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path


def test_importing_player_sdk_does_not_import_mettagrid() -> None:
    script = """
import sys
import players.player_sdk

mettagrid_modules = sorted(
    module for module in sys.modules if module == "mettagrid" or module.startswith("mettagrid.")
)
assert not mettagrid_modules, mettagrid_modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_coworld_json_bridge_is_the_only_sdk_file_importing_mettagrid() -> None:
    package_dir = _player_sdk_package_dir()

    actual = {
        path.relative_to(package_dir)
        for path in package_dir.rglob("*.py")
        if _imports_mettagrid(path)
    }

    assert actual == {Path("coworld_json_bridge.py")}


def test_telemetry_namespace_reexports_top_level_telemetry_symbols() -> None:
    import players.player_sdk as sdk
    from players.player_sdk import telemetry

    for name in telemetry.__all__:
        assert getattr(telemetry, name) is getattr(sdk, name)


def _player_sdk_package_dir() -> Path:
    spec = importlib.util.find_spec("players.player_sdk")
    assert spec is not None
    if spec.submodule_search_locations is not None:
        return Path(next(iter(spec.submodule_search_locations)))
    assert spec.origin is not None
    return Path(spec.origin).parent


def _imports_mettagrid(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_is_mettagrid_module(alias.name) for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if _is_mettagrid_module(node.module):
                return True
    return False


def _is_mettagrid_module(module: str) -> bool:
    return module == "mettagrid" or module.startswith("mettagrid.")
