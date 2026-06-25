from __future__ import annotations

MOVE_DELTAS: dict[str, tuple[int, int]] = {
    "north": (-1, 0),
    "south": (1, 0),
    "east": (0, 1),
    "west": (0, -1),
}

DIRECTIONS = ["north", "south", "east", "west"]


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def manhattan_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    return manhattan(a, b)


def is_adjacent(pos1: tuple[int, int], pos2: tuple[int, int]) -> bool:
    dr = abs(pos1[0] - pos2[0])
    dc = abs(pos1[1] - pos2[1])
    return (dr == 1 and dc == 0) or (dr == 0 and dc == 1)


def is_within_observation_shape(
    *,
    row_offset: int,
    col_offset: int,
    row_radius: int,
    col_radius: int,
) -> bool:
    """Mirror mettagrid's circular local observation mask."""
    if row_radius == 0 and col_radius == 0:
        return row_offset == 0 and col_offset == 0
    if row_radius == 0:
        return row_offset == 0 and abs(col_offset) <= col_radius
    if col_radius == 0:
        return col_offset == 0 and abs(row_offset) <= row_radius

    row_sq = row_offset * row_offset
    col_sq = col_offset * col_offset
    row_radius_sq = row_radius * row_radius
    col_radius_sq = col_radius * col_radius

    if row_radius == col_radius:
        dist_sq = row_sq + col_sq
        if dist_sq <= row_radius_sq:
            return True
        return (
            row_radius >= 2
            and dist_sq == row_radius_sq + 1
            and (abs(row_offset) == row_radius or abs(col_offset) == col_radius)
        )

    if row_radius > col_radius:
        return row_sq * col_radius_sq + col_sq * row_radius_sq <= row_radius_sq * col_radius_sq

    return row_sq * col_radius_sq + col_sq * row_radius_sq <= row_radius_sq * col_radius_sq
