"""CogamerPolicy: program-table-driven CvC policy.

Dispatches through a flat program table operating on GameState.
Each agent is fully independent — no shared state between agents.

Architecture:
  CvCPolicy (MultiAgentPolicy)
    └─ StatefulAgentPolicy[CvCAgentState]  (one per agent)
         └─ CvCPolicyImpl (StatefulPolicyImpl)
              └─ GameState (observation processing + mutable state)
              └─ Program table (step/heal/retreat/mine/align/scramble/explore)
              └─ LLMWorker thread (per-agent, episode-long Anthropic session,
                 reads game status from recorder events, patches strategic knobs)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cvc_policy.game_state import GameState
from cvc_policy.llm_worker import LLMWorker, WORLD_MODEL_ATTR_SKIP
from cvc_policy.programs import Program, all_programs
from cvc_policy.recorder import EventRecorder
from mettagrid.policy.policy import MultiAgentPolicy, StatefulAgentPolicy, StatefulPolicyImpl
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action
from mettagrid.simulator.interface import AgentObservation

_TRACE_DIR = os.environ.get("CVC_TRACE_DIR", "/tmp/cvc-trace")


@dataclass
class CvCAgentState:
    """All mutable state for one agent."""

    game_state: GameState | None = None
    llm_latencies: list[float] = field(default_factory=list)
    resource_bias_from_llm: str | None = None
    llm_role_override: str | None = None
    llm_objective: str | None = None
    llm_log: list[dict[str, Any]] = field(default_factory=list)
    worker: LLMWorker | None = None


class CvCPolicyImpl(StatefulPolicyImpl[CvCAgentState]):
    """Per-agent decision logic using the program table."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        agent_id: int,
        programs: dict[str, Program],
        llm_client: Any | None = None,
        game_id: str = "",
        recorder: EventRecorder | None = None,
        tps: float = 0.0,
    ) -> None:
        self._policy_env_info = policy_env_info
        self._agent_id = agent_id
        self._programs = programs
        self._llm_client = llm_client
        self._game_id = game_id
        self._recorder = recorder if recorder is not None else EventRecorder()
        self._tps = tps
        self._infos: dict[str, Any] = {}
        self._last_summary: str | None = None
        self._last_target: tuple[str, tuple[int, int]] | None = None
        self._last_tick_time: float = 0.0
        self._applied_llm_resource_bias: str | None = None
        self._applied_llm_role: str | None = None
        self._applied_llm_objective: str | None = None

    def initial_agent_state(self) -> CvCAgentState:
        # Wire cap-discovery events into the recorder via constructor (no
        # monkey-patching of the tracker).
        agent_id = self._agent_id
        recorder = self._recorder

        def _on_cargo_cap_discovery(sig: tuple[str, ...], cap: int) -> None:
            recorder.emit(
                type="cap_discovered",
                agent=agent_id,
                stream="py",
                payload={"kind": "cargo", "gear_sig": list(sig), "cap": cap},
            )

        def _on_heart_cap_discovery(sig: tuple[str, ...], cap: int) -> None:
            recorder.emit(
                type="cap_discovered",
                agent=agent_id,
                stream="py",
                payload={"kind": "heart", "gear_sig": list(sig), "cap": cap},
            )

        gs = GameState(
            self._policy_env_info,
            agent_id=self._agent_id,
            on_cargo_cap_discovery=_on_cargo_cap_discovery,
            on_heart_cap_discovery=_on_heart_cap_discovery,
        )
        state = CvCAgentState(game_state=gs)
        if self._llm_client is not None:
            state.worker = LLMWorker(
                self._llm_client, self._agent_id, state, recorder=self._recorder
            )
            state.worker.start()
        return state

    def _invoke_sync(self, name: str, *args: Any) -> Any:
        prog = self._programs[name]
        if prog.executor == "code" and prog.fn is not None:
            return prog.fn(*args)
        raise ValueError(f"Cannot sync-invoke {name} (executor={prog.executor})")

    def step_with_state(self, obs: AgentObservation, state: CvCAgentState) -> tuple[Action, CvCAgentState]:
        gs = state.game_state
        assert gs is not None

        # Throttle: sleep on agent 0 to hit target tps.
        if self._tps > 0 and self._agent_id == 0:
            now = time.monotonic()
            elapsed = now - self._last_tick_time
            interval = 1.0 / self._tps
            if self._last_tick_time > 0 and elapsed < interval:
                time.sleep(interval - elapsed)
            self._last_tick_time = time.monotonic()

        # Apply any LLM-set knobs before action selection.
        if state.resource_bias_from_llm is not None:
            gs.resource_bias = state.resource_bias_from_llm
        if state.llm_objective is not None and hasattr(gs.engine, "_llm_objective"):
            gs.engine._llm_objective = state.llm_objective

        gs.process_obs(obs)
        self._recorder.set_step(gs.step_index)

        # Detect when LLM knobs are picked up by the tick loop.
        applied: dict[str, Any] = {}
        if state.resource_bias_from_llm != self._applied_llm_resource_bias:
            applied["resource_bias"] = state.resource_bias_from_llm
            self._applied_llm_resource_bias = state.resource_bias_from_llm
        if state.llm_role_override != self._applied_llm_role:
            applied["role"] = state.llm_role_override
            self._applied_llm_role = state.llm_role_override
        if state.llm_objective != self._applied_llm_objective:
            applied["objective"] = state.llm_objective
            self._applied_llm_objective = state.llm_objective
        if applied:
            self._recorder.emit(
                type="llm_applied",
                agent=self._agent_id,
                stream="llm",
                payload=applied,
            )

        prev_role = gs.role
        gs.role = self._invoke_sync("desired_role", gs)
        # LLM role override wins over the heuristic role choice (soft hint).
        if state.llm_role_override is not None:
            gs.role = state.llm_role_override
        if gs.role != prev_role:
            self._recorder.emit(
                type="role_change",
                agent=self._agent_id,
                stream="py",
                payload={"from": prev_role, "to": gs.role},
            )

        action, summary = self._invoke_sync("step", gs)
        gs.finalize_step(summary)
        # Only log action when the summary changes (avoids noisy repeats).
        if summary != self._last_summary:
            payload: dict[str, Any] = {"role": gs.role, "summary": summary}
            if self._last_summary is not None:
                payload["from"] = self._last_summary
            self._recorder.emit(
                type="action",
                agent=self._agent_id,
                stream="py",
                payload=payload,
            )
            self._last_summary = summary
        # Per-tick inventory snapshot for the viewer's inventory panel.
        # Kept as a separate event type so volatile inventory data does
        # not leak into `action` payloads.
        mg_state = getattr(gs, "mg_state", None)
        if mg_state is not None:
            inventory = dict(mg_state.self_state.inventory)
            pos = getattr(gs, "position", None)
            inv_payload: dict[str, Any] = {
                "inventory": inventory,
                "hp": int(inventory.get("hp", 0)),
                "role": gs.role,
            }
            if pos is not None:
                inv_payload["pos"] = list(pos)
            self_state = getattr(mg_state, "self_state", None)
            attrs = getattr(self_state, "attributes", None) if self_state else None
            if attrs is not None:
                team = attrs.get("team", "")
                if team:
                    inv_payload["team"] = str(team)
            team_summary = getattr(mg_state, "team_summary", None)
            shared = getattr(team_summary, "shared_inventory", None) if team_summary else None
            if shared is not None:
                inv_payload["team_resources"] = {
                    k: int(v) for k, v in dict(shared).items()
                }
            known_j = getattr(gs, "known_junctions", None)
            team_attr = inv_payload.get("team", "")
            if callable(known_j) and team_attr:
                friendly_j = len(known_j(lambda e: e.owner == team_attr))
                enemy_j = len(known_j(
                    lambda e: e.owner not in {None, "neutral", team_attr}
                ))
                neutral_j = len(known_j(lambda e: e.owner in {None, "neutral"}))
                inv_payload["junctions"] = {
                    "friendly": friendly_j,
                    "enemy": enemy_j,
                    "neutral": neutral_j,
                }
            self._recorder.emit(
                type="inventory",
                agent=self._agent_id,
                stream="py",
                payload=inv_payload,
            )
        # Only log target when it changes.
        target_kind = getattr(gs.engine, "_current_target_kind", None)
        target_pos = getattr(gs.engine, "_current_target_position", None)
        cur_target = (target_kind, tuple(target_pos)) if target_kind and target_pos is not None else None
        if cur_target != self._last_target:
            if cur_target is not None:
                payload_t: dict[str, Any] = {"kind": cur_target[0], "pos": list(cur_target[1])}
                if self._last_target is not None:
                    payload_t["from_kind"] = self._last_target[0]
                    payload_t["from_pos"] = list(self._last_target[1])
                self._recorder.emit(
                    type="target",
                    agent=self._agent_id,
                    stream="py",
                    payload=payload_t,
                )
            self._last_target = cur_target

        # Policy-info passed to mettascope. Mettascope's policy-info panel
        # displays every non-`__` key and recognises a relative
        # `target: [row, col]` offset to highlight on the map. Keep the
        # surface minimal — the diagnostic viewer reads events from
        # `events.json` directly, so we don't need to stuff them here.
        infos: dict[str, Any] = {"role": gs.role, "summary": summary}
        agent_pos_for_target = getattr(gs, "position", None)
        if target_kind and target_pos is not None and agent_pos_for_target is not None:
            dx = int(target_pos[0]) - int(agent_pos_for_target[0])
            dy = int(target_pos[1]) - int(agent_pos_for_target[1])
            infos["target"] = [dy, dx]
        self._infos = infos

        return action, state


def _truthy(value: Any) -> bool:
    """Handles both real bools and CLI-style string values ('1','true','yes')."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y", "t"}


class CvCPolicy(MultiAgentPolicy):
    """Top-level CvC policy. Spawns LLM workers when Anthropic is configured."""

    short_names = ["cvc", "cvc-policy"]
    minimum_action_timeout_ms = 30_000

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        programs: dict[str, Program] | None = None,
        log: str | None = None,
        log_py: Any = None,
        log_llm: Any = None,
        game_id: str | None = None,
        record_dir: str | None = None,
        tps: float = 0.0,
        **kwargs: Any,
    ):
        if kwargs:
            raise TypeError(
                f"CvCPolicy got unknown kwarg(s): {sorted(kwargs)}. "
                "Known kwargs: device, programs, log, log_py, log_llm, "
                "game_id, record_dir, tps."
            )
        super().__init__(policy_env_info, device=device)
        self._programs = programs or all_programs()
        self._agent_policies: dict[int, StatefulAgentPolicy[CvCAgentState]] = {}
        self._llm_client: Any | None = None
        self._tps = float(tps)
        self._episode_start = time.time()
        self._game_id = game_id if game_id is not None else f"game_{int(time.time())}"
        self._record_dir = record_dir
        streams: set[str] = set()
        if log:
            for part in str(log).split("+"):
                part = part.strip().lower()
                if part == "all":
                    streams.update({"py", "llm"})
                elif part in {"py", "llm"}:
                    streams.add(part)
        if _truthy(log_py):
            streams.add("py")
        if _truthy(log_llm):
            streams.add("llm")
        self._recorder = EventRecorder(
            stderr_streams=streams, record_dir=record_dir
        )
        self._ended = False
        self._init_llm()

        import atexit

        atexit.register(self._on_episode_end)

    def _init_llm(self) -> None:
        api_key = os.environ.get("COGORA_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return
        import logging

        logging.getLogger("httpx").setLevel(logging.WARNING)

        import anthropic

        self._llm_client = anthropic.Anthropic(api_key=api_key)

    @property
    def programs(self) -> dict[str, Program]:
        return self._programs

    def agent_policy(self, agent_id: int) -> StatefulAgentPolicy[CvCAgentState]:
        if agent_id not in self._agent_policies:
            impl = CvCPolicyImpl(
                self._policy_env_info,
                agent_id,
                programs=self._programs,
                llm_client=self._llm_client,
                game_id=self._game_id,
                recorder=self._recorder,
                tps=self._tps,
            )
            self._agent_policies[agent_id] = StatefulAgentPolicy(
                impl,
                self._policy_env_info,
                agent_id=agent_id,
            )
        return self._agent_policies[agent_id]

    def reset(self) -> None:
        if self._agent_policies:
            self._on_episode_end()
        self._episode_start = time.time()
        # Drop cached per-agent wrappers so the next agent_policy() call
        # constructs fresh CvCPolicyImpl + initial_agent_state (new GameState,
        # fresh LLM worker). Reusing the old wrappers across episodes would
        # carry stale GameState and dead LLM workers.
        self._agent_policies = {}
        # Re-arm for the next episode: clear idempotency flag and re-register
        # atexit (we unregistered it at the end of the previous episode).
        self._ended = False
        import atexit

        atexit.register(self._on_episode_end)

    def _stop_workers(self) -> None:
        for wrapper in self._agent_policies.values():
            st: CvCAgentState | None = getattr(wrapper, "_state", None)
            if st is not None and st.worker is not None:
                st.worker.stop(timeout=2.0)
                st.worker = None

    def _on_episode_end(self) -> None:
        if self._ended:
            return
        self._ended = True
        # Only ever fire once per instance per episode: unregister the atexit
        # hook so a later interpreter shutdown doesn't double-write.
        import atexit

        atexit.unregister(self._on_episode_end)
        self._stop_workers()
        self._emit_world_model_summaries()
        self._write_trace()
        if self._record_dir:
            self._recorder.flush_json(Path(self._record_dir) / "events.json")

    def _emit_world_model_summaries(self) -> None:
        """Emit full world model snapshot per agent at episode end."""
        for agent_id, wrapper in self._agent_policies.items():
            st: CvCAgentState | None = getattr(wrapper, "_state", None)
            if st is None or st.game_state is None:
                continue
            wm = st.game_state.world_model
            entities = []
            for entity in wm.entities():
                e: dict[str, Any] = {
                    "type": entity.entity_type,
                    "pos": list(entity.position),
                    "last_seen": entity.last_seen_step,
                }
                if entity.owner:
                    e["owner"] = entity.owner
                if entity.team:
                    e["team"] = entity.team
                for k, v in entity.attributes.items():
                    if k not in WORLD_MODEL_ATTR_SKIP:
                        e[k] = v
                entities.append(e)
            self._recorder.emit(
                type="world_model",
                agent=agent_id,
                stream="py",
                payload={"entities": entities, "count": len(entities)},
            )

    def _write_trace(self) -> None:
        """Write LLM↔Python communication trace to disk for analysis."""
        trace_dir = Path(_TRACE_DIR)
        trace_dir.mkdir(parents=True, exist_ok=True)

        all_llm: list[dict] = []
        agents_data: dict[str, Any] = {}
        for aid, wrapper in self._agent_policies.items():
            st: CvCAgentState | None = getattr(wrapper, "_state", None)
            if st is None:
                continue
            gs = st.game_state
            agents_data[str(aid)] = {
                "steps": gs.step_index if gs else 0,
                "llm_calls": len(st.llm_log),
                "final_resource_bias": st.resource_bias_from_llm,
                "final_role_override": st.llm_role_override,
                "final_objective": st.llm_objective,
            }
            for entry in st.llm_log:
                all_llm.append({"agent": aid, **entry})

        trace = {
            "game_id": self._game_id,
            "duration_s": round(time.time() - self._episode_start, 1),
            "agents": agents_data,
            "llm_trace": all_llm,
        }

        path = trace_dir / f"{self._game_id}.json"
        path.write_text(json.dumps(trace, indent=2, default=str))
