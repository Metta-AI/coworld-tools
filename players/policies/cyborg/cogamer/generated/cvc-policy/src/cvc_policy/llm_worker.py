"""Per-agent LLM coach worker.

Each agent owns one LLMWorker running in a dedicated thread. The worker holds a
single episode-long Anthropic conversation. Each turn includes the current game
status and world model. The LLM's only tool is `patch` to write strategic knobs
back onto the agent's state. The Python tick loop only reads those knobs — it
never waits on the LLM.
"""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING, Any

from cvc_policy.recorder import EventRecorder

if TYPE_CHECKING:
    from cvc_policy.cogamer_policy import CvCAgentState


_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 400
_HISTORY_TRIM_AT = 120
_HISTORY_KEEP_TAIL = 40
_STATUS_COOLDOWN_S = 1.0

_SYSTEM = (
    "You are the strategic coach for a single agent in a cooperative CvC game. "
    "All agents on the map are on the same team — there are no opponents. "
    "Score = junctions held over time.\n"
    "\n"
    "You steer three knobs by calling `patch`:\n"
    "- resource_bias: which element to prioritize mining\n"
    "- role: miner/aligner/scrambler (null = keep current)\n"
    "- objective: expand/defend/economy_bootstrap (null = keep current)\n"
    "\n"
    "Each message includes the current game status and world model. "
    "Analyze the state and call `patch` when strategy should change. "
    "Be concise. Only patch when the situation warrants a change."
)

_TOOLS = [
    {
        "name": "patch",
        "description": (
            "Patch the agent's strategic knobs. All fields are optional; only "
            "provided fields are updated. Call whenever you have a new strategic "
            "decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_bias": {
                    "type": "string",
                    "enum": ["carbon", "oxygen", "germanium", "silicon"],
                },
                "role": {
                    "type": "string",
                    "enum": ["miner", "aligner", "scrambler"],
                },
                "objective": {
                    "type": "string",
                    "enum": ["expand", "defend", "economy_bootstrap"],
                },
                "rationale": {
                    "type": "string",
                    "description": "Brief (1-2 sentence) reasoning for this patch.",
                },
            },
        },
    },
]

WORLD_MODEL_ATTR_SKIP = {
    "global_x",
    "global_y",
    "territory:here",
    "territory:north",
    "territory:south",
    "territory:west",
    "territory:east",
}


def _build_status(recorder: EventRecorder, agent_id: int) -> dict[str, Any]:
    """Compute a dense dashboard from the recorder's event stream."""
    events = recorder.events

    # Find latest inventory event for this agent.
    latest_inv: dict[str, Any] = {}
    for e in reversed(events):
        if e["type"] == "inventory" and e.get("agent") == agent_id:
            latest_inv = e.get("payload", {})
            break

    # Recent action/target changes for this agent (last 5 of each).
    recent_actions: list[str] = []
    recent_targets: list[str] = []
    for e in reversed(events):
        if e.get("agent") != agent_id:
            continue
        if e["type"] == "action" and len(recent_actions) < 5:
            summary = e.get("payload", {}).get("summary", "")
            tick = e.get("step", 0)
            recent_actions.append(f"step {tick}: {summary}")
        elif e["type"] == "target" and len(recent_targets) < 3:
            p = e.get("payload", {})
            tick = e.get("step", 0)
            recent_targets.append(f"step {tick}: {p.get('kind', '?')}@{p.get('pos', '?')}")
        if len(recent_actions) >= 5 and len(recent_targets) >= 3:
            break
    recent_actions.reverse()
    recent_targets.reverse()

    inv = latest_inv.get("inventory", {})
    step = 0
    for e in reversed(events):
        if e.get("agent") == agent_id:
            step = e.get("step", 0)
            break

    gear_types = {"miner", "aligner", "scrambler", "scout", "heart"}
    gear = {k: int(v) for k, v in inv.items() if k in gear_types and int(v) > 0}
    cargo_types = {"carbon", "oxygen", "germanium", "silicon"}
    cargo = {k: int(v) for k, v in inv.items() if k in cargo_types and int(v) > 0}

    return {
        "step": step,
        "hp": int(inv.get("hp", 0)),
        "energy": int(inv.get("energy", 0)),
        "position": latest_inv.get("pos"),
        "role": latest_inv.get("role", "unknown"),
        "gear": gear,
        "cargo": cargo,
        "team_resources": latest_inv.get("team_resources", {}),
        "junctions": latest_inv.get("junctions", {}),
        "resource_bias": latest_inv.get("resource_bias", ""),
        "recent_actions": recent_actions,
        "recent_targets": recent_targets,
    }


class LLMWorker:
    """Owns one thread, one Anthropic session → one agent's knobs."""

    def __init__(
        self,
        client: Any,
        agent_id: int,
        state: CvCAgentState,
        recorder: EventRecorder | None = None,
    ) -> None:
        self._client = client
        self._agent_id = agent_id
        self._state = state
        self._recorder = recorder if recorder is not None else EventRecorder()
        self._shutdown = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"cvc-llm-a{agent_id}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._shutdown.set()
        self._thread.join(timeout=timeout)

    # ── tool implementations ────────────────────────────────────────────

    def _tool_get_status(self, args: dict) -> dict:
        status = _build_status(self._recorder, self._agent_id)
        if self._shutdown.is_set():
            status["shutdown"] = True
        return status

    def _tool_patch(self, args: dict) -> dict:
        applied: dict[str, Any] = {}
        state = self._state
        if args.get("resource_bias"):
            state.resource_bias_from_llm = args["resource_bias"]
            applied["resource_bias"] = args["resource_bias"]
        if args.get("role"):
            state.llm_role_override = args["role"]
            applied["role"] = args["role"]
        if args.get("objective"):
            state.llm_objective = args["objective"]
            applied["objective"] = args["objective"]
        rationale = args.get("rationale", "")
        state.llm_log.append(
            {
                "agent": self._agent_id,
                "type": "patch",
                "applied": applied,
                "rationale": rationale,
            }
        )
        self._recorder.emit(
            type="patch_applied",
            agent=self._agent_id,
            stream="llm",
            payload={"applied": applied, "rationale": rationale},
        )
        return {"ok": True, "applied": applied}

    _SKIP_ATTRS = WORLD_MODEL_ATTR_SKIP

    def _tool_get_world_model(self, args: dict, *, exclude_types: set[str] | None = None) -> dict:
        gs = self._state.game_state
        if gs is None:
            return {"entities": []}
        wm = gs.world_model
        skip = exclude_types or set()
        entities = []
        for entity in wm.entities():
            if entity.entity_type in skip:
                continue
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
                if k not in self._SKIP_ATTRS:
                    e[k] = v
            entities.append(e)
        return {"entities": entities, "count": len(entities)}

    def _dispatch_tool(self, name: str, args: dict) -> dict:
        if name == "patch":
            return self._tool_patch(args)
        return {"error": f"unknown tool: {name}"}

    # ── main loop ───────────────────────────────────────────────────────

    _LLM_EXCLUDE_TYPES = {"wall"}

    def _build_state_message(self) -> str:
        """Build a user message with current status + world model."""
        status = _build_status(self._recorder, self._agent_id)
        wm = self._tool_get_world_model({}, exclude_types=self._LLM_EXCLUDE_TYPES)
        return (
            f"=== Agent {self._agent_id} Status ===\n"
            f"{json.dumps(status, indent=2)}\n\n"
            f"=== World Model ({wm.get('count', 0)} entities) ===\n"
            f"{json.dumps(wm.get('entities', []))}\n\n"
            "Analyze and call patch if strategy should change, or say 'no change'."
        )

    def _initial_messages(self) -> list[dict]:
        return [
            {
                "role": "user",
                "content": self._build_state_message(),
            }
        ]

    def _step_once(self, messages: list[dict] | None = None) -> bool:
        """Run one request/response round-trip. Returns True if the loop
        should exit (shutdown sentinel or end_turn in single-step tests)."""
        if messages is None:
            if not hasattr(self, "_messages"):
                self._messages = self._initial_messages()
            messages = self._messages

        t0 = time.perf_counter()
        response = self._client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            tools=_TOOLS,
            messages=messages,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        self._state.llm_latencies.append(latency_ms)

        # Extract the last user message as the "prompt" for this turn.
        prompt_text = ""
        last_user = messages[-1] if messages and messages[-1].get("role") == "user" else None
        if last_user:
            content = last_user.get("content", "")
            if isinstance(content, str):
                prompt_text = content
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        parts.append(item.get("content", ""))
                    elif isinstance(item, dict):
                        parts.append(json.dumps(item))
                    else:
                        parts.append(str(item))
                prompt_text = "\n".join(parts)

        # Log the assistant response for full conversation tracing.
        response_text = ""
        response_tools = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                response_text += block.text
            elif getattr(block, "type", None) == "tool_use":
                response_tools.append({"tool": block.name, "input": dict(block.input or {})})
        self._recorder.emit(
            type="llm_turn",
            agent=self._agent_id,
            stream="llm",
            payload={
                "prompt": prompt_text,
                "text": response_text,
                "tool_calls": response_tools,
                "stop_reason": response.stop_reason,
                "latency_ms": round(latency_ms, 1),
            },
        )

        messages.append({"role": "assistant", "content": response.content})

        # Always handle tool_use blocks in the response, regardless of
        # stop_reason. A max_tokens cutoff can produce tool_use blocks
        # with stop_reason="max_tokens" — we must still provide results.
        tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        stop = False
        if tool_use_blocks:
            tool_results: list[dict] = []
            for block in tool_use_blocks:
                out = self._dispatch_tool(block.name, dict(block.input or {}))
                if out.get("shutdown"):
                    stop = True
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(out),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
        else:
            messages.append(
                {"role": "user", "content": self._build_state_message()}
            )
            stop = True

        # Cooldown: avoid hammering the API.
        if not stop:
            time.sleep(_STATUS_COOLDOWN_S)

        if len(messages) > _HISTORY_TRIM_AT:
            messages[:] = self._trim_history(messages)
        return stop

    @staticmethod
    def _trim_history(messages: list[dict]) -> list[dict]:
        """Trim history while never starting the kept tail on an assistant
        turn. Assistant tool_use blocks must always be followed by a matching
        user tool_result in the same slice."""
        if len(messages) <= _HISTORY_KEEP_TAIL + 1:
            return list(messages)
        start = len(messages) - _HISTORY_KEEP_TAIL
        while start < len(messages) and messages[start].get("role") != "user":
            start += 1
        return [messages[0]] + list(messages[start:])

    def _run(self) -> None:
        self._messages = self._initial_messages()
        while not self._shutdown.is_set():
            self._step_once(self._messages)
