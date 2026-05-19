"""Coworld websocket runner for Toolsy agents."""

from __future__ import annotations

import json
import multiprocessing
import os

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from toolsy_policy.obs import WorldMap, decode_view_from_agent_state
from toolsy_policy.policy import LLM_REQUEST_TIMEOUT_SECONDS, ToolsyAgentPolicy


class ToolsyCoworldProcessManager:
    def __init__(self, websocket_urls: list[str]):
        self._websocket_urls = list(websocket_urls)
        self._ctx = multiprocessing.get_context("spawn")
        self._processes: list[multiprocessing.Process] = []

    @property
    def websocket_urls(self) -> list[str]:
        return list(self._websocket_urls)

    def start(self) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is required for the toolsy policy")
        if self._processes:
            return
        for agent_id, websocket_url in enumerate(self._websocket_urls):
            process = self._ctx.Process(
                target=run_toolsy_coworld_agent,
                args=(agent_id, websocket_url),
                daemon=True,
                name=f"toolsy-coworld-a{agent_id}",
            )
            process.start()
            self._processes.append(process)

    def shutdown(self) -> None:
        for process in self._processes:
            if process.is_alive():
                process.terminate()
        for process in self._processes:
            process.join(timeout=5.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=5.0)
        self._processes.clear()


def run_toolsy_coworld_agent(agent_id: int, websocket_url: str) -> None:
    policy = ToolsyAgentPolicy(
        policy_env_info=None,
        agent_id=agent_id,
        llm_client=_make_llm_client(),
    )
    world_map = WorldMap()
    last_llm_trigger_id = 0
    with ws_connect(websocket_url, open_timeout=30.0) as websocket:
        for message in websocket:
            if not isinstance(message, str):
                continue
            payload = json.loads(message)
            if payload.get("type") != "agent_state":
                continue
            last_llm_trigger_id = sync_policy_llm_trigger(policy, payload, last_llm_trigger_id)
            sync_policy_goals_from_agent_state(policy, payload)
            view = decode_view_from_agent_state(payload, world_map=world_map)
            action = policy.step_view(view)
            if not send_action_message(websocket, action.name, policy.infos):
                break


def send_action_message(websocket, action_name: str, policy_infos: dict) -> bool:
    try:
        websocket.send(json.dumps({
            "type": "action",
            "action_name": action_name,
            "policy_infos": policy_infos,
        }))
    except (ConnectionClosed, OSError):
        return False
    return True


def sync_policy_goals_from_agent_state(policy: ToolsyAgentPolicy, agent_state: dict) -> None:
    policy_infos = agent_state.get("policy_infos") or {}
    goal_tasks = policy_infos.get("goal_tasks")
    if isinstance(goal_tasks, list):
        if goal_tasks:
            policy.sync_goal_tasks(goal_tasks, source="widget")
        return
    current_goals = policy_infos.get("current_goals")
    if isinstance(current_goals, str) and current_goals.strip():
        policy.add_current_goals(current_goals, source="widget")


def sync_policy_llm_trigger(policy: ToolsyAgentPolicy, agent_state: dict, last_trigger_id: int) -> int:
    try:
        trigger_id = int(agent_state.get("llm_trigger_id") or 0)
    except (TypeError, ValueError):
        return last_trigger_id
    if trigger_id <= last_trigger_id:
        return last_trigger_id
    policy.trigger_llm(source="ui")
    return trigger_id


def _make_llm_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for the toolsy policy")
    import anthropic

    return anthropic.Anthropic(
        api_key=api_key,
        timeout=LLM_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
