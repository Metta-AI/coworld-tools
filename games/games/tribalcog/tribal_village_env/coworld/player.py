from __future__ import annotations

import asyncio
import json
import os
import random
from typing import Any

import websockets


async def main() -> None:
    url = os.environ["COGAMES_ENGINE_WS_URL"]
    rng = random.Random(int(os.environ.get("TRIBALCOG_PLAYER_SEED", "0")))
    mode = os.environ.get("TRIBALCOG_PLAYER_MODE", "random")
    async with websockets.connect(url, max_size=None) as websocket:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            if message["type"] == "final":
                return
            if message["type"] == "observation":
                await websocket.send(json.dumps({"action": choose_action(message, mode, rng)}))


def choose_action(message: dict[str, Any], mode: str, rng: random.Random) -> int:
    if mode == "noop":
        return 0
    if mode == "sprite":
        action = choose_sprite_action(message)
        if action is not None:
            return action
    action_space = int(message.get("action_space", 308))
    return rng.randrange(max(1, action_space))


def choose_sprite_action(message: dict[str, Any]) -> int | None:
    view = message.get("sprite_view")
    if not isinstance(view, dict):
        return None
    cells = view.get("cells")
    center = view.get("center")
    if not isinstance(cells, list) or not isinstance(center, dict):
        return None
    center_x = int(center.get("x", 5))
    center_y = int(center.get("y", 5))
    own_team = message.get("team_id")
    targets: list[tuple[int, int, int]] = []
    for row in cells:
        if not isinstance(row, list):
            continue
        for cell in row:
            if not isinstance(cell, dict) or cell.get("obscured"):
                continue
            thing = cell.get("thing")
            team_id = cell.get("team_id")
            if thing in {"tree", "wheat", "stone", "gold", "bush", "fish", "relic"}:
                priority = 1
            elif thing in {"tumor", "wolf", "bear", "skeleton", "goblin_hive", "goblin_hut", "goblin_totem"}:
                priority = 0
            elif thing == "agent" and team_id is not None and team_id != own_team:
                priority = 0
            else:
                continue
            x = int(cell.get("x", center_x))
            y = int(cell.get("y", center_y))
            distance = max(abs(x - center_x), abs(y - center_y))
            if distance > 0:
                targets.append((priority, distance, direction_argument(x - center_x, y - center_y)))
    if not targets:
        return None
    _, _, argument = min(targets)
    return 1 * 28 + argument


def direction_argument(dx: int, dy: int) -> int:
    sx = 0 if dx == 0 else 1 if dx > 0 else -1
    sy = 0 if dy == 0 else 1 if dy > 0 else -1
    return {
        (0, -1): 0,
        (0, 1): 1,
        (-1, 0): 2,
        (1, 0): 3,
        (-1, -1): 4,
        (1, -1): 5,
        (-1, 1): 6,
        (1, 1): 7,
    }.get((sx, sy), 0)


if __name__ == "__main__":
    asyncio.run(main())
