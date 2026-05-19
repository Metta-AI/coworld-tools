#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple


ORIENTATION_TEMPLATES = [
    ("n", "Back view facing away from the camera."),
    ("s", "Front view facing the camera."),
    ("e", "Right-facing profile view."),
    ("w", "Left-facing profile view."),
    ("ne", "Three-quarter back view facing up-right (northeast), facing away from camera."),
    ("nw", "Three-quarter back view facing up-left (northwest), facing away from camera."),
    ("se", "Three-quarter view facing down-right (southeast), looking left."),
    ("sw", "Three-quarter view facing down-left (southwest), looking right."),
]

EDGE_ORIENTATIONS = [
    (
        "ew",
        "Horizontal cliff edge segment running east-west, spanning fully from left edge to right edge with no diagonal sections. High ground/rim with grass tufts is on the north (top) side; low ground/rock face drop is on the south (bottom) side.",
    ),
    (
        "ew_s",
        "Horizontal cliff edge segment running east-west, spanning fully from left edge to right edge with no diagonal sections. Depict higher ground on the south (bottom) side that descends northward down a cliff face to a lower plain on the north (top) side. Grass tufts only on the high rim.",
    ),
    (
        "ns",
        "Vertical cliff edge segment running north-south, spanning fully from top edge to bottom edge with no diagonal sections. High ground/rim with grass tufts is on the east (right) side; low ground/rock face drop is on the west (left) side.",
    ),
    (
        "ns_w",
        "Vertical cliff edge segment running north-south, spanning fully from top edge to bottom edge with no diagonal sections. High ground/rim with grass tufts is on the west (left) side; low ground/rock face drop is on the east (right) side.",
    ),
]

ORIENTATION_SETS = {
    "unit": ORIENTATION_TEMPLATES,
    "edge": EDGE_ORIENTATIONS,
}

FLIP_ORIENTATIONS = {
    "unit": {
        "e": "w",
        "ne": "nw",
        "se": "sw",
    },
    "edge": {
        "ns_w": "ns",
    },
}


class OrientedRow(NamedTuple):
    filename_template: str
    prompt_template: str
    orientation_set: str
    allowed_dirs: set[str] | None
    reference_dir: str | None


class OrientedOutput(NamedTuple):
    filename: str
    prompt: str
    dir_key: str
    reference_filename: str
    orientation_set: str
    reference_dir: str


def parse_flags(raw: str) -> dict[str, str]:
    flags: dict[str, str] = {}
    if not raw:
        return flags
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            flags[key.strip()] = value.strip()
        else:
            flags[token] = "true"
    return flags


def resolve_orientation_set(name: str) -> list[tuple[str, str]]:
    if name not in ORIENTATION_SETS:
        raise ValueError(f"Unknown orientation set '{name}' (expected one of {sorted(ORIENTATION_SETS)})")
    return ORIENTATION_SETS[name]


def parse_dirs(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    parts = [part.strip() for part in re.split(r"[|;,]", raw) if part.strip()]
    return set(parts)


def expand_oriented_row(
    filename: str,
    prompt: str,
    orientation_set: str,
    allowed_dirs: set[str] | None,
) -> list[tuple[str, str]]:
    if "{dir}" not in filename:
        if "{orientation}" in prompt or "{dir}" in prompt:
            raise ValueError(f"Orientation placeholder requires {{dir}} in filename: {filename}")
        return [(filename, prompt)]
    rows: list[tuple[str, str]] = []
    for dir_key, orientation in resolve_orientation_set(orientation_set):
        if allowed_dirs and dir_key not in allowed_dirs:
            continue
        subs = {
            "dir": dir_key,
            "dir_upper": dir_key.upper(),
            "orientation": orientation,
        }
        try:
            expanded_name = filename.format(**subs)
            expanded_prompt = prompt.format(**subs)
        except KeyError as exc:
            raise ValueError(f"Unknown placeholder in prompt row: {filename}") from exc
        rows.append((expanded_name, expanded_prompt))
    return rows


def parse_prompt_line(raw: str) -> tuple[str, str, dict[str, str]]:
    line = raw.strip()
    if not line or line.startswith("#"):
        return "", "", {}
    parts = line.split("\t")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid prompt line (expected TSV with 2 or 3 columns): {raw}")
    filename = parts[0].strip()
    prompt = parts[1].strip()
    flags = parse_flags(parts[2].strip()) if len(parts) == 3 else {}
    return filename, prompt, flags


def load_prompts(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw in path.read_text().splitlines():
        filename, prompt, flags = parse_prompt_line(raw)
        if not filename:
            continue
        orientation_set = flags.get("orient", "unit")
        allowed_dirs = parse_dirs(flags.get("dirs"))
        rows.extend(expand_oriented_row(filename, prompt, orientation_set, allowed_dirs))
    return rows


def load_oriented_rows(path: Path) -> list[OrientedRow]:
    rows: list[OrientedRow] = []
    for raw in path.read_text().splitlines():
        filename, prompt, flags = parse_prompt_line(raw)
        if not filename:
            continue
        orientation_set = flags.get("orient", "unit")
        allowed_dirs = parse_dirs(flags.get("dirs"))
        reference_dir = flags.get("ref") or flags.get("reference")
        if "{dir}" in filename:
            rows.append(
                OrientedRow(
                    filename_template=filename,
                    prompt_template=prompt,
                    orientation_set=orientation_set,
                    allowed_dirs=allowed_dirs,
                    reference_dir=reference_dir,
                )
            )
    return rows


def iter_oriented_rows(
    rows: Iterable[OrientedRow],
    reference_dir: str,
    only: set[str] | None,
) -> Iterator[OrientedOutput]:
    for row in rows:
        orientation_set = resolve_orientation_set(row.orientation_set)
        orientation_map = {key: text for key, text in orientation_set}
        row_reference_dir = row.reference_dir or reference_dir
        for dir_key, orientation in orientation_set:
            if row.allowed_dirs and dir_key not in row.allowed_dirs:
                continue
            subs = {
                "dir": dir_key,
                "dir_upper": dir_key.upper(),
                "orientation": orientation,
            }
            out_name = row.filename_template.format(**subs)
            if only and out_name not in only and Path(out_name).name not in only:
                continue
            if row_reference_dir not in orientation_map:
                raise ValueError(
                    f"Unknown reference dir '{row_reference_dir}' for orient={row.orientation_set} "
                    f"(expected one of {sorted(orientation_map)})"
                )
            reference_orientation = orientation_map[row_reference_dir]
            prompt = row.prompt_template.format(**subs)
            ref_subs = {
                "dir": row_reference_dir,
                "dir_upper": row_reference_dir.upper(),
                "orientation": reference_orientation,
            }
            ref_name = row.filename_template.format(**ref_subs)
            yield OrientedOutput(
                filename=out_name,
                prompt=prompt,
                dir_key=dir_key,
                reference_filename=ref_name,
                orientation_set=row.orientation_set,
                reference_dir=row_reference_dir,
            )


def iter_rows(
    rows: Iterable[tuple[str, str]],
    only: set[str] | None,
) -> Iterable[tuple[str, str]]:
    for filename, prompt in rows:
        if only and filename not in only and Path(filename).name not in only:
            continue
        yield filename, prompt
