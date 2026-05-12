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

NIM_AGENTS_DIR = Path(__file__).resolve().parent
NIMBY_LOCK = NIM_AGENTS_DIR / "nimby.lock"

# nimby is not designed for concurrent use. uv builds mettagrid and
# agent-policies in parallel, so we serialize all nimby invocations via an
# OS-level file lock. Released automatically on process exit (even on crash).
_NIMBY_SYNC_LOCK = Path.home() / ".nimby" / ".python_sync.lock"


def _run_nimby_serialized(args: list[str], *, cwd: Path) -> None:
    """Run a nimby command while holding a cross-process file lock."""
    _NIMBY_SYNC_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(_NIMBY_SYNC_LOCK, "w") as lock_fd:
        print("Acquiring nimby sync lock...")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        subprocess.check_call(args, cwd=cwd)


BINDINGS_DIR = NIM_AGENTS_DIR / "bindings" / "generated"


def _find_version_file(name: str) -> str:
    candidate = NIM_AGENTS_DIR / name
    if candidate.exists():
        return candidate.read_text().strip()
    for parent in NIM_AGENTS_DIR.parents:
        candidate = parent / name
        if candidate.exists():
            return candidate.read_text().strip()
        if parent == parent.parent:
            break
    raise FileNotFoundError(f"{name} not found in any ancestor of {NIM_AGENTS_DIR}")


NIM_VERSION = _find_version_file(".nim-version")
NIMBY_VERSION = _find_version_file(".nimby-version")


def _get_nimby_url() -> str | None:
    system = platform.system()
    arch = platform.machine()
    if system == "Linux" and arch == "x86_64":
        return f"https://github.com/treeform/nimby/releases/download/{NIMBY_VERSION}/nimby-Linux-X64"
    elif system == "Linux" and arch == "aarch64":
        return f"https://github.com/treeform/nimby/releases/download/{NIMBY_VERSION}/nimby-Linux-ARM64"
    elif system == "Darwin" and arch == "arm64":
        return f"https://github.com/treeform/nimby/releases/download/{NIMBY_VERSION}/nimby-macOS-ARM64"
    elif system == "Darwin" and arch == "x86_64":
        return f"https://github.com/treeform/nimby/releases/download/{NIMBY_VERSION}/nimby-macOS-X64"
    return None


def _nim_already_installed() -> bool:
    nim = shutil.which("nim")
    if nim is None:
        return False
    result = subprocess.run([nim, "--version"], capture_output=True, text=True)
    return f"Nim Compiler Version {NIM_VERSION}" in result.stdout


def _install_nim() -> None:
    if _nim_already_installed():
        return

    nimby_url = _get_nimby_url()
    if nimby_url is None:
        system = platform.system()
        arch = platform.machine()
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

    os.environ["PATH"] = f"{dst.parent}{os.pathsep}" + os.environ.get("PATH", "")
    os.environ["PATH"] = f"{nim_bin_dir}{os.pathsep}" + os.environ.get("PATH", "")


def _manual_sync_nimby_lock(lock_path: Path) -> None:
    """Fetch Nim deps without `git` (episode-runner images may not include it)."""
    pkgs_dir = Path.home() / ".nimby" / "pkgs"
    pkgs_dir.mkdir(parents=True, exist_ok=True)

    for raw in lock_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # Format: <name> <version> <repo_url> <commit>
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
        # nimby-managed packages generally expose Nim sources under `src/`.
        candidate = pkgs_dir / name / "src"
        if not candidate.exists():
            candidate = pkgs_dir / name
        args.append(f"--path:{candidate}")
    return args


def build_nim() -> None:
    _install_nim()

    if shutil.which("nimby") is not None:
        if shutil.which("git") is None:
            _manual_sync_nimby_lock(NIMBY_LOCK)
        else:
            _run_nimby_serialized(["nimby", "sync", "-g", str(NIMBY_LOCK)], cwd=NIM_AGENTS_DIR)

    BINDINGS_DIR.mkdir(parents=True, exist_ok=True)

    # Pass explicit `--path:` args so we don't rely on `nimby` generating a
    # machine-specific `nim.cfg`.
    cmd = ["nim", "c", *_nim_paths_from_lock(NIMBY_LOCK), "nim_agents.nim"]
    result = subprocess.run(cmd, cwd=NIM_AGENTS_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        raise RuntimeError(f"Failed to build Nim agents: {result.returncode}")
