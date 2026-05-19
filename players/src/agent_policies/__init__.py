"""Importable agent-framework workspace.

Concrete policies live at the top-level ``players/`` package, not under
``agent_policies``. This package now hosts only reusable frameworks plus
internal eval tooling.
"""

__all__ = ["frameworks", "tools"]
