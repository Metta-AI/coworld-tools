"""Tests for the Tribal Village build helpers."""

import importlib.util
from pathlib import Path

import tribal_village_env
from tribal_village_env import build


def test_collect_source_files_limits_rebuild_inputs():
    root = Path(__file__).resolve().parent.parent
    rel_paths = {path.relative_to(root).as_posix() for path in build._collect_source_files(root)}

    assert "tribal_village.nim" in rel_paths
    assert "tribal_village.nimble" in rel_paths
    assert any(path.startswith("src/") for path in rel_paths)
    assert not any(path.startswith("tests/") for path in rel_paths)
    assert not any(path.startswith("scripts/") for path in rel_paths)


def test_package_exports_are_lazy():
    assert "TribalVillageEnv" not in tribal_village_env.__dict__

    ensure = tribal_village_env.ensure_nim_library_current

    assert callable(ensure)
    assert "ensure_nim_library_current" in tribal_village_env.__dict__


def test_get_runtime_project_root_prefers_packaged_runtime(tmp_path):
    package_dir = tmp_path / "tribal_village_env"
    runtime_root = package_dir / "runtime"
    runtime_root.mkdir(parents=True)
    (runtime_root / "tribal_village.nim").write_text("", encoding="utf-8")
    (runtime_root / "src").mkdir()

    assert build.get_runtime_project_root(package_dir) == runtime_root


def test_copy_runtime_assets_packages_gui_runtime_payload(tmp_path):
    setup_path = Path(__file__).resolve().parent.parent / "setup.py"
    spec = importlib.util.spec_from_file_location("tribal_village_setup", setup_path)
    assert spec is not None and spec.loader is not None
    setup_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup_module)

    setup_module._copy_runtime_assets(str(tmp_path))

    runtime_root = tmp_path / "tribal_village_env" / "runtime"
    assert (runtime_root / "tribal_village.nim").exists()
    assert (runtime_root / "tribal_village.nimble").exists()
    assert (runtime_root / "nim.cfg").exists()
    assert (runtime_root / "nimby.lock").exists()
    assert (runtime_root / "src" / "ffi.nim").exists()
    assert (runtime_root / "data" / "grass.png").exists()
