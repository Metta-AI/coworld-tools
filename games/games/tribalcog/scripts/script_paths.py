#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
DATA_DIR = REPO_ROOT / "data"


def script_path(name: str) -> Path:
    return SCRIPTS_DIR / name
