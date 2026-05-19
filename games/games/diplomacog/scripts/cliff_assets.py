#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def maybe_derive_cliff_variants(target: Path, out_dir: Path) -> None:
    # Mettascope terrain generation currently has no cliff variant derivation step.
    _ = target
    _ = out_dir
    return
