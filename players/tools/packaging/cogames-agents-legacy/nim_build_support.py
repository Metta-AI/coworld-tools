from __future__ import annotations

import fcntl
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent
NIM_AGENTS_DIR = _PKG_ROOT / "src" / "cogames_agents" / "policy" / "nim_agents"
NIMBY_LOCK = NIM_AGENTS_DIR / "nimby.lock"
BINDINGS_DIR = NIM_AGENTS_DIR / "bindings" / "generated"

# nimby is not designed for concurrent use. uv builds mettagrid and
# cogames-agents in parallel, so we serialize all nimby invocations via an
# OS-level file lock. Released automatically on process exit (even on crash).
_NIMBY_SYNC_LOCK = Path.home() / ".nimby" / ".python_sync.lock"


def _run_nimby_serialized(args: list[str], *, cwd: Path) -> None:
    """Run a nimby command while holding a cross-process file lock."""
    _NIMBY_SYNC_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(_NIMBY_SYNC_LOCK, "w") as lock_fd:
        print("Acquiring nimby sync lock...")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        subprocess.check_call(args, cwd=cwd)


def _manual_sync_nimby_lock(lock_path: Path) -> None:
    """Fetch Nim deps without `git` (episode-runner images may not include it)."""
    pkgs_dir = Path.home() / ".nimby" / "pkgs"
    pkgs_dir.mkdir(parents=True, exist_ok=True)

    for raw in lock_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 4:
            raise RuntimeError(f"Unexpected nimby.lock line: {raw!r}")
        name, url, commit = parts[0], parts[2], parts[3]

        if not url.startswith("https://github.com/"):
            raise RuntimeError(f"Unsupported nimby.lock URL without git: {url}")
        owner_repo = url.removeprefix("https://github.com/").strip("/")
        if owner_repo.count("/") != 1:
            raise RuntimeError(f"Unsupported GitHub URL: {url}")
        owner, repo = owner_repo.split("/", 1)

        dest = pkgs_dir / name
        marker = dest / ".nimby_commit"
        if marker.is_file() and marker.read_text().strip() == commit:
            continue
        if dest.exists():
            shutil.rmtree(dest)

        zip_url = f"https://codeload.github.com/{owner}/{repo}/zip/{commit}"
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / f"{name}.zip"
            urllib.request.urlretrieve(zip_url, zip_path)  # noqa: S310
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            extracted_dirs = [p for p in Path(tmp).iterdir() if p.is_dir()]
            if len(extracted_dirs) != 1:
                raise RuntimeError(f"Unexpected zip layout for {zip_url} (dirs={extracted_dirs})")
            shutil.move(str(extracted_dirs[0]), dest)
        marker.write_text(commit)


def _nim_paths_from_lock(lock_path: Path) -> list[str]:
    pkgs_dir = Path.home() / ".nimby" / "pkgs"
    args: list[str] = []
    for raw in lock_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 1:
            continue
        name = parts[0]
        candidate = pkgs_dir / name / "src"
        if not candidate.exists():
            candidate = pkgs_dir / name
        args.append(f"--path:{candidate}")
    return args


def _read_dotfile_version(name: str) -> str:
    # These version files historically lived at the package root, but are now
    # checked in alongside the Nim sources. Look in both places (and walk up
    # from the Nim dir) to be robust across sdists/editable installs.
    direct_candidates = [
        NIM_AGENTS_DIR / name,
        _PKG_ROOT / name,
    ]
    for candidate in direct_candidates:
        if candidate.exists():
            return candidate.read_text().strip()

    for parent in NIM_AGENTS_DIR.parents:
        candidate = parent / name
        if candidate.exists():
            return candidate.read_text().strip()
        if parent == parent.parent:
            break

    raise FileNotFoundError(f"{name} not found in {NIM_AGENTS_DIR} or any of its ancestors")


NIM_VERSION = _read_dotfile_version(".nim-version")
NIMBY_VERSION = _read_dotfile_version(".nimby-version")


def _get_nimby_url() -> str | None:
    """Get the nimby download URL for the current platform, or None if not supported."""
    system = platform.system()
    arch = platform.machine()

    if system == "Linux" and arch == "x86_64":
        return f"https://github.com/treeform/nimby/releases/download/{NIMBY_VERSION}/nimby-Linux-X64"
    if system == "Linux" and arch == "aarch64":
        return f"https://github.com/treeform/nimby/releases/download/{NIMBY_VERSION}/nimby-Linux-ARM64"
    if system == "Darwin" and arch == "arm64":
        return f"https://github.com/treeform/nimby/releases/download/{NIMBY_VERSION}/nimby-macOS-ARM64"
    if system == "Darwin" and arch == "x86_64":
        return f"https://github.com/treeform/nimby/releases/download/{NIMBY_VERSION}/nimby-macOS-X64"
    return None


def _nim_already_installed() -> bool:
    nim = shutil.which("nim")
    if nim is None:
        return False
    result = subprocess.run([nim, "--version"], capture_output=True, text=True, check=False)
    return f"Nim Compiler Version {NIM_VERSION}" in result.stdout


def _lib_name(module: str) -> str:
    if sys.platform == "win32":
        return f"{module}.dll"
    if sys.platform == "darwin":
        return f"lib{module}.dylib"
    return f"lib{module}.so"


def _nim_artifacts_up_to_date(nim_dir: Path, module: str) -> bool:
    """Check whether Nim outputs are still current."""
    force_rebuild = os.environ.get("COGAMES_AGENTS_FORCE_NIM_BUILD", "").lower() in {"1", "true", "yes"}
    if force_rebuild:
        return False

    generated_dir = nim_dir / "bindings" / "generated"
    if not generated_dir.exists():
        return False

    output_paths = {
        generated_dir / f"{module}.py",
        generated_dir / _lib_name(module),
    }
    if not all(path.exists() for path in output_paths):
        return False

    source_files = [path for pattern in ("*.nim", "*.nims") for path in nim_dir.rglob(pattern) if path.is_file()]
    source_files.append(nim_dir / "nimby.lock")
    source_files = [path for path in source_files if path.exists()]
    if not source_files:
        return False

    latest_source_mtime = max(path.stat().st_mtime for path in source_files)
    oldest_output_mtime = min(path.stat().st_mtime for path in output_paths)

    return oldest_output_mtime >= latest_source_mtime


def build_nim_agents() -> None:
    """Build Nim agents and generate Python bindings in-place.

    Outputs are written to:
      src/cogames_agents/policy/nim_agents/bindings/generated/
    """
    if _nim_artifacts_up_to_date(NIM_AGENTS_DIR, "nim_agents"):
        return

    system = platform.system()
    arch = platform.machine()

    if not _nim_already_installed():
        nimby_url = _get_nimby_url()
        if nimby_url is None:
            raise RuntimeError(
                f"Nim {NIM_VERSION} is not installed and nimby download is not available for {system} {arch}. "
                "Please install Nim manually (https://nim-lang.org/install.html) or build nimby from source."
            )

        nim_bin_dir = Path.home() / ".nimby" / "nim" / "bin"
        dst = nim_bin_dir / "nimby"
        with tempfile.TemporaryDirectory() as tmp:
            nimby = Path(tmp) / "nimby"
            urllib.request.urlretrieve(nimby_url, nimby)
            nimby.chmod(nimby.stat().st_mode | stat.S_IEXEC)
            subprocess.check_call([str(nimby), "use", NIM_VERSION])

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(nimby, dst)

        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{nim_bin_dir}{os.pathsep}{original_path}"

    # Sync Nim dependencies using nimby
    if shutil.which("nimby") is not None:
        if shutil.which("git") is None:
            _manual_sync_nimby_lock(NIMBY_LOCK)
        else:
            _run_nimby_serialized(["nimby", "sync", "-g", str(NIMBY_LOCK)], cwd=NIM_AGENTS_DIR)

    BINDINGS_DIR.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "nim",
            "c",
            *_nim_paths_from_lock(NIMBY_LOCK),
            "nim_agents.nim",
        ],
        cwd=NIM_AGENTS_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        raise RuntimeError(f"Failed to build Nim agents: {result.returncode}")
