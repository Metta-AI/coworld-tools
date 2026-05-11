"""Build helper for the guided_bot Nim shared library.

Phase 0: builds from the self-contained Nim sources in this directory.
No bitworld / nimby lookup yet (phase 1 adds the `--path:` switches
for imports from `common/` and `among_them/sim.nim` upstream).

Mirrors `modulabot/build_modulabot.py` in spirit so the phase-1 upgrade
is a contained diff.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

GUIDED_BOT_DIR = Path(__file__).resolve().parent
NIM_VERSION = "2.2.4"
NIMBY_VERSION = "0.1.26"
# Keep in sync with `ffi/lib.nim:GuidedBotAbiVersion`.
GUIDED_BOT_ABI_VERSION = 3


def build_guided_bot() -> Path:
    """Builds the guided_bot shared library and returns its path."""
    _install_nim()
    out_path = GUIDED_BOT_DIR / _library_name()
    cmd = [
        "nim",
        "c",
        "-d:release",
        "--opt:speed",
        "--app:lib",
        "-d:guidedBotLibrary",
        "--threads:on",
        "--mm:orc",
        f"--nimcache:{GUIDED_BOT_DIR / 'nimcache'}",
        f"--out:{out_path}",
        str(GUIDED_BOT_DIR / "guided_bot.nim"),
    ]
    result = subprocess.run(cmd, cwd=GUIDED_BOT_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        raise RuntimeError(
            f"Failed to build guided_bot Nim library: {result.returncode}"
        )
    _abi_stamp_path(out_path).write_text(f"{GUIDED_BOT_ABI_VERSION}\n")
    return out_path


def _nim_already_installed() -> bool:
    nim = shutil.which("nim")
    if nim is None:
        return False
    result = subprocess.run([nim, "--version"], capture_output=True, text=True)
    return result.returncode == 0 and f"Nim Compiler Version {NIM_VERSION}" in result.stdout


def _install_nim() -> None:
    if _nim_already_installed():
        return
    nimby_url = _nimby_url()
    if nimby_url is None:
        system = platform.system()
        arch = platform.machine()
        raise RuntimeError(f"Nim {NIM_VERSION} is unavailable for {system} {arch}.")

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


def _nimby_url() -> str | None:
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


def _library_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "libguidedbot.dylib"
    if system == "Windows":
        return "guidedbot.dll"
    return "libguidedbot.so"


def _abi_stamp_path(lib_path: Path) -> Path:
    return lib_path.with_name(f"{lib_path.name}.abi")


if __name__ == "__main__":
    print(build_guided_bot())
