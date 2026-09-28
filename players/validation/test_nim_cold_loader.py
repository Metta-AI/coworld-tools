import importlib
import sys
from pathlib import Path

import pytest

from players.cogsguard.nim import agents, build


def test_cold_nim_build_invalidates_missing_binding_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindings = tmp_path / "generated"
    monkeypatch.setattr(sys, "path", [str(bindings), *sys.path])
    monkeypatch.setattr(agents, "_na", None)
    module_name = "pr24999_cold_nim_binding"
    original_import = importlib.import_module
    build_calls = []

    def import_binding(name: str):
        return original_import(module_name if name == "nim_agents" else name)

    def compile_binding():
        assert sys.path_importer_cache[str(bindings)] is None
        build_calls.append(True)
        bindings.mkdir()
        (bindings / f"{module_name}.py").write_text("version = 73\n")

    monkeypatch.setattr(importlib, "import_module", import_binding)
    monkeypatch.setattr(build, "build_nim", compile_binding)
    loaded = agents._nim_agents()
    assert loaded.version == 73
    assert Path(loaded.__file__).parent == bindings
    assert agents._nim_agents() is loaded
    assert build_calls == [True]
    del sys.modules[module_name]
