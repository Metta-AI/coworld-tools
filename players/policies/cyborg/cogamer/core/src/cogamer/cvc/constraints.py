"""CvC constraint coglets for the PCO optimizer.

Constraints validate proposed patches before they are applied. Each receives
a patch dict on the "update" channel and transmits a verdict on "verdict".
"""

from __future__ import annotations

import ast
import re
from typing import Any

from cogamer.pco.constraint import ConstraintCoglet


class SyntaxConstraint(ConstraintCoglet):
    """Validates that any patched Python source code parses correctly.

    Checks for Program objects in the patch dict that have a ``source``
    attribute and verifies each one parses via ``ast.parse``.
    """

    async def check(self, patch: Any) -> dict:
        if not isinstance(patch, dict):
            return {"accepted": True}

        for key, value in patch.items():
            source = getattr(value, "source", None)
            if source is None:
                continue
            try:
                ast.parse(source)
            except SyntaxError as exc:
                return {
                    "accepted": False,
                    "reason": f"syntax error in {key}: {exc}",
                }

        return {"accepted": True}


# Patterns considered dangerous in policy source code.
_DANGEROUS_PATTERNS = [
    re.compile(r"\beval\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\b__import__\s*\("),
    re.compile(r"\bimport\s+os\b"),
    re.compile(r"\bimport\s+subprocess\b"),
    re.compile(r"\bimport\s+sys\b"),
    re.compile(r"\bopen\s*\("),
]


class SafetyConstraint(ConstraintCoglet):
    """Rejects patches containing dangerous Python constructs.

    Scans any ``source`` attribute on Program objects in the patch for
    eval, exec, __import__, import os/subprocess/sys, and open().
    """

    async def check(self, patch: Any) -> dict:
        if not isinstance(patch, dict):
            return {"accepted": True}

        for key, value in patch.items():
            source = getattr(value, "source", None)
            if source is None:
                continue
            for pattern in _DANGEROUS_PATTERNS:
                match = pattern.search(source)
                if match:
                    return {
                        "accepted": False,
                        "reason": f"dangerous construct in {key}: {match.group()}",
                    }

        return {"accepted": True}
