"""Temporary asset shim — delete once mettagrid ships multi-data-dir support.

Builds a merged data directory at startup that symlinks mettagrid's bundled
mettascope data and overlays cogame_euchre's custom sprites on top. Since
mettascope rebuilds its atlas from loose files every time it starts, the
overlay sprites appear automatically.

Target removal: when mettagrid's MettascopeRenderer accepts extra asset dirs
natively.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

from mettagrid.renderer.mettascope import MettascopeRenderer, _resolve_nim_root

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def _build_merged_data_dir() -> Path:
    """Create a temp dir that merges mettagrid's data with cogame_euchre sprites."""
    nim_root = _resolve_nim_root()
    mg_data = nim_root / "data" if nim_root else None
    if mg_data is None or not mg_data.is_dir():
        raise FileNotFoundError("Cannot locate mettagrid's mettascope data directory")

    merged = Path(tempfile.mkdtemp(prefix="cogame_euchre_data_"))
    atexit.register(shutil.rmtree, merged, ignore_errors=True)

    # Symlink all top-level items from mettagrid's data dir.
    for item in mg_data.iterdir():
        os.symlink(item, merged / item.name)

    # Overlay our sprites. Where a top-level symlink needs to become a real
    # directory (so we can add files inside it), replace it with a dir whose
    # contents symlink back to the original.
    for asset_file in _ASSETS_DIR.rglob("*.png"):
        rel = asset_file.relative_to(_ASSETS_DIR)
        dest = merged / rel

        # Materialise any ancestor symlinks into real directories.
        for depth in range(1, len(rel.parts)):
            ancestor = merged / Path(*rel.parts[:depth])
            if ancestor.is_symlink():
                target = ancestor.resolve()
                ancestor.unlink()
                ancestor.mkdir()
                for child in target.iterdir():
                    os.symlink(child, ancestor / child.name)

        if dest.is_symlink():
            dest.unlink()
        shutil.copy2(asset_file, dest)

    return merged


class EuchreRenderer(MettascopeRenderer):
    """MettascopeRenderer that includes cogame_euchre sprites in the atlas."""

    def __init__(self, autostart: bool = False):
        super().__init__(autostart=autostart)
        self._data_dir = str(_build_merged_data_dir())
