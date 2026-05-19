"""Browser client projection and renderer for Cogisis."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from html import escape
from typing import Any

from cogisis.engine import PLAYER_TURN_ACTIONS, Character, CharacterStatus, CogisisSimulator, Phase, Room, World

SHIP_LAYOUT_WIDTH = 1145
SHIP_LAYOUT_HEIGHT = 760
ROOM_BOX_WIDTH = 100
ROOM_BOX_HEIGHT = 60

ACTION_CARD_TYPES_BY_VERB: dict[str, tuple[str, ...]] = {
    "move": ("move", "sprint"),
    "cautious_move": ("move", "sprint"),
    "search": ("search",),
    "rest": ("rest",),
    "shoot": ("attack",),
    "melee": ("attack",),
    "repair": ("repair", "jury_rig"),
    "check_engine": ("repair", "jury_rig"),
    "send_signal": ("plan", "improvise"),
    "set_destination": ("plan", "improvise"),
    "discover_weakness": ("plan", "improvise"),
    "destroy_egg": ("attack", "improvise"),
    "hibernate": ("plan", "improvise"),
    "escape": ("sprint", "improvise"),
    "use_room": ("plan", "improvise"),
    "start_self_destruct": ("plan", "jury_rig"),
    "craft": ("improvise", "jury_rig"),
    "take_object": ("plan", "improvise"),
    "drop_object": ("plan", "improvise"),
}

ROOM_LAYOUT: dict[str, dict[str, int]] = {
    "cockpit": {"x": 80, "y": 345},
    "comms": {"x": 250, "y": 155},
    "escape_b": {"x": 345, "y": 44},
    "storage": {"x": 510, "y": 610},
    "escape_a": {"x": 405, "y": 708},
    "atrium": {"x": 410, "y": 400},
    "laboratory": {"x": 650, "y": 618},
    "nest": {"x": 655, "y": 145},
    "hibernatorium": {"x": 620, "y": 350},
    "surgery": {"x": 850, "y": 600},
    "armory": {"x": 770, "y": 315},
    "engine_3": {"x": 1060, "y": 120},
    "engine_2": {"x": 1070, "y": 370},
    "engine_1": {"x": 1060, "y": 590},
}


def build_client_frames(sim: CogisisSimulator, policy_name: str, *, seed: int = 0) -> list[dict[str, Any]]:
    """Run a policy episode and return frames for the browser client."""

    from cogisis.policies import make_policy

    policy = make_policy(policy_name, seed=seed)
    frames = [client_frame(sim, events=[])]
    while not sim.done:
        result = sim.step_with_policy(policy)
        frames.append(client_frame(sim, events=result.events))
    return frames


def client_frame(
    sim: CogisisSimulator,
    *,
    events: Iterable[dict[str, Any]] = (),
    turn_token: dict[str, Any] | None = None,
    player_connections: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a privacy-aware frame for the global browser client."""

    world = sim.world
    turn_token = turn_token or _turn_token(world)
    return {
        "step": world.current_step,
        "phase": world.phase.value,
        "done": sim.done,
        "turn_token": turn_token,
        "layout": {
            "width": SHIP_LAYOUT_WIDTH,
            "height": SHIP_LAYOUT_HEIGHT,
            "room_width": ROOM_BOX_WIDTH,
            "room_height": ROOM_BOX_HEIGHT,
            "rooms": ROOM_LAYOUT,
            "edges": _ship_edges(world),
        },
        "global": _global_visible_state(world),
        "player_connections": _player_connection_state(world, player_connections),
        "players": [_player_state(sim, character_id, turn_token) for character_id in sorted(world.characters)],
        "events": list(events),
        "stats": _client_stats(sim) if sim.done else None,
    }


def render_client_html(
    frames: list[dict[str, Any]],
    *,
    title: str = "Cogisis global client",
    live_endpoint: str | None = None,
    selected_agent_id: int | None = None,
    player_auth: dict[str, Any] | None = None,
    player_urls: list[str] | None = None,
) -> str:
    """Render a self-contained HTML client for a sequence of frames."""

    data = json.dumps(
        {
            "frames": frames,
            "live_endpoint": live_endpoint,
            "selected_agent_id": selected_agent_id,
            "player_auth": player_auth,
            "player_urls": player_urls or [],
        },
        sort_keys=True,
    ).replace("</", "<\\/")
    god_mode_button = ""
    god_mode_button_lookup = "null"
    if selected_agent_id is None:
        god_mode_button = (
            '<button id="godModeButton" class="god-mode-button" type="button" '
            'aria-pressed="false">God Mode</button>'
        )
        god_mode_button_lookup = 'document.getElementById("godModeButton")'
    return (
        _CLIENT_HTML.replace("__TITLE__", escape(title))
        .replace("__CLIENT_DATA__", data)
        .replace("__GOD_MODE_BUTTON__", god_mode_button)
        .replace("__GOD_MODE_BUTTON_LOOKUP__", god_mode_button_lookup)
    )


def _turn_token(world: World) -> dict[str, Any]:
    active_ids = [
        character_id
        for character_id, character in sorted(world.characters.items())
        if character.status is CharacterStatus.ACTIVE
    ]
    if world.phase is Phase.FINISHED:
        return {
            "phase": world.phase.value,
            "holder": None,
            "queue": [],
            "label": "Finished",
            "actions_per_turn": PLAYER_TURN_ACTIONS,
            "actions_remaining": 0,
        }
    if world.phase is Phase.EVENT:
        return {
            "phase": world.phase.value,
            "holder": "ship",
            "queue": ["ship"],
            "label": "Ship event phase",
            "actions_per_turn": PLAYER_TURN_ACTIONS,
            "actions_remaining": 0,
        }
    holder = active_ids[0] if active_ids else None
    holder_name = world.characters[holder].display_name() if holder is not None else None
    label = f"{holder_name} ready / {PLAYER_TURN_ACTIONS} actions left" if holder is not None else "No active cogs"
    return {
        "phase": world.phase.value,
        "holder": holder,
        "queue": active_ids,
        "label": label,
        "actions_per_turn": PLAYER_TURN_ACTIONS,
        "actions_remaining": PLAYER_TURN_ACTIONS if holder is not None else 0,
    }


def _global_visible_state(world: World) -> dict[str, Any]:
    return {
        "phase": world.phase.value,
        "step": world.current_step,
        "finished_reason": world.finished_reason,
        "ship": {
            **world.ship.snapshot(),
            "damaged_engines": world.ship.damaged_engines(),
            "survived": world.ship.survived(),
        },
        "rooms": {room_id: _room_state(world, room_id) for room_id in sorted(world.rooms)},
        "characters": {
            character_id: _public_character_state(character)
            for character_id, character in sorted(world.characters.items())
        },
        "intruders": {
            intruder_id: intruder.snapshot()
            for intruder_id, intruder in sorted(world.intruders.items())
        },
        "intruder_bag_counts": dict(sorted(Counter(kind.value for kind in world.intruder_bag).items())),
        "escape_pods": {
            pod_id: pod.snapshot()
            for pod_id, pod in sorted(world.escape_pods.items())
        },
        "noise_markers": [
            {"room_id": room_id, "corridor": corridor}
            for room_id, corridor in sorted(world.noise_markers)
        ],
        "fire_rooms": sorted(world.fire_rooms),
        "malfunction_rooms": sorted(world.malfunction_rooms),
        "discovered_weaknesses": world.discovered_weaknesses,
        "nest_eggs": world.nest_eggs,
        "killed_intruders": [kind.value for kind in world.killed_intruders],
    }


def _room_state(world: World, room_id: str) -> dict[str, Any]:
    room = world.rooms[room_id]
    return {
        **room.snapshot(),
        "characters": [
            _public_character_state(character)
            for character in sorted(world.room_characters(room_id), key=lambda item: item.character_id)
        ],
        "intruders": [
            intruder.snapshot()
            for intruder in sorted(world.room_intruders(room_id), key=lambda item: item.intruder_id)
        ],
        "noise_corridors": [
            corridor
            for marker_room_id, corridor in sorted(world.noise_markers)
            if marker_room_id == room_id
        ],
        "fire": room_id in world.fire_rooms,
        "malfunction": room_id in world.malfunction_rooms,
        "engine": next(
            (
                engine.snapshot()
                for engine in world.ship.engines.values()
                if engine.room_id == room_id
            ),
            None,
        ),
        "escape_pod": next(
            (
                pod.snapshot()
                for pod in world.escape_pods.values()
                if pod.room_id == room_id
            ),
            None,
        ),
    }


def _player_state(
    sim: CogisisSimulator,
    character_id: int,
    turn_token: dict[str, Any],
) -> dict[str, Any]:
    observation = sim.observation(character_id)
    queue = turn_token["queue"]
    character = sim.world.characters[character_id]
    return {
        "id": character_id,
        "display_name": character.display_name(),
        "has_turn_token": turn_token["holder"] == character_id,
        "turn_position": queue.index(character_id) + 1 if character_id in queue else None,
        "actions_remaining": turn_token.get("actions_remaining", 0) if turn_token["holder"] == character_id else 0,
        "observation": observation,
        "available_actions": _available_actions(sim, character_id),
        "action_options": _action_options(sim, character_id),
    }


def _client_stats(sim: CogisisSimulator) -> dict[str, Any]:
    stats = sim.stats()
    return {
        "steps": stats["steps"],
        "phase": stats["phase"],
        "done": stats["done"],
        "finished_reason": stats["finished_reason"],
        "ship_survived": stats["ship_survived"],
        "destination": stats["destination"],
        "winners": stats["winners"],
        "survivors": stats["survivors"],
    }


def _player_connection_state(
    world: World,
    player_connections: dict[int, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    connections = player_connections or {}
    return [
        {
            "id": character_id,
            "connected": bool(connections.get(character_id, {}).get("connected", False)),
            "last_seen_seconds": connections.get(character_id, {}).get("last_seen_seconds"),
        }
        for character_id in sorted(world.characters)
    ]


def _public_character_state(character: Character) -> dict[str, Any]:
    return {
        "id": character.character_id,
        "name": character.name,
        "display_name": character.display_name(),
        "role": character.role,
        "room_id": character.room_id,
        "status": character.status.value,
        "light_wounds": character.light_wounds,
        "serious_wounds": character.serious_wounds,
        "contamination": character.contamination,
        "slime": character.slime,
        "ammo": character.ammo,
        "signal_sent": character.signal_sent,
        "item_count": len(character.items),
        "action_hand_count": len(character.action_hand),
        "action_deck_count": len(character.action_deck),
        "action_discard_count": len(character.action_discard),
    }


def _available_actions(sim: CogisisSimulator, character_id: int) -> list[str]:
    return [
        action
        for option in _action_options(sim, character_id)
        for action in ([option["action"]] if option.get("action") else [choice["action"] for choice in option.get("choices", [])])
    ]


def _action_options(sim: CogisisSimulator, character_id: int) -> list[dict[str, Any]]:
    world = sim.world
    character = world.characters[character_id]
    if character.status is not CharacterStatus.ACTIVE or world.phase is Phase.FINISHED:
        return [{"id": "noop", "label": "Noop", "action": "noop", "kind": "immediate"}]

    room = world.rooms[character.room_id]
    options: list[dict[str, Any]] = [
        _action_option("pass", "Pass", character=character),
        _action_option("search", "Search", character=character),
        _action_option("rest", "Rest", character=character),
        _action_option("use_room", "Use room", character=character),
    ]

    if room.exits:
        options.append(
            {
                "id": "move",
                "label": "Move",
                "kind": "choice",
                "choice_label": "Pick a room",
                "choices": [
                    _choice_action(
                        character,
                        f"move:{neighbor_id}",
                        _room_choice_label(world.rooms[neighbor_id], corridor),
                        detail=f"Corridor {corridor}",
                    )
                    for corridor, neighbor_id in sorted(room.exits.items())
                ],
            }
        )
        options.append(
            {
                "id": "cautious_move",
                "label": "Cautious move",
                "kind": "choice",
                "choice_label": "Pick a room and corridor",
                "choices": [
                    _choice_action(
                        character,
                        f"cautious_move:{neighbor_id}:{corridor}",
                        _room_choice_label(world.rooms[neighbor_id], corridor),
                        detail=f"Place noise in corridor {corridor}",
                    )
                    for corridor, neighbor_id in sorted(room.exits.items())
                ],
            }
        )

    intruders_here = world.room_intruders(room.room_id)
    if intruders_here:
        options.append(
            {
                "id": "shoot",
                "label": "Shoot",
                "kind": "choice",
                "choice_label": "Pick an intruder",
                "choices": [
                    _choice_action(
                        character,
                        f"shoot:{intruder.intruder_id}",
                        f"{intruder.kind.value} {intruder.intruder_id}",
                        detail=f"{intruder.damage}/{intruder.health} damage",
                    )
                    for intruder in intruders_here
                ],
            }
        )
        options.append(
            {
                "id": "melee",
                "label": "Melee",
                "kind": "choice",
                "choice_label": "Pick an intruder",
                "choices": [
                    _choice_action(
                        character,
                        f"melee:{intruder.intruder_id}",
                        f"{intruder.kind.value} {intruder.intruder_id}",
                        detail=f"{intruder.damage}/{intruder.health} damage",
                    )
                    for intruder in intruders_here
                ],
            }
        )
    if room.kind.startswith("engine"):
        options.append(_action_option(f"repair:{room.kind}", "Repair engine", option_id="repair", character=character))
    if room.kind == "comms":
        options.append(_action_option("send_signal", "Send signal", character=character))
    if room.kind == "cockpit":
        options.append(
            {
                "id": "set_destination",
                "label": "Set destination",
                "kind": "choice",
                "choice_label": "Pick destination",
                "choices": [
                    _choice_action(character, "set_destination:earth", "Earth"),
                    _choice_action(character, "set_destination:mars", "Mars"),
                    _choice_action(character, "set_destination:deep_space", "Deep space"),
                ],
            }
        )
    if room.kind == "laboratory":
        options.append(_action_option("discover_weakness", "Discover weakness", character=character))
    if room.kind == "nest":
        options.append(_action_option("destroy_egg", "Destroy egg", character=character))
    if room.kind == "hibernatorium":
        options.append(_action_option("hibernate", "Hibernate", character=character))
    if room.kind == "cockpit":
        options.append(_action_option("start_self_destruct", "Start self destruct", option_id="self_destruct", character=character))
    escape_choices = []
    for pod_id, pod in sorted(world.escape_pods.items()):
        if pod.room_id == room.room_id:
            escape_choices.append(
                _choice_action(
                    character,
                    f"escape:{pod_id}",
                    pod_id.replace("_", " ").title(),
                    detail="unlocked" if pod.unlocked else "locked",
                )
            )
    if escape_choices:
        options.append(
            {
                "id": "escape",
                "label": "Escape",
                "kind": "choice",
                "choice_label": "Pick an escape pod",
                "choices": escape_choices,
            }
        )
    return options


def _action_option(action: str, label: str, *, option_id: str | None = None, character: Character | None = None) -> dict[str, Any]:
    payment = _payment_metadata(character, action) if character is not None else {"cost": CogisisSimulator.action_cost(action)}
    return {
        "id": option_id or action.split(":", 1)[0],
        "label": label,
        "action": action,
        "kind": "immediate",
        **payment,
    }


def _choice_action(character: Character, action: str, label: str, *, detail: str | None = None) -> dict[str, Any]:
    choice: dict[str, Any] = {
        "label": label,
        "action": action,
        **_payment_metadata(character, action),
    }
    if detail is not None:
        choice["detail"] = detail
    return choice


def _payment_metadata(character: Character, action: str) -> dict[str, Any]:
    cost = CogisisSimulator.action_cost(action)
    metadata: dict[str, Any] = {"cost": cost, "discard_cost": max(0, cost)}
    if cost <= 0:
        metadata["discard_cost"] = 0
        return metadata

    playable_card = _playable_action_card(character, action)
    if playable_card is None:
        return metadata

    metadata.update(
        {
            "play_card_id": playable_card["id"],
            "play_card_name": playable_card["name"],
            "discard_cost": max(0, cost - 1),
        }
    )
    return metadata


def _playable_action_card(character: Character, action: str) -> dict[str, str] | None:
    allowed_card_types = ACTION_CARD_TYPES_BY_VERB.get(_action_verb(action), ())
    if not allowed_card_types:
        return None
    for card in character.action_hand:
        if _action_card_type(card) in allowed_card_types:
            return card
    return None


def _action_verb(action: str) -> str:
    return action.split(":", 1)[0] if action else "noop"


def _action_card_type(card: dict[str, str]) -> str:
    card_id = card.get("id", "")
    if "_" not in card_id:
        return card_id
    return card_id.rsplit("_", 1)[0]


def _room_choice_label(room: Room, corridor: int) -> str:
    return room.name if room.explored else f"Unknown room via corridor {corridor}"


def _ship_edges(world: World) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for room_id, room in sorted(world.rooms.items()):
        for corridor, target_room_id in sorted(room.exits.items()):
            key = tuple(sorted((room_id, target_room_id)))
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                {
                    "from": room_id,
                    "to": target_room_id,
                    "corridors": {
                        room_id: corridor,
                        target_room_id: world.corridor_between(target_room_id, room_id),
                    },
                }
            )
    return edges


_CLIENT_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>__TITLE__</title>
  <style>
    :root {
      --bg: #10100f;
      --panel: #181917;
      --panel-2: #22241f;
      --line: #3a3d34;
      --text: #f1efe6;
      --muted: #aaa590;
      --accent: #58bda4;
      --amber: #d8a94d;
      --red: #c85b57;
      --green: #7ba85f;
      --violet: #9a83cf;
      --room: #2b2f29;
      --room-hot: #4b2825;
      --room-risk: #43361d;
      --room-active: #21413a;
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: var(--bg);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 20% 0%, rgba(88, 189, 164, 0.12), transparent 28rem),
        linear-gradient(135deg, #11110f 0%, #171814 48%, #10100f 100%);
    }

    .app-shell {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(340px, 0.65fr);
      gap: 16px;
      width: min(1640px, 100%);
      min-height: 100vh;
      margin: 0 auto;
      padding: 16px;
    }

    .left-stack,
    .right-stack {
      display: grid;
      gap: 16px;
      align-content: start;
    }

    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(24, 25, 23, 0.94);
      box-shadow: 0 18px 44px rgba(0, 0, 0, 0.28);
    }

    .panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .cog-launchers {
      display: flex;
      flex: 1 1 auto;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
      min-width: 0;
    }

    .cog-launchers[hidden] {
      display: none;
    }

    h1,
    h2,
    h3 {
      margin: 0;
      letter-spacing: 0;
    }

    h1 {
      font-size: 16px;
      font-weight: 750;
    }

    h2 {
      font-size: 13px;
      font-weight: 720;
      text-transform: uppercase;
      color: var(--muted);
    }

    h3 {
      font-size: 13px;
      font-weight: 720;
    }

    .token {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      padding: 6px 10px;
      border: 1px solid rgba(88, 189, 164, 0.55);
      border-radius: 999px;
      color: var(--text);
      background: rgba(88, 189, 164, 0.14);
      font-size: 12px;
      font-weight: 760;
      white-space: nowrap;
    }

    .token-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(88, 189, 164, 0.16);
    }

    .god-mode-button {
      height: 34px;
      border-color: rgba(216, 169, 77, 0.62);
      color: #f4db9d;
      background: rgba(216, 169, 77, 0.12);
    }

    .god-mode-button.active {
      color: #14110a;
      border-color: #f2c76e;
      background: #d8a94d;
    }

    .cog-launcher {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 34px;
      border: 1px solid #4d5245;
      border-radius: 6px;
      padding: 0 12px;
      border-color: #4d5245;
      color: var(--text);
      background: #20231d;
      font-size: 13px;
      font-weight: 760;
      text-decoration: none;
      white-space: nowrap;
      cursor: pointer;
    }

    .cog-launcher:hover {
      border-color: var(--accent);
    }

    .cog-launcher.active-turn {
      border-color: rgba(88, 189, 164, 0.8);
      background: rgba(88, 189, 164, 0.14);
    }

    .cog-launcher.connected {
      border-color: rgba(123, 168, 95, 0.7);
    }

    .connection-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #686c5d;
      box-shadow: 0 0 0 3px rgba(104, 108, 93, 0.12);
    }

    .connection-dot.connected {
      background: var(--green);
      box-shadow: 0 0 0 3px rgba(123, 168, 95, 0.18);
    }

    .map-panel {
      overflow: hidden;
    }

    .map-wrap {
      width: 100%;
      padding: 12px;
      overflow: auto;
    }

    .ship-map {
      display: block;
      min-width: 980px;
      width: 100%;
      height: auto;
      border-radius: 8px;
      background: #060908;
      border: 1px solid #2c2f28;
    }

    .board-bg {
      fill: #060908;
    }

    .ship-hull {
      fill: url(#hullGradient);
      stroke: rgba(128, 199, 185, 0.48);
      stroke-width: 3;
      filter: url(#softGlow);
    }

    .hull-panel {
      fill: rgba(50, 70, 65, 0.2);
      stroke: rgba(159, 192, 177, 0.18);
      stroke-width: 1.5;
    }

    .corridor-shadow {
      fill: none;
      stroke: rgba(0, 0, 0, 0.48);
      stroke-width: 32;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .corridor-shell {
      fill: none;
      stroke: rgba(69, 113, 106, 0.72);
      stroke-width: 24;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .corridor-core {
      fill: none;
      stroke: rgba(142, 216, 198, 0.28);
      stroke-width: 8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .noise-marker {
      filter: url(#slotShadow);
      pointer-events: none;
    }

    .noise-marker-ring {
      fill: rgba(216, 169, 77, 0.92);
      stroke: rgba(246, 230, 178, 0.92);
      stroke-width: 2;
    }

    .noise-marker-core {
      fill: #171913;
      stroke: rgba(46, 38, 21, 0.7);
      stroke-width: 1;
    }

    .noise-marker-label {
      fill: #f8e7b7;
      font-size: 11px;
      font-weight: 850;
      text-anchor: middle;
      dominant-baseline: central;
    }

    .board-slot {
      fill: url(#slotGradient);
      stroke: rgba(164, 211, 196, 0.52);
      stroke-width: 2;
      filter: url(#slotShadow);
    }

    .board-slot.engine-slot {
      fill: url(#engineGradient);
      stroke: rgba(216, 169, 77, 0.62);
    }

    .board-slot.fixed-slot {
      stroke: rgba(88, 189, 164, 0.74);
    }

    .escape-shell {
      fill: rgba(35, 48, 46, 0.58);
      stroke: rgba(92, 162, 177, 0.62);
      stroke-width: 2;
    }

    .ship-nose,
    .engine-pod {
      fill: rgba(31, 43, 40, 0.72);
      stroke: rgba(164, 211, 196, 0.36);
      stroke-width: 2;
    }

    .board-detail {
      fill: none;
      stroke: rgba(241, 239, 230, 0.13);
      stroke-width: 1.5;
    }

    .slot-mark {
      fill: rgba(241, 239, 230, 0.42);
      font-size: 10px;
      font-weight: 800;
      text-anchor: middle;
    }

    .room-shape {
      fill: rgba(8, 9, 8, 0.2);
      stroke: rgba(241, 239, 230, 0.62);
      stroke-width: 2;
      stroke-linejoin: round;
    }

    .room.active .room-shape {
      fill: rgba(33, 65, 58, 0.18);
      stroke: var(--accent);
    }

    .room.risk .room-shape {
      fill: rgba(67, 54, 29, 0.2);
      stroke: var(--amber);
    }

    .room.hot .room-shape {
      fill: rgba(75, 40, 37, 0.24);
      stroke: var(--red);
    }

    .room.unexplored .room-shape {
      fill: rgba(8, 9, 8, 0.1);
      stroke: #55594d;
      stroke-dasharray: 6 5;
    }

    .room-label-bg {
      fill: rgba(10, 11, 10, 0.76);
      stroke: rgba(241, 239, 230, 0.28);
      stroke-width: 1;
    }

    .room-name {
      fill: var(--text);
      font-size: 11px;
      font-weight: 780;
    }

    .room-kind {
      fill: var(--muted);
      font-size: 7px;
      text-transform: uppercase;
    }

    .token-pill {
      font-size: 8px;
      font-weight: 780;
    }

    .pill-bg.character {
      fill: var(--accent);
    }

    .pill-bg.intruder {
      fill: var(--red);
    }

    .pill-bg.noise {
      fill: var(--amber);
    }

    .pill-bg.system {
      fill: var(--violet);
    }

    .controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 12px 14px;
      border-top: 1px solid var(--line);
    }

    button {
      height: 34px;
      border: 1px solid #4d5245;
      border-radius: 6px;
      padding: 0 12px;
      color: var(--text);
      background: #242720;
      font-weight: 760;
      cursor: pointer;
    }

    button:hover {
      border-color: var(--accent);
    }

    button:disabled {
      cursor: default;
      color: #777263;
      border-color: #33362e;
      background: #1b1c19;
    }

    input[type="range"] {
      flex: 1 1 220px;
      accent-color: var(--accent);
    }

    .frame-count {
      min-width: 84px;
      color: var(--muted);
      font-size: 12px;
      text-align: right;
    }

    .state-panel .panel-header {
      padding: 10px 14px;
    }

    .state-grid {
      display: grid;
      grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr) minmax(0, 1.3fr);
      gap: 6px;
      padding: 10px 14px 8px;
    }

    .state-group {
      display: grid;
      gap: 6px;
      min-width: 0;
      border: 1px solid #34372f;
      border-radius: 6px;
      padding: 7px 8px;
      background: var(--panel-2);
    }

    .state-group h3 {
      color: var(--muted);
      font-size: 10px;
      font-weight: 760;
      text-transform: uppercase;
    }

    .state-pairs {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(72px, 1fr));
      gap: 5px 10px;
      min-width: 0;
    }

    .state-pair {
      min-width: 0;
    }

    .state-pair span {
      display: block;
      color: var(--muted);
      font-size: 9px;
      line-height: 1.1;
      text-transform: uppercase;
    }

    .state-pair strong {
      display: block;
      margin-top: 2px;
      overflow-wrap: anywhere;
      font-size: 13px;
      line-height: 1.15;
    }

    .state-detail-grid {
      display: grid;
      grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
      gap: 6px;
      padding: 0 14px 12px;
    }

    .state-detail-block {
      min-width: 0;
      border: 1px solid #34372f;
      border-radius: 6px;
      padding: 7px;
      background: #1d1f1b;
    }

    .state-detail-block .section-label {
      margin-bottom: 5px;
    }

    .engine-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px;
    }

    .engine-chip {
      display: grid;
      align-content: start;
      min-width: 0;
      gap: 2px;
      border: 1px solid #34372f;
      border-radius: 6px;
      padding: 5px 6px;
      background: #1d1f1b;
      font-size: 11px;
    }

    .engine-chip b {
      min-width: 0;
      color: var(--text);
      line-height: 1.15;
      overflow-wrap: anywhere;
    }

    .engine-chip span {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }

    .system-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 5px;
    }

    .system-chip {
      display: grid;
      min-width: 0;
      gap: 2px;
      border: 1px solid #34372f;
      border-radius: 6px;
      padding: 5px 6px;
      background: #1d1f1b;
    }

    .system-chip b {
      color: var(--text);
      font-size: 11px;
      line-height: 1.15;
    }

    .system-chip span {
      color: var(--muted);
      font-size: 10px;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }

    .players {
      display: grid;
      gap: 10px;
      padding: 12px 14px 14px;
    }

    .player-card {
      border: 1px solid #383b32;
      border-radius: 8px;
      background: #1d1f1b;
      overflow: hidden;
    }

    .player-card.active-token {
      border-color: var(--accent);
      box-shadow: inset 4px 0 0 var(--accent);
    }

    .player-top {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 10px;
      border-bottom: 1px solid #34372f;
      background: #20231d;
    }

    .player-meta {
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
    }

    .player-body {
      display: grid;
      gap: 8px;
      padding: 10px;
    }

    .mini-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 6px;
    }

    .mini {
      border: 1px solid #33362e;
      border-radius: 6px;
      padding: 6px;
      background: #181a17;
      font-size: 12px;
    }

    .mini span {
      display: block;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
    }

    .chips {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }

    .chip {
      border: 1px solid #44483e;
      border-radius: 999px;
      padding: 3px 7px;
      color: var(--text);
      background: #262921;
      font-size: 11px;
      font-weight: 700;
    }

    .chip.good {
      border-color: rgba(123, 168, 95, 0.7);
      background: rgba(123, 168, 95, 0.14);
    }

    .chip.warn {
      border-color: rgba(216, 169, 77, 0.7);
      background: rgba(216, 169, 77, 0.14);
    }

    .chip.bad {
      border-color: rgba(200, 91, 87, 0.7);
      background: rgba(200, 91, 87, 0.14);
    }

    .section-label {
      color: var(--muted);
      font-size: 10px;
      font-weight: 760;
      text-transform: uppercase;
    }

    .private-hidden {
      border: 1px dashed #4c4f44;
      border-radius: 6px;
      padding: 8px;
      color: var(--muted);
      background: #191b17;
      font-size: 12px;
    }

    .action-panel {
      display: grid;
      gap: 8px;
    }

    .card-hand {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(94px, 1fr));
      gap: 6px;
    }

    .action-card {
      min-height: 48px;
      border: 1px solid #44483e;
      border-radius: 6px;
      padding: 7px;
      color: var(--text);
      background: #181a17;
      text-align: left;
    }

    .action-card.selected {
      border-color: var(--accent);
      background: rgba(88, 189, 164, 0.24);
      box-shadow: inset 0 0 0 2px rgba(88, 189, 164, 0.55);
    }

    .action-card b,
    .action-card span {
      display: block;
      overflow-wrap: anywhere;
    }

    .action-card span {
      color: var(--muted);
      font-size: 10px;
      font-weight: 650;
    }

    .selected-indicator {
      margin-top: 5px;
      color: #7fd6c1;
      font-size: 10px;
      font-weight: 850;
      text-transform: uppercase;
    }

    .payment-panel {
      display: grid;
      gap: 7px;
      border: 1px solid #34372f;
      border-radius: 6px;
      padding: 8px;
      background: #181a17;
    }

    .name-form {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 6px;
    }

    .name-input {
      min-width: 0;
      height: 32px;
      border: 1px solid #44483e;
      border-radius: 6px;
      padding: 0 8px;
      color: var(--text);
      background: #181a17;
      font: inherit;
      font-size: 12px;
    }

    .name-input:focus {
      border-color: var(--accent);
      outline: none;
    }

    .action-buttons,
    .choice-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .action-button {
      height: 32px;
      min-width: 92px;
    }

    .action-button.open {
      border-color: var(--accent);
      background: rgba(88, 189, 164, 0.18);
    }

    .choice-panel {
      display: grid;
      gap: 7px;
      border: 1px solid #34372f;
      border-radius: 6px;
      padding: 8px;
      background: #181a17;
    }

    .choice-detail {
      display: block;
      color: var(--muted);
      font-size: 10px;
      font-weight: 650;
    }

    .action-status {
      color: var(--muted);
      font-size: 12px;
    }

    .action-status.error {
      color: #f1a19d;
    }

    .events {
      max-height: 220px;
      overflow: auto;
      padding: 0 14px 14px;
    }

    .event-line {
      border-bottom: 1px solid #30332b;
      padding: 7px 0;
      color: #d5d0bd;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 11px;
      overflow-wrap: anywhere;
    }

    @media (max-width: 1080px) {
      .app-shell {
        grid-template-columns: 1fr;
      }

    }

    @media (max-width: 640px) {
      .app-shell {
        padding: 8px;
      }

      .mini-grid {
        grid-template-columns: 1fr;
      }

      .panel-header,
      .controls {
        align-items: stretch;
        flex-direction: column;
      }

      .cog-launchers {
        justify-content: flex-start;
      }

      .header-actions {
        align-items: stretch;
        flex-direction: column;
      }

      .frame-count {
        text-align: left;
      }
    }

    @media (max-width: 480px) {
      .state-grid,
      .state-detail-grid,
      .engine-strip,
      .system-strip {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <script id="client-data" type="application/json">__CLIENT_DATA__</script>
  <main class="app-shell">
    <section class="left-stack">
      <section class="panel map-panel">
        <div class="panel-header">
          <h1 id="clientTitle">Cogisis global client</h1>
          <div id="cogLaunchers" class="cog-launchers" aria-label="Cog player clients"></div>
          <div class="header-actions">
            __GOD_MODE_BUTTON__
            <div class="token"><span class="token-dot"></span><span id="turnToken">Token</span></div>
          </div>
        </div>
        <div class="map-wrap">
          <svg id="shipMap" class="ship-map" viewBox="0 0 1145 760" role="img" aria-label="Cogisis ship layout"></svg>
        </div>
        <div class="controls">
          <button id="prevButton" type="button">Prev</button>
          <button id="playButton" type="button">Play</button>
          <button id="nextButton" type="button">Next</button>
          <input id="frameSlider" type="range" min="0" value="0">
          <span id="frameCount" class="frame-count"></span>
        </div>
      </section>
      <section class="panel state-panel">
        <div class="panel-header">
          <h2>Global ship state</h2>
          <span id="finishedReason" class="chip"></span>
        </div>
        <div id="stateGrid" class="state-grid"></div>
        <div class="state-detail-grid">
          <div class="state-detail-block">
            <div class="section-label">Engines</div>
            <div id="engineList" class="engine-strip"></div>
          </div>
          <div class="state-detail-block">
            <div class="section-label">Hazards</div>
            <div id="systemList" class="system-strip"></div>
          </div>
        </div>
      </section>
    </section>
    <aside class="right-stack">
      <section class="panel">
        <div class="panel-header">
          <h2>Player panels</h2>
          <span id="playerCount" class="chip"></span>
        </div>
        <div id="players" class="players"></div>
      </section>
      <section class="panel">
        <div class="panel-header">
          <h2>Recent events</h2>
          <span id="eventCount" class="chip"></span>
        </div>
        <div id="events" class="events"></div>
      </section>
    </aside>
  </main>
  <script>
    const payload = JSON.parse(document.getElementById("client-data").textContent);
    let frames = payload.frames || [];
    const liveEndpoint = payload.live_endpoint || null;
    const selectedAgentId = payload.selected_agent_id;
    const playerAuth = payload.player_auth || null;
    const playerUrls = payload.player_urls || [];
    let currentFrame = 0;
    let playTimer = null;
    let godMode = false;
    let openChoiceId = null;
    let pendingAction = null;
    let actionMessage = "";
    let actionMessageKind = "info";
    let selectedPaymentAction = null;
    let selectedDiscardCards = new Set();

    const map = document.getElementById("shipMap");
    const slider = document.getElementById("frameSlider");
    const frameCount = document.getElementById("frameCount");
    const turnToken = document.getElementById("turnToken");
    const playButton = document.getElementById("playButton");
    const prevButton = document.getElementById("prevButton");
    const nextButton = document.getElementById("nextButton");
    const revealButton = __GOD_MODE_BUTTON_LOOKUP__;
    const allowGodMode = revealButton !== null;
    const cogLaunchers = document.getElementById("cogLaunchers");

    document.getElementById("clientTitle").textContent = document.title;
    slider.max = String(Math.max(0, frames.length - 1));

    function svg(tag, attrs = {}) {
      const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
      for (const [key, value] of Object.entries(attrs)) {
        node.setAttribute(key, String(value));
      }
      return node;
    }

    function el(tag, className, text) {
      const node = document.createElement(tag);
      if (className) {
        node.className = className;
      }
      if (text !== undefined) {
        node.textContent = text;
      }
      return node;
    }

    function clear(node) {
      node.replaceChildren();
    }

    function titleCase(text) {
      return String(text).replaceAll("_", " ").replace(/\\b\\w/g, (letter) => letter.toUpperCase());
    }

    function displayCharacterName(value) {
      const source = value && value.observation ? value.observation.self : value;
      if (!source) return "Unknown";
      return source.display_name || source.name || `Cog ${source.id}`;
    }

    function displayCharacterNameById(frame, characterId) {
      const player = (frame.players || []).find((item) => item.id === characterId);
      if (player) return displayCharacterName(player);
      const character = frame.global.characters[String(characterId)] || frame.global.characters[characterId];
      return character ? displayCharacterName(character) : `Cog ${characterId}`;
    }

    function shortRoom(roomId) {
      return String(roomId).replace("engine_", "eng ");
    }

    function formatObjective(objective, frame) {
      let text = titleCase(objective.kind);
      if (objective.target_character_id !== undefined && objective.target_character_id !== null) {
        text += ` / ${displayCharacterNameById(frame, objective.target_character_id)}`;
      }
      return text;
    }

    function roomKnown(room) {
      return (allowGodMode && godMode) || Boolean(room.explored);
    }

    function displayRoomName(room) {
      return roomKnown(room) ? room.name : "Unexplored";
    }

    function displayRoomKind(room) {
      return roomKnown(room) ? room.kind : "UNKNOWN";
    }

    function displayNeighborName(corridor, room) {
      return roomKnown(room) ? room.name : `unknown via ${corridor}`;
    }

    function ownsPlayer(player) {
      return Boolean(playerAuth && Number(playerAuth.slot) === player.id);
    }

    function canRevealPrivate(player) {
      return (allowGodMode && godMode) || ownsPlayer(player);
    }

    function captureFocusedNameDraft() {
      const active = document.activeElement;
      if (!active || !active.classList || !active.classList.contains("name-input")) {
        return null;
      }
      const form = active.closest(".name-form");
      if (!form || !form.dataset.playerId) {
        return null;
      }
      return {
        playerId: form.dataset.playerId,
        value: active.value,
        selectionStart: active.selectionStart,
        selectionEnd: active.selectionEnd,
      };
    }

    function restoreFocusedNameDraft(draft) {
      if (!draft) {
        return;
      }
      const inputs = document.querySelectorAll(".name-form .name-input");
      for (const input of inputs) {
        const form = input.closest(".name-form");
        if (!form || form.dataset.playerId !== draft.playerId) {
          continue;
        }
        input.value = draft.value;
        input.focus({ preventScroll: true });
        if (
          typeof input.setSelectionRange === "function"
          && draft.selectionStart !== null
          && draft.selectionEnd !== null
        ) {
          input.setSelectionRange(draft.selectionStart, draft.selectionEnd);
        }
        return;
      }
    }

    function setGodMode(enabled) {
      if (!allowGodMode) {
        return;
      }
      godMode = enabled;
      revealButton.classList.toggle("active", godMode);
      revealButton.setAttribute("aria-pressed", String(godMode));
      render();
    }

    function playerConnection(frame, playerId) {
      return (frame.player_connections || []).find((connection) => connection.id === playerId) || {
        connected: false,
        last_seen_seconds: null,
      };
    }

    function hexPoints(cx, cy, width, height) {
      const halfWidth = width / 2;
      const halfHeight = height / 2;
      const shoulder = width * 0.22;
      return [
        `${cx - halfWidth + shoulder},${cy - halfHeight}`,
        `${cx + halfWidth - shoulder},${cy - halfHeight}`,
        `${cx + halfWidth},${cy}`,
        `${cx + halfWidth - shoulder},${cy + halfHeight}`,
        `${cx - halfWidth + shoulder},${cy + halfHeight}`,
        `${cx - halfWidth},${cy}`,
      ].join(" ");
    }

    function drawPath(parent, className, d) {
      parent.appendChild(svg("path", { class: className, d }));
    }

    function corridorNoisePosition(marker, layout, edges, corridorPaths) {
      const edge = (edges || []).find((item) => {
        return item.corridors
          && item.corridors[marker.room_id] === marker.corridor
          && layout[item.from]
          && layout[item.to];
      });
      if (!edge) {
        return null;
      }

      const path = corridorPaths.find((item) => {
        return (item.from === edge.from && item.to === edge.to)
          || (item.from === edge.to && item.to === edge.from);
      });
      if (path) {
        const probe = svg("path", { d: path.d });
        try {
          const total = probe.getTotalLength();
          const fraction = path.from === marker.room_id ? 0.28 : 0.72;
          const point = probe.getPointAtLength(total * fraction);
          return { x: point.x, y: point.y };
        } catch {
          // Fall back to linear interpolation below if SVG path metrics are unavailable.
        }
      }

      const source = layout[marker.room_id];
      const targetId = edge.from === marker.room_id ? edge.to : edge.from;
      const target = layout[targetId];
      if (!source || !target) {
        return null;
      }
      return {
        x: source.x + (target.x - source.x) * 0.28,
        y: source.y + (target.y - source.y) * 0.28,
      };
    }

    function drawNoiseMarkers(frame, layout, corridorPaths) {
      for (const marker of frame.global.noise_markers || []) {
        const point = corridorNoisePosition(marker, layout, frame.layout.edges, corridorPaths);
        if (!point) {
          continue;
        }
        const group = svg("g", {
          class: "noise-marker",
          transform: `translate(${point.x}, ${point.y})`,
          "aria-label": `Noise marker ${marker.room_id} corridor ${marker.corridor}`,
        });
        group.appendChild(svg("circle", { class: "noise-marker-ring", cx: 0, cy: 0, r: 13 }));
        group.appendChild(svg("circle", { class: "noise-marker-core", cx: 0, cy: 0, r: 8 }));
        const label = svg("text", { class: "noise-marker-label", x: 0, y: 1 });
        label.textContent = String(marker.corridor);
        group.appendChild(label);
        map.appendChild(group);
      }
    }

    function drawGeneratedBoard(frame, layout) {
      const defs = svg("defs");
      defs.innerHTML = `
        <linearGradient id="hullGradient" x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stop-color="#172421" />
          <stop offset="52%" stop-color="#0f1715" />
          <stop offset="100%" stop-color="#17201d" />
        </linearGradient>
        <radialGradient id="slotGradient" cx="50%" cy="45%" r="70%">
          <stop offset="0%" stop-color="#32443f" />
          <stop offset="100%" stop-color="#151d1a" />
        </radialGradient>
        <radialGradient id="engineGradient" cx="50%" cy="45%" r="70%">
          <stop offset="0%" stop-color="#483c25" />
          <stop offset="100%" stop-color="#1a1814" />
        </radialGradient>
        <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#58bda4" flood-opacity="0.16" />
        </filter>
        <filter id="slotShadow" x="-30%" y="-30%" width="160%" height="160%">
          <feDropShadow dx="0" dy="5" stdDeviation="6" flood-color="#000000" flood-opacity="0.38" />
        </filter>
      `;
      map.appendChild(defs);
      map.appendChild(svg("rect", { class: "board-bg", x: 0, y: 0, width: frame.layout.width, height: frame.layout.height }));

      const stars = [
        [58, 76], [122, 628], [178, 116], [282, 84], [345, 708], [458, 110],
        [548, 708], [700, 92], [812, 690], [930, 118], [1010, 690], [1102, 260],
      ];
      for (const [x, y] of stars) {
        map.appendChild(svg("circle", { class: "slot-mark", cx: x, cy: y, r: 1.4 }));
      }

      drawPath(
        map,
        "ship-hull",
        "M 38 340 C 72 160 220 70 420 78 L 800 78 C 980 92 1106 200 1120 360 C 1106 535 964 670 760 690 L 430 690 C 235 684 78 570 38 420 Z",
      );
      drawPath(map, "hull-panel", "M 170 210 C 310 128 498 116 674 128 C 548 190 434 234 318 330 C 270 294 225 255 170 210 Z");
      drawPath(map, "hull-panel", "M 500 532 C 640 468 785 450 960 500 C 902 604 778 652 624 650 C 575 624 535 586 500 532 Z");
      drawPath(map, "ship-nose", "M 42 315 C 72 280 106 280 138 315 L 138 420 C 106 455 72 455 42 420 Z");

      const corridors = [
        { from: "hibernatorium", to: "atrium", d: `M ${layout.hibernatorium.x} ${layout.hibernatorium.y} C 560 374 490 385 ${layout.atrium.x} ${layout.atrium.y}` },
        { from: "hibernatorium", to: "engine_1", d: `M ${layout.hibernatorium.x} ${layout.hibernatorium.y} C 635 470 760 570 ${layout.engine_1.x} ${layout.engine_1.y}` },
        { from: "hibernatorium", to: "escape_a", d: `M ${layout.hibernatorium.x} ${layout.hibernatorium.y} C 575 505 505 625 ${layout.escape_a.x} ${layout.escape_a.y}` },
        { from: "atrium", to: "cockpit", d: `M ${layout.atrium.x} ${layout.atrium.y} C 290 380 190 370 ${layout.cockpit.x} ${layout.cockpit.y}` },
        { from: "atrium", to: "comms", d: `M ${layout.atrium.x} ${layout.atrium.y} C 360 280 310 210 ${layout.comms.x} ${layout.comms.y}` },
        { from: "atrium", to: "laboratory", d: `M ${layout.atrium.x} ${layout.atrium.y} C 500 500 575 585 ${layout.laboratory.x} ${layout.laboratory.y}` },
        { from: "atrium", to: "nest", d: `M ${layout.atrium.x} ${layout.atrium.y} C 500 275 560 190 ${layout.nest.x} ${layout.nest.y}` },
        { from: "cockpit", to: "engine_2", d: `M ${layout.cockpit.x} ${layout.cockpit.y} C 210 245 430 205 668 210 C 830 215 985 290 ${layout.engine_2.x} ${layout.engine_2.y}` },
        { from: "comms", to: "storage", d: `M ${layout.comms.x} ${layout.comms.y} C 210 305 255 505 ${layout.storage.x} ${layout.storage.y}` },
        { from: "storage", to: "engine_1", d: `M ${layout.storage.x} ${layout.storage.y} C 710 690 930 675 ${layout.engine_1.x} ${layout.engine_1.y}` },
        { from: "nest", to: "engine_3", d: `M ${layout.nest.x} ${layout.nest.y} C 790 112 930 110 ${layout.engine_3.x} ${layout.engine_3.y}` },
        { from: "nest", to: "escape_b", d: `M ${layout.nest.x} ${layout.nest.y} C 520 92 440 72 ${layout.escape_b.x} ${layout.escape_b.y}` },
        { from: "laboratory", to: "surgery", d: `M ${layout.laboratory.x} ${layout.laboratory.y} C 710 635 780 626 ${layout.surgery.x} ${layout.surgery.y}` },
        { from: "surgery", to: "armory", d: `M ${layout.surgery.x} ${layout.surgery.y} C 840 498 805 400 ${layout.armory.x} ${layout.armory.y}` },
        { from: "armory", to: "engine_2", d: `M ${layout.armory.x} ${layout.armory.y} C 890 318 985 340 ${layout.engine_2.x} ${layout.engine_2.y}` },
      ];
      for (const corridor of corridors) drawPath(map, "corridor-shadow", corridor.d);
      for (const corridor of corridors) drawPath(map, "corridor-shell", corridor.d);
      for (const corridor of corridors) drawPath(map, "corridor-core", corridor.d);

      const escapePods = [
        { id: "escape_b", angle: -16 },
        { id: "escape_a", angle: 16 },
      ];
      for (const pod of escapePods) {
        const pos = layout[pod.id];
        const shell = svg("rect", {
          class: "escape-shell",
          x: pos.x - 50,
          y: pos.y - 28,
          width: 100,
          height: 56,
          rx: 24,
          transform: `rotate(${pod.angle} ${pos.x} ${pos.y})`,
        });
        map.appendChild(shell);
      }

      for (const engineId of ["engine_3", "engine_2", "engine_1"]) {
        const pos = layout[engineId];
        map.appendChild(svg("ellipse", { class: "engine-pod", cx: pos.x, cy: pos.y, rx: 68, ry: 46 }));
        map.appendChild(svg("path", {
          class: "board-detail",
          d: `M ${pos.x - 42} ${pos.y} L ${pos.x + 42} ${pos.y} M ${pos.x - 26} ${pos.y - 22} L ${pos.x + 26} ${pos.y + 22}`,
        }));
      }

      const fixedRooms = new Set(["cockpit", "hibernatorium"]);
      const engineRooms = new Set(["engine_1", "engine_2", "engine_3"]);
      let slotIndex = 1;
      for (const roomId of Object.keys(layout)) {
        const pos = layout[roomId];
        const classes = ["board-slot"];
        if (fixedRooms.has(roomId)) classes.push("fixed-slot");
        if (engineRooms.has(roomId)) classes.push("engine-slot");
        map.appendChild(svg("polygon", {
          class: classes.join(" "),
          points: hexPoints(pos.x, pos.y, engineRooms.has(roomId) ? 86 : 82, engineRooms.has(roomId) ? 48 : 70),
        }));
        const mark = svg("text", { class: "slot-mark", x: pos.x, y: pos.y + 4 });
        mark.textContent = fixedRooms.has(roomId) ? "" : String(slotIndex).padStart(2, "0");
        map.appendChild(mark);
        slotIndex += 1;
      }

      for (const d of [
        "M 130 310 C 170 285 205 252 235 210",
        "M 140 430 C 220 500 312 555 430 690",
        "M 750 88 C 840 152 928 210 1050 210",
        "M 760 690 C 870 625 965 555 1096 506",
      ]) {
        drawPath(map, "board-detail", d);
      }

      drawNoiseMarkers(frame, layout, corridors);
    }

    async function submitAction(action, discardCards = []) {
      if (!playerAuth || pendingAction) {
        return;
      }
      pendingAction = action;
      actionMessage = `Submitting ${action}`;
      actionMessageKind = "info";
      render();
      try {
        const response = await fetch("/player/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            slot: playerAuth.slot,
            token: playerAuth.token,
            action,
            "discard": discardCards,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          throw new Error(data.error || `action failed with HTTP ${response.status}`);
        }
        frames = [data.frame];
        currentFrame = 0;
        openChoiceId = null;
        selectedPaymentAction = null;
        selectedDiscardCards = new Set();
        actionMessage = `Submitted ${action}`;
        actionMessageKind = "info";
      } catch (error) {
        actionMessage = error instanceof Error ? error.message : String(error);
        actionMessageKind = "error";
      } finally {
        pendingAction = null;
        render();
      }
    }

    function drawMap(frame) {
      clear(map);
      map.setAttribute("viewBox", `0 0 ${frame.layout.width} ${frame.layout.height}`);
      const layout = frame.layout.rooms;
      drawGeneratedBoard(frame, layout);
      const roomWidth = frame.layout.room_width || 134;
      const roomHeight = frame.layout.room_height || 84;
      for (const roomId of Object.keys(layout)) {
        const pos = layout[roomId];
        const room = frame.global.rooms[roomId];
        const known = roomKnown(room);
        const classes = ["room"];
        if (!known) classes.push("unexplored");
        if (room.characters.length > 0) classes.push("active");
        if (known && (room.intruders.length > 0 || room.noise_corridors.length > 0 || room.malfunction)) classes.push("risk");
        if (known && room.fire) classes.push("hot");

        const xInset = 7;
        const topShoulder = Math.round(roomHeight * 0.25);
        const bottomShoulder = roomHeight - topShoulder;
        const points = [
          `${roomWidth / 2},2`,
          `${roomWidth - xInset},${topShoulder}`,
          `${roomWidth - xInset},${bottomShoulder}`,
          `${roomWidth / 2},${roomHeight - 2}`,
          `${xInset},${bottomShoulder}`,
          `${xInset},${topShoulder}`,
        ].join(" ");
        const group = svg("g", {
          class: classes.join(" "),
          transform: `translate(${pos.x - roomWidth / 2}, ${pos.y - roomHeight / 2})`,
        });
        const shape = svg("polygon", { class: "room-shape", points });
        group.appendChild(shape);

        const roomLabel = displayRoomName(room);
        const labelWidth = Math.min(roomWidth - 14, Math.max(54, roomLabel.length * 6 + 12));
        group.appendChild(svg("rect", {
          class: "room-label-bg",
          x: 7,
          y: 7,
          width: labelWidth,
          height: 18,
          rx: 9,
        }));

        const name = svg("text", { class: "room-name", x: 14, y: 20 });
        name.textContent = roomLabel;
        group.appendChild(name);

        const kind = svg("text", { class: "room-kind", x: 14, y: 33 });
        kind.textContent = displayRoomKind(room);
        group.appendChild(kind);

        const tokens = [];
        if (room.characters.length) tokens.push(["character", room.characters.map(displayCharacterName).join(" ")]);
        if (known && room.intruders.length) tokens.push(["intruder", room.intruders.map((item) => `I${item.id}:${item.kind}`).join(" ")]);
        if (known && room.noise_corridors.length) tokens.push(["noise", `N${room.noise_corridors.join(",")}`]);
        if (known && room.engine) {
          const engineLabel = godMode || room.engine.checked
            ? (room.engine.working ? "ENG ok" : "ENG damaged")
            : "ENG unknown";
          tokens.push(["system", engineLabel]);
        }
        if (known && room.escape_pod) tokens.push(["system", room.escape_pod.unlocked ? "POD open" : "POD locked"]);
        tokens.slice(0, 3).forEach((token, index) => {
          const y = 47 + index * 8;
          const bg = svg("rect", {
            class: `pill-bg ${token[0]}`,
            x: 13,
            y: y - 7,
            width: roomWidth - 26,
            height: 9,
            rx: 5,
          });
          const text = svg("text", { class: "token-pill", x: 18, y: y });
          text.textContent = token[1];
          group.appendChild(bg);
          group.appendChild(text);
        });

        map.appendChild(group);
      }
    }

    function renderStats(frame) {
      const grid = document.getElementById("stateGrid");
      clear(grid);
      const ship = frame.global.ship;
      const knownDamagedEngines = Object.values(ship.engines).filter((engine) => engine.checked && !engine.working).length;
      const stateGroups = [
        [
          "Turn",
          [
            ["Phase", frame.phase],
            ["Step", `${frame.step}`],
            ["Time", `${ship.time_remaining}`],
          ],
        ],
        [
          "Navigation",
          [
            ["Destination", godMode || ship.coordinates_known ? ship.destination : "unknown"],
            ["Coordinates", ship.coordinates_known ? "known" : "unknown"],
          ],
        ],
        [
          "Ship",
          [
            ["Damaged", godMode ? `${ship.damaged_engines}` : `${knownDamagedEngines} known`],
            ["Hibernation", ship.hibernation_open ? "open" : "closed"],
            ["Self destruct", ship.self_destruct === null ? "inactive" : `${ship.self_destruct}`],
          ],
        ],
      ];
      for (const [groupTitle, stats] of stateGroups) {
        const group = el("div", "state-group");
        group.appendChild(el("h3", "", groupTitle));
        const pairs = el("div", "state-pairs");
        for (const [label, value] of stats) {
          const stat = el("div", "state-pair");
          stat.appendChild(el("span", "", label));
          stat.appendChild(el("strong", "", titleCase(value)));
          pairs.appendChild(stat);
        }
        group.appendChild(pairs);
        grid.appendChild(group);
      }

      const reason = document.getElementById("finishedReason");
      reason.textContent = frame.global.finished_reason ? titleCase(frame.global.finished_reason) : "running";
      reason.className = frame.done ? "chip warn" : "chip good";

      const engines = document.getElementById("engineList");
      clear(engines);
      for (const engine of Object.values(ship.engines)) {
        const engineRoom = frame.global.rooms[engine.room_id];
        const engineRoomKnown = engineRoom ? roomKnown(engineRoom) : godMode;
        const engineState = engineRoomKnown && (godMode || engine.checked) ? (engine.working ? "working" : "damaged") : "unknown";
        const row = el("div", "engine-chip");
        row.appendChild(el("b", "", engineRoomKnown ? `${engine.id} in ${shortRoom(engine.room_id)}` : "Unknown engine bay"));
        row.appendChild(el("span", "", `${engineState} / ${engineRoomKnown && engine.checked ? "checked" : "unchecked"}`));
        engines.appendChild(row);
      }

      const systems = document.getElementById("systemList");
      clear(systems);
      const bag = Object.entries(frame.global.intruder_bag_counts).map(([kind, count]) => `${kind}:${count}`).join(" ");
      const hazards = [
        ["Noise", frame.global.noise_markers.map((item) => `${item.room_id}:${item.corridor}`).join(", ") || "none"],
        ["Fire", frame.global.fire_rooms.join(", ") || "none"],
        ["Malfunction", frame.global.malfunction_rooms.join(", ") || "none"],
        ["Intruder bag", godMode ? (bag || "empty") : "hidden"],
        ["Weaknesses", `${frame.global.discovered_weaknesses}`],
        ["Nest eggs", `${frame.global.nest_eggs}`],
      ];
      for (const [label, value] of hazards) {
        const row = el("div", "system-chip");
        row.appendChild(el("b", "", label));
        row.appendChild(el("span", "", value));
        systems.appendChild(row);
      }
    }

    function renderCogLaunchers(frame) {
      clear(cogLaunchers);
      const isGlobalViewer = selectedAgentId === null || selectedAgentId === undefined;
      if (!isGlobalViewer || !playerUrls.length) {
        cogLaunchers.hidden = true;
        return;
      }

      cogLaunchers.hidden = false;
      for (const player of frame.players) {
        const connection = playerConnection(frame, player.id);
        const playerName = displayCharacterName(player);
        const classes = ["cog-launcher"];
        if (connection.connected) classes.push("connected");
        if (player.has_turn_token) classes.push("active-turn");

        const button = el("a", classes.join(" "));
        button.href = playerUrls[player.id] || "#";
        button.target = "_blank";
        button.rel = "noopener";
        button.setAttribute("role", "button");
        button.setAttribute("aria-label", `Open ${playerName} agent client`);
        button.dataset.playerId = String(player.id);
        button.dataset.playerUrl = playerUrls[player.id] || "";
        const lastSeen = connection.last_seen_seconds === null ? "never seen" : `${connection.last_seen_seconds}s ago`;
        button.title = `Open ${playerName} agent client in a new window / ${connection.connected ? "connected" : "disconnected"} / ${lastSeen}`;
        button.addEventListener("click", (event) => {
          const url = button.dataset.playerUrl;
          if (!url) return;
          const opened = window.open(url, `cogisis-cog-${player.id}`, "popup=yes,width=1180,height=920");
          if (opened) {
            opened.opener = null;
            event.preventDefault();
          }
        });

        const dot = el("span", connection.connected ? "connection-dot connected" : "connection-dot");
        dot.setAttribute("aria-hidden", "true");
        button.appendChild(dot);
        button.appendChild(el("span", "", playerName));
        cogLaunchers.appendChild(button);
      }
    }

    function renderNameControl(player, body) {
      if (!playerAuth || !ownsPlayer(player)) {
        return;
      }
      body.appendChild(el("div", "section-label", "Name"));
      const form = el("form", "name-form");
      form.dataset.playerId = String(player.id);
      const input = document.createElement("input");
      input.className = "name-input";
      input.type = "text";
      input.name = "display_name";
      input.maxLength = 32;
      input.autocomplete = "nickname";
      input.value = player.observation.self.name || "";
      input.placeholder = displayCharacterName(player);
      input.disabled = pendingAction !== null;
      const button = el("button", "action-button", "Set name");
      button.type = "submit";
      button.disabled = pendingAction !== null;
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitAction(`set-name:${input.value.trim()}`);
      });
      form.appendChild(input);
      form.appendChild(button);
      body.appendChild(form);
    }

    function paymentCost(item) {
      return Number(item.cost || 0);
    }

    function discardCost(item) {
      if (!item) return 0;
      if (item.discardCost !== undefined) return Number(item.discardCost || 0);
      if (item.discard_cost !== undefined) return Number(item.discard_cost || 0);
      return paymentCost(item);
    }

    function playCardIds(item) {
      if (!item) return [];
      if (Array.isArray(item.playCardIds)) return item.playCardIds;
      if (item.playCardId) return [item.playCardId];
      if (item.play_card_id) return [item.play_card_id];
      return [];
    }

    function playCardName(item) {
      return item.playCardName || item.play_card_name || "";
    }

    function costDetail(item) {
      const totalCost = paymentCost(item);
      const extraDiscards = discardCost(item);
      const cardName = playCardName(item);
      if (totalCost <= 0) {
        return "free";
      }
      if (cardName && extraDiscards <= 0) {
        return `${cardName} card`;
      }
      if (cardName) {
        return `${cardName} + ${extraDiscards} discard${extraDiscards === 1 ? "" : "s"}`;
      }
      return `${totalCost} card${totalCost === 1 ? "" : "s"}`;
    }

    function chooseActionForPayment(item) {
      selectedPaymentAction = {
        action: item.action,
        label: item.label,
        cost: paymentCost(item),
        discardCost: discardCost(item),
        playCardId: item.play_card_id || item.playCardId || null,
        playCardName: playCardName(item),
      };
      selectedDiscardCards = new Set();
      openChoiceId = null;
      render();
    }

    function handleActionSelection(item) {
      const totalCost = paymentCost(item);
      const extraDiscards = discardCost(item);
      if (totalCost <= 0 || extraDiscards <= 0) {
        submitAction(item.action, playCardIds(item));
        return;
      }
      chooseActionForPayment(item);
    }

    function renderCardHand(player, panel) {
      const hand = player.observation.self.action_hand || [];
      panel.appendChild(el("div", "section-label", "Action cards"));
      if (!hand.length) {
        panel.appendChild(el("div", "action-status", "No cards in hand."));
        return;
      }
      const cardGrid = el("div", "card-hand");
      const playedCards = new Set(playCardIds(selectedPaymentAction));
      const requiredDiscards = discardCost(selectedPaymentAction);
      for (const card of hand) {
        const played = playedCards.has(card.id);
        const selected = selectedDiscardCards.has(card.id);
        const cardButton = el("button", played || selected ? "action-card selected" : "action-card");
        cardButton.type = "button";
        cardButton.disabled = pendingAction !== null || !selectedPaymentAction || played;
        cardButton.setAttribute("aria-pressed", played || selected ? "true" : "false");
        cardButton.dataset.cardId = card.id;
        cardButton.appendChild(el("b", "", card.name));
        cardButton.appendChild(el("span", "", card.id));
        const indicator = played ? "Played" : (selected ? "Selected" : (selectedPaymentAction ? "Click to discard" : "Choose action first"));
        cardButton.appendChild(el("span", "selected-indicator", indicator));
        cardButton.addEventListener("click", () => {
          if (!selectedPaymentAction || played) {
            return;
          }
          if (selectedDiscardCards.has(card.id)) {
            selectedDiscardCards.delete(card.id);
          } else if (selectedDiscardCards.size < requiredDiscards) {
            selectedDiscardCards.add(card.id);
          }
          render();
        });
        cardGrid.appendChild(cardButton);
      }
      panel.appendChild(cardGrid);
    }

    function renderPaymentPanel(player, panel) {
      if (!selectedPaymentAction || !ownsPlayer(player)) {
        return;
      }
      const requiredDiscards = discardCost(selectedPaymentAction);
      if (requiredDiscards <= 0) {
        return;
      }
      const payment = el("div", "payment-panel");
      const played = playCardName(selectedPaymentAction)
        ? `Playing ${playCardName(selectedPaymentAction)}. `
        : "";
      payment.appendChild(
        el(
          "div",
          "action-status",
          `${played}${selectedPaymentAction.label} needs ${requiredDiscards} extra discard${requiredDiscards === 1 ? "" : "s"}.`,
        ),
      );
      const selectedCards = Array.from(selectedDiscardCards);
      const submit = el(
        "button",
        "action-button",
        `Discard ${selectedCards.length}/${requiredDiscards}`,
      );
      submit.type = "button";
      submit.disabled = pendingAction !== null || selectedCards.length !== requiredDiscards;
      submit.addEventListener("click", () => submitAction(selectedPaymentAction.action, [...playCardIds(selectedPaymentAction), ...selectedCards]));
      const cancel = el("button", "action-button", "Cancel");
      cancel.type = "button";
      cancel.disabled = pendingAction !== null;
      cancel.addEventListener("click", () => {
        selectedPaymentAction = null;
        selectedDiscardCards = new Set();
        render();
      });
      const buttons = el("div", "action-buttons");
      buttons.appendChild(submit);
      buttons.appendChild(cancel);
      payment.appendChild(buttons);
      panel.appendChild(payment);
    }

    function renderActionControls(player, body, frame) {
      body.appendChild(el("div", "section-label", "Turn actions"));
      const panel = el("div", "action-panel");
      const options = player.action_options || [];
      const canSubmit = Boolean(playerAuth && ownsPlayer(player) && player.has_turn_token && !frame.done);

      if (!canSubmit) {
        const chips = el("div", "chips");
        const labels = options.length
          ? options.map((option) => option.label)
          : (player.available_actions || []);
        for (const label of labels.slice(0, 14)) {
          chips.appendChild(el("span", player.has_turn_token ? "chip good" : "chip", label));
        }
        if (labels.length > 14) {
          chips.appendChild(el("span", "chip", `+${labels.length - 14}`));
        }
        panel.appendChild(chips);

        if (playerAuth && ownsPlayer(player)) {
          const text = frame.done ? "Game finished" : `Waiting for ${frame.turn_token.label}`;
          panel.appendChild(el("div", "action-status", text));
        } else if (!playerAuth) {
          panel.appendChild(el("div", "action-status", "Open a player client to submit actions."));
        }
      } else {
        renderPaymentPanel(player, panel);
        renderCardHand(player, panel);
        panel.appendChild(
          el(
            "div",
            "action-status",
            `${player.actions_remaining} action${player.actions_remaining === 1 ? "" : "s"} left this turn`,
          ),
        );
        const actions = el("div", "action-buttons");
        for (const option of options) {
          const button = el(
            "button",
            option.id === openChoiceId ? "action-button open" : "action-button",
            option.label,
          );
          button.type = "button";
          button.disabled = pendingAction !== null;
          button.appendChild(el("span", "choice-detail", costDetail(option)));
          if (option.action) {
            button.dataset.action = option.action;
            button.addEventListener("click", () => handleActionSelection(option));
          } else {
            button.dataset.optionId = option.id;
            button.addEventListener("click", () => {
              openChoiceId = openChoiceId === option.id ? null : option.id;
              render();
            });
          }
          actions.appendChild(button);
        }
        panel.appendChild(actions);

        const openOption = options.find((option) => option.id === openChoiceId && option.choices);
        if (openOption) {
          const choices = el("div", "choice-panel");
          choices.appendChild(el("div", "section-label", openOption.choice_label || "Choose"));
          const grid = el("div", "choice-grid");
          for (const choice of openOption.choices || []) {
            const button = el("button", "action-button", choice.label);
            button.type = "button";
            button.disabled = pendingAction !== null;
            button.dataset.action = choice.action;
            const detail = choice.detail ? `${choice.detail} / ` : "";
            button.appendChild(el("span", "choice-detail", `${detail}${costDetail(choice)}`));
            button.addEventListener("click", () => handleActionSelection(choice));
            grid.appendChild(button);
          }
          choices.appendChild(grid);
          panel.appendChild(choices);
        }
      }

      if (playerAuth && ownsPlayer(player) && actionMessage) {
        panel.appendChild(el("div", actionMessageKind === "error" ? "action-status error" : "action-status", actionMessage));
      }
      body.appendChild(panel);
    }

    function renderPlayers(frame) {
      const players = document.getElementById("players");
      clear(players);
      const visiblePlayers = selectedAgentId === null || selectedAgentId === undefined
        ? frame.players
        : frame.players.filter((player) => player.id === selectedAgentId);
      document.getElementById("playerCount").textContent = `${visiblePlayers.length} / ${frame.players.length} cogs`;
      for (const player of visiblePlayers) {
        const self = player.observation.self;
        const room = player.observation.room;
        const playerName = displayCharacterName(player);
        const card = el("article", player.has_turn_token ? "player-card active-token" : "player-card");
        const top = el("div", "player-top");
        const title = el("div");
        title.appendChild(el("h3", "", `${playerName} / ${titleCase(self.role)}`));
        title.appendChild(el("div", "player-meta", `${titleCase(self.status)} in ${displayRoomName(room)}`));
        top.appendChild(title);
        const token = player.has_turn_token
          ? `${player.actions_remaining} action${player.actions_remaining === 1 ? "" : "s"} left`
          : player.turn_position ? `queue ${player.turn_position}` : "waiting";
        top.appendChild(el("span", player.has_turn_token ? "chip good" : "chip", token));
        card.appendChild(top);

        const body = el("div", "player-body");
        const grid = el("div", "mini-grid");
        const values = [
          ["Light", self.light_wounds],
          ["Serious", self.serious_wounds],
          ["Contam", self.contamination],
          ["Ammo", self.ammo],
          ["Slime", self.slime ? "yes" : "no"],
          ["Signal", self.signal_sent ? "sent" : "no"],
        ];
        for (const [label, value] of values) {
          const mini = el("div", "mini");
          mini.appendChild(el("span", "", label));
          mini.appendChild(document.createTextNode(String(value)));
          grid.appendChild(mini);
        }
        body.appendChild(grid);

        renderNameControl(player, body);

        body.appendChild(el("div", "section-label", "Visible room"));
        const visible = el("div", "chips");
        visible.appendChild(el("span", "chip good", displayRoomName(room)));
        for (const [corridor, neighbor] of Object.entries(player.observation.neighbors)) {
          visible.appendChild(el("span", "chip", `${corridor}:${displayNeighborName(corridor, neighbor)}`));
        }
        if (player.observation.intruders_here.length) {
          for (const intruder of player.observation.intruders_here) {
            visible.appendChild(el("span", "chip bad", `${intruder.kind} ${intruder.damage}/${intruder.health}`));
          }
        }
        for (const marker of player.observation.noise_markers) {
          visible.appendChild(el("span", "chip warn", `noise ${marker.corridor}`));
        }
        body.appendChild(visible);

        const revealPrivate = canRevealPrivate(player);
        body.appendChild(el("div", "section-label", revealPrivate ? "Private objectives" : "Hidden private info"));
        if (revealPrivate) {
          const objectives = el("div", "chips");
          for (const objective of self.objectives) {
            objectives.appendChild(el("span", "chip", formatObjective(objective, frame)));
          }
          if (self.chosen_objective) {
            objectives.appendChild(el("span", "chip good", `chosen ${formatObjective(self.chosen_objective, frame)}`));
          }
          if (!self.objectives.length && !self.chosen_objective) {
            objectives.appendChild(el("span", "chip", "none"));
          }
          body.appendChild(objectives);

          body.appendChild(el("div", "section-label", "Inventory"));
          const inventory = el("div", "chips");
          for (const item of self.items || []) {
            inventory.appendChild(el("span", "chip", titleCase(item)));
          }
          if (!(self.items || []).length) {
            inventory.appendChild(el("span", "chip", "empty"));
          }
          body.appendChild(inventory);
        } else {
          body.appendChild(el("div", "private-hidden", "Objectives, chosen objective, and inventory are hidden in this view."));
        }

        renderActionControls(player, body, frame);

        card.appendChild(body);
        players.appendChild(card);
      }
    }

    function renderEvents(frame) {
      const events = document.getElementById("events");
      clear(events);
      document.getElementById("eventCount").textContent = `${frame.events.length} events`;
      if (!frame.events.length) {
        events.appendChild(el("div", "event-line", "initial frame"));
        return;
      }
      for (const event of frame.events) {
        events.appendChild(el("div", "event-line", JSON.stringify(event)));
      }
    }

    function render() {
      const frame = frames[currentFrame];
      if (!frame) {
        return;
      }
      const focusedNameDraft = captureFocusedNameDraft();
      drawMap(frame);
      renderStats(frame);
      renderCogLaunchers(frame);
      renderPlayers(frame);
      restoreFocusedNameDraft(focusedNameDraft);
      renderEvents(frame);
      if (selectedAgentId !== null && selectedAgentId !== undefined) {
        const player = (frame.players || []).find((item) => item.id === selectedAgentId);
        if (player) {
          document.getElementById("clientTitle").textContent = `${displayCharacterName(player)} client`;
        }
      }
      turnToken.textContent = frame.turn_token.label;
      slider.value = String(currentFrame);
      slider.max = String(Math.max(0, frames.length - 1));
      if (liveEndpoint) {
        frameCount.textContent = "live";
        prevButton.disabled = true;
        playButton.disabled = true;
        nextButton.disabled = true;
        slider.disabled = true;
        playButton.textContent = "Live";
      } else {
        frameCount.textContent = `${currentFrame + 1} / ${frames.length}`;
        prevButton.disabled = currentFrame === 0;
        playButton.disabled = false;
        nextButton.disabled = currentFrame >= frames.length - 1;
        slider.disabled = false;
      }
    }

    function setFrame(nextFrame) {
      currentFrame = Math.max(0, Math.min(frames.length - 1, nextFrame));
      render();
    }

    function stopPlayback() {
      if (playTimer) {
        clearInterval(playTimer);
        playTimer = null;
      }
      playButton.textContent = "Play";
    }

    prevButton.addEventListener("click", () => {
      stopPlayback();
      setFrame(currentFrame - 1);
    });
    nextButton.addEventListener("click", () => {
      stopPlayback();
      setFrame(currentFrame + 1);
    });
    slider.addEventListener("input", () => {
      stopPlayback();
      setFrame(Number(slider.value));
    });
    playButton.addEventListener("click", () => {
      if (liveEndpoint) {
        return;
      }
      if (playTimer) {
        stopPlayback();
        return;
      }
      playButton.textContent = "Pause";
      playTimer = setInterval(() => {
        if (currentFrame >= frames.length - 1) {
          stopPlayback();
          return;
        }
        setFrame(currentFrame + 1);
      }, 750);
    });
    if (revealButton) {
      revealButton.addEventListener("click", () => {
        setGodMode(!godMode);
      });
    }

    async function refreshLiveFrame() {
      if (!liveEndpoint || pendingAction || selectedPaymentAction) {
        return;
      }
      let response;
      try {
        response = await fetch(liveEndpoint, { cache: "no-store" });
      } catch {
        return;
      }
      if (!response.ok) {
        return;
      }
      const frame = await response.json();
      frames = [frame];
      currentFrame = 0;
      render();
    }

    if (liveEndpoint) {
      setInterval(refreshLiveFrame, 800);
      refreshLiveFrame();
    }

    render();
  </script>
</body>
</html>
"""
