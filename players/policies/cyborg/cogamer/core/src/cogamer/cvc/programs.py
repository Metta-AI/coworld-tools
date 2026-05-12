"""Flat program table: all CvC programs in one dict, operating on GameState.

Programs read from / write to GameState (from cogamer.cvc.game_state), which
delegates to the engine's A* pathfinding and role logic. The ``all_programs()``
function returns a dict[str, Program] with query, action, and decision programs.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from cogamer.cvc.proglet import Program
except ImportError:
    from dataclasses import dataclass
    from dataclasses import field as _field
    from typing import Callable

    @dataclass  # type: ignore[no-redef]
    class Program:  # type: ignore[no-redef]
        executor: str = "python"
        fn: Callable | None = None
        system: str | Callable | None = None
        tools: list[str] = _field(default_factory=list)
        parser: Callable | None = None
        config: dict[str, Any] = _field(default_factory=dict)


from cogamer.cvc.agent import KnownEntity, manhattan, team_id
from mettagrid.simulator import Action

_ELEMENTS = ("carbon", "oxygen", "germanium", "silicon")

# ---------------------------------------------------------------------------
# Query programs — read from GameState (which delegates to engine)
# ---------------------------------------------------------------------------


def _hp(gs: Any) -> int:
    return gs.hp


def _step_num(gs: Any) -> int:
    return gs.step_index


def _position(gs: Any) -> tuple[int, int]:
    return gs.position


def _inventory(gs: Any) -> dict:
    return dict(gs.mg_state.self_state.inventory)


def _resource_bias(gs: Any) -> str:
    return gs.resource_bias


def _team_resources(gs: Any) -> dict[str, int]:
    if gs.mg_state.team_summary is None:
        return {e: 0 for e in _ELEMENTS}
    return {e: int(gs.mg_state.team_summary.shared_inventory.get(e, 0)) for e in _ELEMENTS}


def _resource_priority(gs: Any) -> list[str]:
    return gs.resource_priority()


def _nearest_hub(gs: Any) -> KnownEntity | None:
    return gs.nearest_hub()


def _nearest_extractor(gs: Any, resource: str) -> KnownEntity | None:
    return gs.nearest_extractor(resource)


def _known_junctions(gs: Any, predicate: Any = None) -> list[KnownEntity]:
    return gs.known_junctions(predicate)


def _safe_distance(gs: Any) -> int:
    hub = gs.nearest_hub()
    if hub is None:
        return 0
    return manhattan(gs.position, hub.position)


def _has_role_gear(gs: Any, role: str) -> bool:
    return gs.has_role_gear(role)


def _team_can_afford_gear(gs: Any, role: str) -> bool:
    return gs.team_can_afford_gear(role)


def _needs_emergency_mining(gs: Any) -> bool:
    return gs.needs_emergency_mining()


def _is_stalled(gs: Any) -> bool:
    return gs.stalled_steps >= 12


def _is_oscillating(gs: Any) -> bool:
    return gs.oscillation_steps >= 4


# ---------------------------------------------------------------------------
# Action programs — delegate to GameState → engine A* pathfinding
# ---------------------------------------------------------------------------


def _action(gs: Any, name: str, vibe: str | None = None) -> Action:
    action_name = name if name in gs.action_names else gs.fallback
    vibe_name = vibe if vibe in gs.vibe_actions else None
    return Action(name=action_name, vibe=vibe_name)


def _move_to(gs: Any, target: Any) -> tuple[Action, str]:
    """Move to a KnownEntity or position tuple using engine A* pathfinding."""
    if hasattr(target, "position"):
        return gs.move_to_known(target, summary="move")
    return gs.move_to_position(target, summary="move")


def _hold(gs: Any) -> tuple[Action, str]:
    return gs.hold()


def _explore(gs: Any, role: str = "miner") -> tuple[Action, str]:
    return gs.explore(role)


def _unstick(gs: Any, role: str = "miner") -> tuple[Action, str]:
    return gs.unstick(role)


# ---------------------------------------------------------------------------
# Decision programs — compose queries and actions via engine delegation
# ---------------------------------------------------------------------------


def _desired_role(gs: Any) -> str:
    # Engine's _desired_role already adjusts for teammate roles via pressure.py.
    # No additional override here to avoid double-counting.
    return gs.desired_role()


def _should_retreat(gs: Any) -> bool:
    if gs.should_retreat():
        return True
    # Extra caution when low HP and far from hub
    if gs.hp < 60:
        hub = gs.nearest_hub()
        if hub is not None and manhattan(gs.position, hub.position) > 25:
            return True
    return False


def _retreat(gs: Any) -> tuple[Action, str]:
    hub = gs.nearest_hub()
    if hub is not None:
        return gs.move_to_known(hub, summary="retreat_to_hub")
    return gs.hold(summary="retreat_hold")


def _mine(gs: Any) -> tuple[Action, str]:
    return gs.miner_action()


def _align(gs: Any) -> tuple[Action, str]:
    return gs.aligner_action()


def _scramble(gs: Any) -> tuple[Action, str]:
    return gs.scrambler_action()


def _step(gs: Any) -> tuple[Action, str]:
    """Main dispatch — delegates to engine._choose_action decision tree."""
    return gs.choose_action(gs.role)


def _summarize(gs: Any) -> dict:
    """Experience snapshot for LLM analysis."""
    hp = gs.hp
    pos = gs.position
    hub = gs.nearest_hub()
    team = team_id(gs.mg_state) if gs.mg_state else ""
    friendly_j = len(gs.known_junctions(lambda e: e.owner == team)) if team else 0
    enemy_j = len(gs.known_junctions(lambda e: e.owner not in {None, "neutral", team})) if team else 0
    neutral_j = len(gs.known_junctions(lambda e: e.owner in {None, "neutral"}))

    # Team role counts for LLM context
    roles_str = ""
    if gs.mg_state and gs.mg_state.team_summary:
        role_counts: dict[str, int] = {}
        for m in gs.mg_state.team_summary.members:
            role_counts[m.role] = role_counts.get(m.role, 0) + 1
        roles_str = ", ".join(f"{k}={v}" for k, v in sorted(role_counts.items()))

    return {
        "step": gs.step_index,
        "agent_id": gs.agent_id,
        "hp": hp,
        "position": pos,
        "role": gs.role,
        "resource_bias": gs.resource_bias,
        "team_resources": _team_resources(gs),
        "inventory": _inventory(gs),
        "junctions": {"friendly": friendly_j, "enemy": enemy_j, "neutral": neutral_j},
        "safe_distance": 0 if hub is None else manhattan(pos, hub.position),
        "stalled": _is_stalled(gs),
        "oscillating": _is_oscillating(gs),
        "has_gear": gs.has_role_gear(gs.role),
        "emergency_mining": gs.needs_emergency_mining(),
        "roles": roles_str,
    }


# ---------------------------------------------------------------------------
# LLM program: analyze
# ---------------------------------------------------------------------------


def _build_analysis_prompt(context: dict) -> str:
    """Build the LLM analysis prompt from extracted game context."""
    j = context["junctions"]
    lines = [
        f"CvC game step {context['step']}/10000. 88x88 map, 8 agents per team.",
        "Score = junctions held over time. MAXIMIZE friendly junctions held.",
        "",
        f"Agent {context['agent_id']}: HP={context['hp']}, Hearts={context['hearts']}, "
        f"Role={context.get('role', 'unknown')}",
        f"Position: {context.get('position', 'unknown')}",
        f"Gear: aligner={context['aligner']} scrambler={context['scrambler']} miner={context['miner']}",
        f"Hub resources: {context['resources']}",
        f"Team roles: {context.get('roles', 'unknown')}",
        f"Junctions: friendly={j['friendly']} enemy={j['enemy']} neutral={j['neutral']}",
        f"Stalled: {context.get('stalled', False)}, Oscillating: {context.get('oscillating', False)}",
        f"Safe distance to hub: {context.get('safe_distance', 'unknown')}",
    ]

    lines.append(
        "\nAnalyze the game state and provide strategic guidance."
        "\nRespond with ONLY a JSON object:"
        '\n{"resource_bias": "carbon"|"oxygen"|"germanium"|"silicon",'
        ' "role": null|"miner"|"aligner"|"scrambler",'
        ' "objective": null|"expand"|"defend"|"economy_bootstrap",'
        ' "analysis": "1-2 sentence strategic assessment"}'
        "\nRules:"
        "\n- resource_bias: element with lowest supply"
        "\n- role: suggest role change ONLY if agent is stuck/stagnating or"
        "\n  team composition is badly unbalanced. null = keep current role."
        "\n- objective: 'expand' if friendly < enemy (need more junctions),"
        "\n  'defend' if we have junctions but enemy is catching up,"
        "\n  'economy_bootstrap' if resources are critically low,"
        "\n  null = normal operation."
    )
    return "\n".join(lines)


def _parse_analysis(text: str) -> dict:
    """Parse the LLM response text into a directive dict."""
    result: dict[str, Any] = {"analysis": text[:100]}
    try:
        directive = json.loads(text)
        if isinstance(directive, dict):
            if directive.get("resource_bias") in _ELEMENTS:
                result["resource_bias"] = directive["resource_bias"]
            if directive.get("role") in {"miner", "aligner", "scrambler"}:
                result["role"] = directive["role"]
            if directive.get("objective") in {"expand", "defend", "economy_bootstrap"}:
                result["objective"] = directive["objective"]
            result["analysis"] = directive.get("analysis", text[:100])
    except (json.JSONDecodeError, ValueError):
        pass
    return result


# ---------------------------------------------------------------------------
# all_programs / seed_programs
# ---------------------------------------------------------------------------


def all_programs() -> dict[str, Program]:
    """Return the flat program table."""
    return {
        # Query programs
        "hp": Program(executor="code", fn=_hp),
        "step_num": Program(executor="code", fn=_step_num),
        "position": Program(executor="code", fn=_position),
        "inventory": Program(executor="code", fn=_inventory),
        "resource_bias": Program(executor="code", fn=_resource_bias),
        "team_resources": Program(executor="code", fn=_team_resources),
        "resource_priority": Program(executor="code", fn=_resource_priority),
        "nearest_hub": Program(executor="code", fn=_nearest_hub),
        "nearest_extractor": Program(executor="code", fn=_nearest_extractor),
        "known_junctions": Program(executor="code", fn=_known_junctions),
        "safe_distance": Program(executor="code", fn=_safe_distance),
        "has_role_gear": Program(executor="code", fn=_has_role_gear),
        "team_can_afford_gear": Program(executor="code", fn=_team_can_afford_gear),
        "needs_emergency_mining": Program(executor="code", fn=_needs_emergency_mining),
        "is_stalled": Program(executor="code", fn=_is_stalled),
        "is_oscillating": Program(executor="code", fn=_is_oscillating),
        # Action programs
        "action": Program(executor="code", fn=_action),
        "move_to": Program(executor="code", fn=_move_to),
        "hold": Program(executor="code", fn=_hold),
        "explore": Program(executor="code", fn=_explore),
        "unstick": Program(executor="code", fn=_unstick),
        # Decision programs
        "desired_role": Program(executor="code", fn=_desired_role),
        "should_retreat": Program(executor="code", fn=_should_retreat),
        "retreat": Program(executor="code", fn=_retreat),
        "mine": Program(executor="code", fn=_mine),
        "align": Program(executor="code", fn=_align),
        "scramble": Program(executor="code", fn=_scramble),
        "step": Program(executor="code", fn=_step),
        "summarize": Program(executor="code", fn=_summarize),
        # LLM program
        "analyze": Program(
            executor="llm",
            system=_build_analysis_prompt,
            parser=_parse_analysis,
            config={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 200,
                "temperature": 0.2,
                "max_turns": 1,
            },
        ),
    }
