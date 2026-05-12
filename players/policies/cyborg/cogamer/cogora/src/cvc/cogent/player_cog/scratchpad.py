from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

SCRATCHPAD_LINE_RE = re.compile(r"^(?P<prefix>\s*(?:-\s*)?)(?P<key>[A-Za-z0-9_.-]+)\s*(?P<sep>:|=)\s*(?P<value>.*)$")


def parse_scratchpad_value(text: str) -> Any:
    candidate = text.strip()
    if not candidate:
        return ""
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return candidate


def render_scratchpad_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def scratchpad_key_lines(lines: Iterable[str]) -> dict[str, str]:
    keyed_lines: dict[str, str] = {}
    for line in lines:
        match = SCRATCHPAD_LINE_RE.match(line)
        if match is not None:
            keyed_lines[match.group("key")] = line
    return keyed_lines


def scratchpad_line_value(line: str) -> Any:
    match = SCRATCHPAD_LINE_RE.match(line)
    if match is None:
        return ""
    return parse_scratchpad_value(match.group("value"))
