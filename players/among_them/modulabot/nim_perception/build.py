"""Build helper for the modulabot Nim perception shared library.

Adapted from ``~/coding/bitworld/among_them/players/modulabot/build_modulabot.py``
but scoped down to perception kernels only and without the ``nimby``
lock-file dependency — we don't pull in any upstream Nim packages (only
the vendored kernel sources under ``among_them/common/perception_kernels/``),
so a plain ``nim c`` invocation suffices.

The kernel sources live in ``among_them/common/perception_kernels/`` so
guided_bot (and any future agent) can import them too without reaching
into modulabot's tree. ``lib.nim`` here is the modulabot-specific FFI
surface (the ``mb_*`` exports the Python loader binds to); it imports
the kernels via Nim's ``--path:`` resolution against
:data:`KERNELS_DIR`.

The caller protocol matches the upstream build helper:

- Called on first import by :mod:`modulabot.policy` via
  :func:`modulabot.nim_perception.ensure_library`.
- Rebuilds the library when the source hash changes. Writes a
  ``.dylib.sources`` sidecar with the SHA256 of the sources tree so the
  next import can short-circuit.
- Respects ``MODULABOT_DISABLE_NATIVE=1`` (the env-var opt-out) by
  raising :class:`NativeBuildDisabled` — the loader treats that as
  "fall back to pure Python" without printing a scary traceback.

The ABI stamp is independent: the FFI surface (symbol signatures) is
versioned by :data:`ABI_VERSION`, while the *source content* is tracked
by the sha256 sidecar. Either changing forces a rebuild.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

#: Bump whenever the FFI surface changes. Keep in sync with
#: ``lib.nim::ModulabotPerceptionAbiVersion`` and
#: ``__init__.py::ABI_VERSION``.
ABI_VERSION = 6

HERE = Path(__file__).resolve().parent
LIB_NIM = HERE / "lib.nim"

#: Shared kernel directory. Both modulabot (here) and guided_bot
#: (via ``among_them/guided_bot/perception/localize.nim``) consume the
#: same ``.nim`` files. Layout (with this file at
#: ``among_them/modulabot/nim_perception/build.py``):
#:   parents[0] = modulabot
#:   parents[1] = among_them   ← the one we want
KERNELS_DIR = HERE.parents[1] / "common" / "perception_kernels"


class NativeBuildDisabled(RuntimeError):
    """Raised when ``MODULABOT_DISABLE_NATIVE`` is set or a build fails.

    The Python loader catches this and falls back to pure-Python kernels;
    callers see ``HAVE_NATIVE = False``.
    """


def library_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "libmodulabot_perception.dylib"
    if system == "Windows":
        return "modulabot_perception.dll"
    return "libmodulabot_perception.so"


def library_path() -> Path:
    return HERE / library_name()


def _sidecar_path(lib_path: Path) -> Path:
    return lib_path.with_suffix(lib_path.suffix + ".sources")


def _hash_sources() -> str:
    """Return a SHA256 of every Nim source file the build consumes.

    Hashes :data:`LIB_NIM` plus every ``.nim`` under the shared kernel
    directory (:data:`KERNELS_DIR`). Sorted by absolute path so the
    hash is platform-stable; hashing content (not mtime) so rebuilds
    only happen on real edits. Path keys are namespaced as ``lib/`` /
    ``kernels/`` so a kernel and a lib file with the same basename
    don't collide.
    """
    h = hashlib.sha256()
    entries: list[tuple[str, Path]] = [("lib/" + LIB_NIM.name, LIB_NIM)]
    if KERNELS_DIR.exists():
        for path in sorted(KERNELS_DIR.rglob("*.nim")):
            entries.append(("kernels/" + path.name, path))
    for key, path in sorted(entries):
        h.update(key.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    # Fold ABI_VERSION in so a surface change also invalidates.
    h.update(f"abi={ABI_VERSION}\n".encode("utf-8"))
    return h.hexdigest()


def _needs_rebuild(lib_path: Path) -> bool:
    if not lib_path.exists():
        return True
    sidecar = _sidecar_path(lib_path)
    if not sidecar.exists():
        return True
    return sidecar.read_text().strip() != _hash_sources()


def _run_nim(lib_path: Path) -> None:
    nim = shutil.which("nim")
    if nim is None:
        raise NativeBuildDisabled(
            "Nim compiler not found on PATH. Install via nimby "
            "(https://github.com/treeform/nimby) or disable the native "
            "path with MODULABOT_DISABLE_NATIVE=1."
        )
    # ``nim c`` writes a ``nimcache/`` next to the working dir; keep it
    # scoped to this package so we don't pollute the modulabot root.
    cache_dir = HERE / "nimcache"
    cache_dir.mkdir(exist_ok=True)
    if not KERNELS_DIR.exists():
        raise NativeBuildDisabled(
            f"Shared perception-kernel directory not found: {KERNELS_DIR}. "
            "Expected at among_them/common/perception_kernels/. "
            "Did the kernels move? Check git history."
        )
    cmd = [
        nim,
        "c",
        "-d:release",
        "--opt:speed",
        "--app:lib",
        "--mm:orc",
        "--threads:off",
        f"--nimcache:{cache_dir}",
        f"--path:{KERNELS_DIR}",
        f"--out:{lib_path}",
        str(LIB_NIM),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise NativeBuildDisabled(
            "nim c failed: "
            + (result.stderr or result.stdout or f"rc={result.returncode}")
        )


def ensure_library(*, force: bool = False) -> Path:
    """Build the library if missing/stale; return its path.

    Raises :class:`NativeBuildDisabled` when
    ``MODULABOT_DISABLE_NATIVE=1`` is set or the build tooling is
    unavailable. Otherwise returns the path to the built library.
    """
    if os.environ.get("MODULABOT_DISABLE_NATIVE"):
        raise NativeBuildDisabled("MODULABOT_DISABLE_NATIVE=1")
    lib_path = library_path()
    if force or _needs_rebuild(lib_path):
        _run_nim(lib_path)
        _sidecar_path(lib_path).write_text(_hash_sources() + "\n")
    return lib_path


if __name__ == "__main__":
    # Known cosmetic: ``python -m modulabot.nim_perception.build``
    # emits a ``RuntimeWarning`` about ``build`` being in ``sys.modules``
    # before runpy executes it as ``__main__``. The warning is runpy's,
    # not ours — it fires because ``modulabot.nim_perception.__init__``
    # eagerly imports this module via :func:`_try_load`. The
    # double-import is harmless (same content, same globals); suppress
    # the warning caller-side with ``python -W ignore::RuntimeWarning``
    # if it bothers you, or invoke this file directly:
    #   python modulabot/nim_perception/build.py --force
    try:
        path = ensure_library(force="--force" in sys.argv)
    except NativeBuildDisabled as exc:
        print(f"native build disabled: {exc}", file=sys.stderr)
        sys.exit(1)
    print(path)
