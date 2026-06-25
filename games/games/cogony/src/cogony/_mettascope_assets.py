"""Overlay cogony's bundled mettascope assets onto the installed mettagrid.

``assets/mettascope/`` in this repo is the authoritative asset tree. On every
``import cogony`` we do a cheap manifest-hash check and, if the installed
``site-packages/mettagrid/nim/mettascope/data/`` doesn't already match, copy
every file across. That makes the sync fire automatically after ``uv sync``:
the next Python process that imports cogony (``uv run cogony play``, tests,
REPL, etc.) refreshes the assets.

Add or override a sprite by dropping a file at the matching path under
``assets/mettascope/`` — e.g. ``assets/mettascope/objects/red:hub.png``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = _REPO_ROOT / "assets" / "mettascope"
SENTINEL = ".cogony-assets-version"


def _installed_data_dir() -> Path | None:
    try:
        import mettagrid  # noqa: PLC0415
    except ImportError:
        return None
    mg_root = Path(mettagrid.__file__).parent
    # Editable install: mettagrid is at .mettagrid/python/src/mettagrid/,
    # Nim data lives at .mettagrid/nim/mettascope/data/.
    nim_source = mg_root.parent.parent.parent / "nim" / "mettascope" / "data"
    if nim_source.is_dir():
        return nim_source
    # Packaged install: data is at site-packages/mettagrid/nim/mettascope/data/.
    return mg_root / "nim" / "mettascope" / "data"


def _manifest_hash(src: Path) -> str:
    """Cheap summary of the source tree: hash of (relpath, mtime_ns, size)."""
    h = hashlib.sha1()
    for p in sorted(src.rglob("*")):
        if p.is_file():
            st = p.stat()
            h.update(str(p.relative_to(src)).encode())
            h.update(str(st.st_mtime_ns).encode())
            h.update(str(st.st_size).encode())
    return h.hexdigest()


def overlay(force: bool = False) -> bool:
    """Return True if an overlay happened, False if already in sync or unavailable."""
    if not SRC.exists():
        return False
    dst = _installed_data_dir()
    if dst is None:
        return False
    want = _manifest_hash(SRC)
    sentinel = dst / SENTINEL
    if not force and sentinel.exists():
        try:
            if sentinel.read_text().strip() == want:
                return False
        except OSError:
            pass
    dst.mkdir(parents=True, exist_ok=True)
    for p in SRC.rglob("*"):
        rel = p.relative_to(SRC)
        out = dst / rel
        if p.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
    sentinel.write_text(want)
    return True


def auto_overlay() -> None:
    """Called from ``cogony.__init__`` on package import. Silent unless it
    actually overlays, so it only makes noise after ``uv sync``."""
    if os.environ.get("COGONY_SKIP_ASSET_OVERLAY"):
        return
    try:
        if overlay():
            print("[cogony] synced assets/mettascope/ → installed mettagrid")
    except Exception as e:  # noqa: BLE001
        # Overlay is best-effort; don't block imports if it fails.
        print(f"[cogony] asset overlay skipped: {e}")
