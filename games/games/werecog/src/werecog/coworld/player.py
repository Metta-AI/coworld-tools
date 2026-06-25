from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import websockets


def choose_action(action_names: list[str], step: int, slot: int) -> str:
    if "noop" in action_names:
        return "noop"
    return action_names[(step + slot) % max(1, len(action_names))]


async def run_reference_player(player_ws_url: str) -> None:
    action_names: list[str] = []
    slot = 0
    async with websockets.connect(player_ws_url, max_size=None) as websocket:
        async for raw_message in websocket:
            message: dict[str, Any] = json.loads(raw_message)
            message_type = message.get("type")
            if message_type == "player_config":
                action_names = list(message.get("action_names", []))
                slot = int(message.get("slot", 0))
            elif message_type == "observation":
                step = int(message.get("step", 0))
                await websocket.send(
                    json.dumps(
                        {
                            "type": "action",
                            "action_name": choose_action(action_names, step, slot),
                            "policy_infos": {"policy_name": "coworld-reference-player"},
                            "request_id": f"step-{step}",
                        }
                    )
                )
            elif message_type == "final":
                return


def main() -> None:
    asyncio.run(run_reference_player(os.environ["COWORLD_PLAYER_WS_URL"]))


if __name__ == "__main__":
    main()
