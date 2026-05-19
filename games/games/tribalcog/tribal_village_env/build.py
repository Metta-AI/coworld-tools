from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

DEFAULT_NIM_VERSION = os.environ.get("TRIBAL_VILLAGE_NIM_VERSION", "2.2.6")
DEFAULT_NIMBY_VERSION = os.environ.get("TRIBAL_VILLAGE_NIMBY_VERSION", "0.1.11")
_TARGET_LIBRARY_NAME = {
    "Darwin": "libtribal_village.dylib",
    "Windows": "libtribal_village.dll",
}.get(platform.system(), "libtribal_village.so")
_TARGET_BINARY_NAME = "tribal_village.exe" if platform.system() == "Windows" else "tribal_village"
_PACKAGED_RUNTIME_DIR_NAME = "runtime"


def _collect_source_files(project_root: Path) -> list[Path]:
    src_dir = project_root / "src"
    nim_sources = list(src_dir.rglob("*.nim")) if src_dir.exists() else []
    return nim_sources + [
        project_root / "tribal_village.nim",
        project_root / "tribal_village.nimble",
        project_root / "nim.cfg",
        project_root / "nimby.lock",
    ]


def get_runtime_project_root(package_dir: Path | None = None) -> Path:
    package_dir = package_dir or Path(__file__).resolve().parent
    packaged_runtime_root = package_dir / _PACKAGED_RUNTIME_DIR_NAME
    if (packaged_runtime_root / "tribal_village.nim").exists() and (
        packaged_runtime_root / "src"
    ).is_dir():
        return packaged_runtime_root
    return package_dir.parent


def _run_build(project_root: Path, cmd: list[str], artifact_name: str) -> None:
    _ensure_nim_toolchain()
    _install_nim_deps(project_root)
    result = subprocess.run(cmd, cwd=project_root, capture_output=True, text=True)
    if result.returncode != 0:
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"Failed to build {artifact_name} (exit {result.returncode}). stdout: {stdout} stderr: {stderr}"
        )


def _build_library(project_root: Path) -> Path:
    target_ext = Path(_TARGET_LIBRARY_NAME).suffix
    _run_build(
        project_root,
        [
            "nim",
            "c",
            "--app:lib",
            "--mm:arc",
            "--opt:speed",
            "-d:danger",
            f"--out:libtribal_village{target_ext}",
            "src/ffi.nim",
        ],
        "Nim library",
    )

    for ext in (".dylib", ".dll", ".so"):
        candidate = project_root / f"libtribal_village{ext}"
        if candidate.exists():
            return candidate

    raise RuntimeError(
        "Build completed but libtribal_village.{so,dylib,dll} not found."
    )


def _build_binary(project_root: Path) -> Path:
    _run_build(
        project_root,
        [
            "nim",
            "c",
            "-d:release",
            "--path:src",
            f"--out:{_TARGET_BINARY_NAME}",
            "tribal_village.nim",
        ],
        "Tribal Village binary",
    )

    binary_path = project_root / _TARGET_BINARY_NAME
    if binary_path.exists():
        return binary_path

    raise RuntimeError(f"Build completed but {_TARGET_BINARY_NAME} was not found.")


def _needs_rebuild(target_path: Path, source_files: Iterable[Path]) -> bool:
    latest_source_mtime = max(
        (path.stat().st_mtime for path in source_files if path.exists()),
        default=None,
    )
    target_mtime: float | None = (
        target_path.stat().st_mtime if target_path.exists() else None
    )
    return target_mtime is None or (
        latest_source_mtime is not None and target_mtime < latest_source_mtime
    )


def _ensure_current(
    target_path: Path,
    project_root: Path,
    build_fn: Callable[[Path], Path],
    build_message: str,
    *,
    verbose: bool,
) -> Path:
    if not _needs_rebuild(target_path, _collect_source_files(project_root)):
        return target_path

    if verbose:
        print(build_message)

    built_path = build_fn(project_root)
    if built_path != target_path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built_path, target_path)
        if verbose:
            print(f"Copied {built_path} to {target_path}")

    return target_path


def ensure_nim_library_current(verbose: bool = True) -> Path:
    """Rebuild libtribal_village if missing or stale."""
    package_dir = Path(__file__).resolve().parent
    project_root = get_runtime_project_root(package_dir)
    return _ensure_current(
        package_dir / _TARGET_LIBRARY_NAME,
        project_root,
        _build_library,
        "Building Tribal Village Nim library to keep bindings current...",
        verbose=verbose,
    )


def ensure_nim_binary_current(verbose: bool = True) -> Path:
    """Rebuild the GUI binary if missing or stale."""
    project_root = get_runtime_project_root()
    return _ensure_current(
        project_root / _TARGET_BINARY_NAME,
        project_root,
        _build_binary,
        "Building Tribal Village GUI binary to keep the launcher current...",
        verbose=verbose,
    )


def _ensure_nim_toolchain() -> None:
    """Ensure nimby is available and installs the requested Nim version."""

    nimby_path = shutil.which("nimby")

    system = platform.system()
    arch = platform.machine().lower()
    if nimby_path is None:
        if system == "Linux":
            url = f"https://github.com/treeform/nimby/releases/download/{DEFAULT_NIMBY_VERSION}/nimby-Linux-X64"
        elif system == "Darwin":
            suffix = "ARM64" if "arm" in arch else "X64"
            url = f"https://github.com/treeform/nimby/releases/download/{DEFAULT_NIMBY_VERSION}/nimby-macOS-{suffix}"
        else:
            raise RuntimeError(f"Unsupported OS for nimby bootstrap: {system}")

        dst = Path.home() / ".nimby" / "nim" / "bin" / "nimby"
        with tempfile.TemporaryDirectory() as tmp:
            nimby_dl = Path(tmp) / "nimby"
            urllib.request.urlretrieve(url, nimby_dl)
            nimby_dl.chmod(nimby_dl.stat().st_mode | stat.S_IEXEC)
            subprocess.check_call([str(nimby_dl), "use", DEFAULT_NIM_VERSION])

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(nimby_dl, dst)

        nimby_path = str(dst)

    nim_bin_dir = Path.home() / ".nimby" / "nim" / "bin"
    os.environ["PATH"] = f"{nim_bin_dir}{os.pathsep}" + os.environ.get("PATH", "")

    if shutil.which("nim") is None:
        subprocess.check_call([nimby_path, "use", DEFAULT_NIM_VERSION])

    if shutil.which("nim") is None:
        raise RuntimeError("Failed to provision nim via nimby.")


def _install_nim_deps(project_root: Path) -> None:
    """Install Nim deps via nimby lockfile."""

    nimby = shutil.which("nimby")
    if nimby is None:
        raise RuntimeError("nimby not found after setup.")

    lockfile = project_root / "nimby.lock"
    if not lockfile.exists():
        raise RuntimeError(f"nimby.lock missing at {lockfile}")

    nim_cfg = project_root / "nim.cfg"
    if nim_cfg.exists():
        nim_cfg.unlink()

    result = subprocess.run(
        [nimby, "sync", "-g", str(lockfile)],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        raise RuntimeError(
            f"nimby sync failed (exit {result.returncode}). stdout: {stdout} stderr: {stderr}"
        )
