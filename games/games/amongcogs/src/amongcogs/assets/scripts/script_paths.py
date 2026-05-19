#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ASSETS_ROOT = SCRIPTS_DIR.parent
PROMPTS_DIR = ASSETS_ROOT / "prompts"
REPO_ROOT = ASSETS_ROOT.parents[3]
METTASCOPE_DATA_DIR = REPO_ROOT / "packages" / "mettagrid" / "nim" / "mettascope" / "data"
METTASCOPE_AMONGUS_DATA_DIR = METTASCOPE_DATA_DIR / "amongus"


def script_path(name: str) -> Path:
    return SCRIPTS_DIR / name
