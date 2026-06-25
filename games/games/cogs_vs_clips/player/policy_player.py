from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Literal

import websockets
from pydantic import BaseModel


class ReferencePlayerConfig(BaseModel):
    type: Literal["player_config"]
    protocol: Literal["coworld.player.v1"]
    slot: int
    connection_id: str
    action_names: list[str]
    policy_env: dict[str, Any]


class ReferencePlayerObservation(BaseModel):
    type: Literal["observation"]
    protocol: Literal["coworld.player.v1"]
    slot: int
    step: int
    observation: list[tuple[int, int, int]]


class ReferencePlayer:
    def __init__(self) -> None:
        self.config: ReferencePlayerConfig | None = None

    def configure(self, raw_message: dict[str, object]) -> None:
        self.config = ReferencePlayerConfig.model_validate(raw_message)

    def action_for_observation(self, raw_message: dict[str, object]) -> dict[str, object]:
        observation_message = ReferencePlayerObservation.model_validate(raw_message)
        assert self.config is not None
        return {
            "type": "action",
            "action_name": self._action_name(observation_message.step),
            "policy_infos": {"policy_name": "coworld-reference-player"},
            "request_id": f"step-{observation_message.step}",
        }

    def _action_name(self, step: int) -> str:
        action_names = self.config.action_names
        if "noop" in action_names:
            return "noop"
        return action_names[(self.config.slot + step) % len(action_names)]


async def run_reference_player(*, player_ws_url: str) -> None:
    player = ReferencePlayer()
    async with websockets.connect(player_ws_url) as websocket:
        async for raw_message in websocket:
            message = json.loads(raw_message)
            if message["type"] == "player_config":
                player.configure(message)
            elif message["type"] == "observation":
                await websocket.send(json.dumps(player.action_for_observation(message)))
            elif message["type"] == "final":
                return


def main() -> None:
    asyncio.run(run_reference_player(player_ws_url=os.environ["COWORLD_PLAYER_WS_URL"]))


if __name__ == "__main__":
    main()
