"""In-process Cogony episode runner.

This is a lightweight local analogue of the Coworld runner contract: it owns the
game simulation, policy startup, browser renderer, and status surface for one
episode.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cogony.coworld_episode import EpisodeArtifacts, artifact_status, build_play_links
from cogony.runner_support import (
    _current_policy_infos,
    _decode_observation_tokens,
    _make_policy,
    _refresh_policy_obs_grids,
    _start_toolsy_coworld_processes,
)


class _Renderer(Protocol):
    def render(self) -> None: ...

    def apply_deferred_user_actions(self) -> None: ...


@dataclass(frozen=True)
class EpisodeRunnerConfig:
    variant: list[str] | None = None
    max_steps: int = 10000
    seed: int = 42
    policy: str = "noop"
    cogs: int = 0
    render: str = "gui"
    tps: float = 5.0
    port: int = 0
    autoplay: bool = False
    autostart: bool = False
    codex: bool = False
    wasm_dir: Path | None = None
    log_dir: Path | str = "logs"
    artifact_workspace: Path | str | None = None
    god_mode: bool = False
    launch_path: str = "/"


def _default_mission_factory():
    from cogony.mission import CogonyMission

    return CogonyMission()


def _default_simulator_factory():
    from mettagrid.simulator.simulator import Simulator

    return Simulator()


def _default_web_renderer_factory(**kwargs):
    from cogony.web.server import WebRenderer

    return WebRenderer(**kwargs)


def _default_renderer_factory(render_mode: str, should_autoplay: bool):
    from mettagrid.renderer.renderer import create_renderer

    return create_renderer(render_mode, autostart=should_autoplay)


def _default_policy_env_info_factory(config):
    from mettagrid.policy.policy_env_interface import PolicyEnvInterface

    return PolicyEnvInterface.from_mg_cfg(config)


def _scores(sim) -> list[float]:
    rewards = getattr(sim, "episode_rewards", None)
    if rewards is None:
        return []
    if hasattr(rewards, "tolist"):
        rewards = rewards.tolist()
    return [float(score) for score in rewards]


class EpisodeRunner:
    def __init__(
        self,
        config: EpisodeRunnerConfig,
        *,
        mission_factory: Callable[[], Any] = _default_mission_factory,
        simulator_factory: Callable[[], Any] = _default_simulator_factory,
        web_renderer_factory: Callable[..., Any] = _default_web_renderer_factory,
        renderer_factory: Callable[[str, bool], Any] = _default_renderer_factory,
        policy_env_info_factory: Callable[[Any], Any] = _default_policy_env_info_factory,
        make_policy: Callable[..., Any] = _make_policy,
        start_coworld_processes: Callable[[Any, int], Any] = _start_toolsy_coworld_processes,
        decode_observation_tokens: Callable[[Any, Any, int], tuple[dict, dict, list[int] | None]] = (
            _decode_observation_tokens
        ),
        on_ready: Callable[[dict], None] | None = None,
    ) -> None:
        self.config = config
        self._mission_factory = mission_factory
        self._simulator_factory = simulator_factory
        self._web_renderer_factory = web_renderer_factory
        self._renderer_factory = renderer_factory
        self._policy_env_info_factory = policy_env_info_factory
        self._make_policy = make_policy
        self._start_coworld_processes = start_coworld_processes
        self._decode_observation_tokens = decode_observation_tokens
        self._on_ready = on_ready
        self._render_mode = self._normalize_render_mode(config.render)
        self._policy_name = config.policy.lower()
        self._policy_mode = "none"
        self._renderer: Any | None = None
        self._simulator: Any | None = None
        self._sim: Any | None = None
        self._artifacts = EpisodeArtifacts.create(config.artifact_workspace)
        self._player_tokens: list[str] = []
        self._coworld_processes: Any | None = None
        self._multi_policy: Any | None = None

    def run(self) -> int:
        mission = self._build_mission()
        env = mission.make_env()
        self._ensure_player_tokens(int(getattr(mission, "num_agents", 0) or 0))
        should_autoplay = self.config.autoplay or self.config.autostart
        renderer, wait_until_step_allowed = self._build_renderer(should_autoplay)
        self._renderer = renderer

        self._simulator = self._simulator_factory()
        self._simulator.add_event_handler(renderer)
        self._sim = self._simulator.new_simulation(env, seed=self.config.seed)
        if len(self._player_tokens) != int(getattr(self._sim, "num_agents", 0) or 0):
            self._ensure_player_tokens(int(getattr(self._sim, "num_agents", 0) or 0))
            if hasattr(renderer, "set_player_tokens"):
                renderer.set_player_tokens(list(self._player_tokens))

        pei = self._policy_env_info_factory(self._sim.config)
        self._start_policies(renderer, pei)
        self._sim._context["policy_infos"] = _current_policy_infos(
            self._sim,
            pei,
            self._policy_name,
            self._decode_observation_tokens,
        )
        if self._on_ready is not None:
            self._on_ready(self.status())

        try:
            renderer.render()
            if self._render_mode == "gui" and not self._sim.is_done():
                self._advance_simulation_step(renderer, pei)
                if not self._sim.is_done():
                    renderer.render()
            while not self._sim.is_done():
                if not wait_until_step_allowed():
                    break
                if self._sim.is_done():
                    break
                self._advance_simulation_step(renderer, pei)
                if self._sim.is_done():
                    break
                renderer.render()
        finally:
            if self._coworld_processes is not None:
                self._coworld_processes.shutdown()

        self._write_episode_artifacts()
        return int(self._sim.current_step)

    def status(self) -> dict:
        renderer = self._renderer
        sim = self._sim
        port = self._renderer_port()
        admin = renderer.admin_state() if renderer is not None and hasattr(renderer, "admin_state") else {}
        endpoints = self._endpoints(port)
        client_urls = self._client_urls(port)
        step = getattr(sim, "current_step", None)
        done = bool(sim.is_done()) if sim is not None and hasattr(sim, "is_done") else False
        agents = int(getattr(sim, "num_agents", 0) or 0)
        components = [
            {
                "name": "server",
                "state": "running" if self._render_mode == "gui" and renderer is not None else self._render_mode,
                "detail": f"http://localhost:{port}" if port is not None else self._render_mode,
            },
            {
                "name": "game",
                "state": "done" if done else ("running" if sim is not None else "ready"),
                "detail": f"step {step if step is not None else 0} / {self.config.max_steps}",
            },
            {
                "name": "policies",
                "state": self._policy_mode,
                "detail": f"{self._policy_name} x{agents}",
            },
        ]
        return {
            "ok": True,
            "runner": "coworld_episode_runner",
            "session_id": getattr(renderer, "session_id", None),
            "artifacts": artifact_status(self._artifacts),
            "components": components,
            "endpoints": endpoints,
            "client_urls": client_urls,
            "admin": admin,
            "episode": {
                "seed": self.config.seed,
                "max_steps": self.config.max_steps,
                "step": step,
                "done": done,
            },
            "policy": {
                "name": self._policy_name,
                "mode": self._policy_mode,
                "agents": agents,
            },
        }

    def _build_mission(self):
        mission = self._mission_factory()
        mission.max_steps = self.config.max_steps
        if self.config.god_mode:
            mission = mission.with_god_mode()
        if self.config.cogs > 0:
            mission = mission.with_cogs(self.config.cogs)
        if self.config.variant:
            mission = mission.with_variants(list(self.config.variant))
        return mission

    def _build_renderer(self, should_autoplay: bool) -> tuple[_Renderer, Callable[[], bool]]:
        if self._render_mode == "gui":
            renderer = self._web_renderer_factory(
                wasm_dir=self.config.wasm_dir,
                port=int(self.config.port),
                tick_rate=self.config.tps,
                autoplay=should_autoplay,
                codex_browser=self.config.codex,
                launch_path=self.config.launch_path,
                log_dir=self._artifacts.logs_dir,
                player_tokens=list(self._player_tokens),
            )
            if hasattr(renderer, "set_status_provider"):
                renderer.set_status_provider(self.status)
            return renderer, renderer.wait_until_step_allowed

        renderer = self._renderer_factory(self._render_mode, should_autoplay)

        def wait_until_step_allowed() -> bool:
            return True

        return renderer, wait_until_step_allowed

    def _start_policies(self, renderer, pei) -> None:
        self._coworld_processes = None
        if self._render_mode == "gui" and self._policy_name == "toolsy":
            self._coworld_processes = self._start_coworld_processes(renderer, self._sim.num_agents)
            if self._coworld_processes is not None:
                self._coworld_processes.start()
                self._policy_mode = "coworld"
                return

        self._multi_policy = self._make_policy(
            self._policy_name,
            pei,
            enable_llm=self._render_mode == "gui",
        )
        self._policy_mode = "in-process" if self._multi_policy is not None else "none"

    def _advance_simulation_step(self, renderer: _Renderer, pei) -> None:
        policy_infos: dict = {}
        if self._multi_policy is not None:
            observations = self._sim.observations()
            for agent_id in range(self._sim.num_agents):
                agent_policy = self._multi_policy.agent_policy(agent_id)
                action = agent_policy.step(observations[agent_id])
                self._sim.agent(agent_id).set_action(action.name)
                infos = dict(agent_policy.infos) if hasattr(agent_policy, "infos") and agent_policy.infos else {}
                infos["__policy_name__"] = self._policy_name
                policy_infos[agent_id] = infos
        else:
            for agent_id in range(self._sim.num_agents):
                self._sim.agent(agent_id).set_action("noop")
                policy_infos[agent_id] = {"__policy_name__": self._policy_name}
        self._sim._context["policy_infos"] = policy_infos
        renderer.apply_deferred_user_actions()
        self._sim.step()
        if self._sim.num_agents > 0 and hasattr(self._sim, "observations"):
            _refresh_policy_obs_grids(
                policy_infos,
                self._sim.observations(),
                pei,
                self._sim.current_step,
                self._policy_name,
                self._decode_observation_tokens,
            )
        self._sim._context["policy_infos"] = policy_infos

    def _renderer_port(self) -> int | None:
        renderer = self._renderer
        if renderer is not None:
            admin = renderer.admin_state() if hasattr(renderer, "admin_state") else {}
            if isinstance(admin, dict) and admin.get("port") is not None:
                return int(admin["port"])
            if getattr(renderer, "_port", None) is not None:
                return int(renderer._port)
        return int(self.config.port) if self._render_mode == "gui" else None

    def _endpoints(self, port: int | None) -> dict:
        if port is None:
            return {}
        return {
            "healthz": f"http://127.0.0.1:{port}/healthz",
            "status": f"http://127.0.0.1:{port}/status",
            "admin": f"http://127.0.0.1:{port}/admin",
            "global": f"ws://127.0.0.1:{port}/global",
            "player": f"ws://127.0.0.1:{port}/player",
            "agent_template": f"ws://127.0.0.1:{port}/agent/{{id}}",
        }

    def _client_urls(self, port: int | None) -> dict:
        if port is None:
            return {}
        links = build_play_links(self._player_tokens, game_port=port)
        return {
            "admin": links.admin,
            "global": links.global_,
            "players": links.players,
            "admin-coworld": links.admin,
            "global-client": f"http://localhost:{port}/global-client",
            "policy-debugger?agent=0": f"http://localhost:{port}/policy-debugger?agent=0",
        }

    def _ensure_player_tokens(self, num_agents: int) -> None:
        if len(self._player_tokens) == num_agents:
            return
        self._player_tokens = [secrets.token_urlsafe(16) for _ in range(max(0, num_agents))]

    def _write_episode_artifacts(self) -> None:
        sim = self._sim
        if sim is None:
            return
        results = {
            "steps": int(getattr(sim, "current_step", 0) or 0),
            "scores": _scores(sim),
            "policy": self._policy_name,
        }
        self._artifacts.results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        self._artifacts.replay_path.write_text(
            json.dumps({"events": [], "results": results}, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_render_mode(render: str) -> str:
        render_mode = render.lower()
        return "gui" if render_mode == "web" else render_mode
