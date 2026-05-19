"""Registry of scripted policy URIs derived from policy short_names."""

from __future__ import annotations

import ast
import functools
from pathlib import Path
from typing import Iterable

_POLICY_ROOT = Path(__file__).resolve().parent
# Directories under players/cogsguard/ that are NOT policy code (helpers,
# fixtures, anything that should not be scanned for short_names).
_SCAN_EXCLUDES = {"_shared", "__pycache__"}


def _iter_policy_files() -> Iterable[Path]:
    for child in _POLICY_ROOT.iterdir():
        if not child.is_dir() or child.name in _SCAN_EXCLUDES:
            continue
        for path in child.rglob("*.py"):
            if path.name.startswith("__"):
                continue
            yield path


def _extract_short_names_from_class(class_def: ast.ClassDef) -> list[str]:
    for stmt in class_def.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "short_names":
                    return list(ast.literal_eval(stmt.value))
        if isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id == "short_names" and stmt.value is not None:
                return list(ast.literal_eval(stmt.value))
    return []


@functools.cache
def list_scripted_agent_names() -> tuple[str, ...]:
    names: set[str] = set()
    for path in _iter_policy_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                names.update(_extract_short_names_from_class(node))
    return tuple(sorted(names))


SCRIPTED_AGENT_URIS: dict[str, str] = {name: f"metta://policy/{name}" for name in list_scripted_agent_names()}


def resolve_scripted_agent_uri(name: str) -> str:
    if name in SCRIPTED_AGENT_URIS:
        return SCRIPTED_AGENT_URIS[name]
    available = ", ".join(sorted(SCRIPTED_AGENT_URIS))
    raise ValueError(f"Unknown scripted agent '{name}'. Available: {available}")
