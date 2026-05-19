#!/usr/bin/env python3
"""
Setup script for tribal-village that builds the Nim shared library.
"""

from importlib import util
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.develop import develop
from setuptools.command.install import install

_RUNTIME_FILES = (
    "tribal_village.nim",
    "tribal_village.nimble",
    "nim.cfg",
    "nimby.lock",
)
_RUNTIME_DIRS = ("data", "src")


def _load_build_helpers():
    """Load tribal_village_env.build without mutating sys.path."""
    project_root = Path(__file__).parent
    build_path = project_root / "tribal_village_env" / "build.py"
    spec = util.spec_from_file_location("tribal_village_env.build", build_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load build helpers from {build_path}")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module.ensure_nim_library_current


def _copy_runtime_assets(build_lib: str) -> None:
    project_root = Path(__file__).parent
    runtime_root = Path(build_lib) / "tribal_village_env" / "runtime"
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)

    for filename in _RUNTIME_FILES:
        shutil.copy2(project_root / filename, runtime_root / filename)
    for dirname in _RUNTIME_DIRS:
        shutil.copytree(project_root / dirname, runtime_root / dirname)


class BuildNimLibrary:
    """Mixin class to build the Nim shared library."""

    def build_nim_library(self):
        """Build or refresh the Nim shared library using nimby + nim."""
        print("Building Nim shared library via nimby...")
        ensure_nim_library_current = _load_build_helpers()
        ensure_nim_library_current(verbose=True)


class CustomBuildPy(build_py, BuildNimLibrary):
    """Custom build_py that builds Nim library first."""

    def run(self):
        self.build_nim_library()
        super().run()
        _copy_runtime_assets(self.build_lib)


class CustomDevelop(develop, BuildNimLibrary):
    """Custom develop that builds Nim library first."""

    def run(self):
        self.build_nim_library()
        super().run()


class CustomInstall(install, BuildNimLibrary):
    """Custom install that builds Nim library first."""

    def run(self):
        self.build_nim_library()
        super().run()


if __name__ == "__main__":
    setup(
        cmdclass={
            "build_py": CustomBuildPy,
            "develop": CustomDevelop,
            "install": CustomInstall,
        }
    )
