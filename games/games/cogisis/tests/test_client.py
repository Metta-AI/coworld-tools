from cogisis.client import (
    ROOM_BOX_HEIGHT,
    ROOM_BOX_WIDTH,
    ROOM_LAYOUT,
    build_client_frames,
    client_frame,
    render_client_html,
)
from cogisis.engine import CogisisSimulator
from cogisis.mission import CogisisMission


def test_ship_room_layout_has_no_overlapping_room_boxes() -> None:
    boxes = {
        room_id: {
            "left": position["x"] - ROOM_BOX_WIDTH / 2,
            "right": position["x"] + ROOM_BOX_WIDTH / 2,
            "top": position["y"] - ROOM_BOX_HEIGHT / 2,
            "bottom": position["y"] + ROOM_BOX_HEIGHT / 2,
        }
        for room_id, position in ROOM_LAYOUT.items()
    }

    overlaps = []
    room_ids = sorted(boxes)
    for index, left_id in enumerate(room_ids):
        left = boxes[left_id]
        for right_id in room_ids[index + 1 :]:
            right = boxes[right_id]
            if (
                left["left"] < right["right"]
                and left["right"] > right["left"]
                and left["top"] < right["bottom"]
                and left["bottom"] > right["top"]
            ):
                overlaps.append((left_id, right_id))

    assert overlaps == []


def test_client_frame_separates_global_and_player_private_state() -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=2, max_steps=3, seed=5).build_world())
    sim.perform(0, "set-name:Ripley")

    frame = client_frame(sim)

    assert frame["turn_token"]["holder"] == 0
    assert frame["turn_token"]["label"] == "Ripley ready / 2 actions left"
    assert frame["layout"]["width"] == 1145
    assert "board_image" not in frame["layout"]
    assert frame["layout"]["rooms"]["atrium"]
    assert frame["global"]["rooms"]["atrium"]["explored"] is False
    assert frame["global"]["rooms"]["hibernatorium"]["explored"] is True
    assert frame["global"]["characters"][0]["display_name"] == "Ripley"
    assert frame["global"]["rooms"]["hibernatorium"]["characters"][0]["display_name"] == "Ripley"
    assert "objectives" not in frame["global"]["characters"][0]
    assert "chosen_objective" not in frame["global"]["characters"][0]
    assert frame["players"][0]["display_name"] == "Ripley"
    assert frame["players"][0]["observation"]["self"]["display_name"] == "Ripley"
    assert len(frame["players"][0]["observation"]["self"]["action_hand"]) == 5
    assert frame["players"][0]["observation"]["self"]["action_deck_count"] == 5
    assert frame["players"][0]["observation"]["self"]["objectives"]
    assert frame["players"][0]["has_turn_token"] is True
    assert frame["players"][1]["turn_position"] == 2
    assert frame["player_connections"] == [
        {"id": 0, "connected": False, "last_seen_seconds": None},
        {"id": 1, "connected": False, "last_seen_seconds": None},
    ]


def test_build_client_frames_records_global_map_and_events() -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=1, max_steps=2, seed=6).build_world())

    frames = build_client_frames(sim, "noop", seed=6)

    assert len(frames) == 3
    assert frames[-1]["done"] is True
    assert frames[-1]["global"]["ship"]["time_remaining"] == 0
    assert frames[-1]["events"]


def test_client_frame_includes_structured_turn_action_options() -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=1, max_steps=3, seed=8).build_world())
    character = sim.world.characters[0]
    character.action_hand = [
        {"id": "search_1", "name": "Search"},
        {"id": "move_1", "name": "Move"},
        {"id": "plan_1", "name": "Plan"},
    ]

    frame = client_frame(sim)
    player = frame["players"][0]
    options = {option["id"]: option for option in player["action_options"]}

    assert "pass" in options
    assert options["pass"]["cost"] == 0
    assert options["search"]["cost"] == 1
    assert options["search"]["play_card_id"] == "search_1"
    assert options["search"]["discard_cost"] == 0
    assert "move" in options
    assert {
        "label": "Unknown room via corridor 1",
        "detail": "Corridor 1",
        "action": "move:atrium",
        "cost": 1,
        "play_card_id": "move_1",
        "play_card_name": "Move",
        "discard_cost": 0,
    } in options["move"]["choices"]
    assert "move:atrium" in player["available_actions"]
    assert "cautious_move:atrium:1" in player["available_actions"]


def test_render_client_html_embeds_self_contained_surface() -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=1, max_steps=1, seed=7).build_world())
    frame = client_frame(sim)

    html = render_client_html(
        [frame],
        player_auth={"slot": 0, "token": "test-token"},
        player_urls=["http://127.0.0.1:9999/player?slot=0&token=test-token"],
    )

    assert "<svg id=\"shipMap\"" in html
    assert "drawGeneratedBoard" in html
    assert "board-slot" in html
    assert "corridor-core" in html
    assert "room-shape" in html
    assert 'svg("line"' not in html
    assert "class: \"edge\"" not in html
    assert "corridor-badge" not in html
    assert "state-group" in html
    assert "system-strip" in html
    assert "engine-strip" in html
    assert "Global ship state" in html
    assert "Player panels" in html
    assert "\"turn_token\"" in html
    assert "God Mode" in html
    assert "\"player_auth\"" in html
    assert "/player/action" in html
    assert "name-form" in html
    assert "set-name:" in html
    assert "displayCharacterName" in html
    assert "card-hand" in html
    assert "payment-panel" in html
    assert "selected-indicator" in html
    assert "pendingAction || selectedPaymentAction" in html
    assert "playCardIds" in html
    assert "discardCost" in html
    assert "selectedDiscardCards" in html
    assert "\"discard\"" in html
    assert "Hidden private info" in html
    assert "cogLaunchers" in html
    assert "connection-dot" in html
    assert "\"player_urls\"" in html
    assert "new window" in html
    assert "target = \"_blank\"" in html
    assert "window.open" in html
    assert "agent client" in html
    assert "iframe" not in html
    assert "player-popup" not in html


def test_render_client_html_preserves_focused_name_input_across_live_refresh() -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=1, max_steps=1, seed=7).build_world())
    frame = client_frame(sim)

    html = render_client_html(
        [frame],
        live_endpoint="/state.json?slot=0&token=test-token",
        selected_agent_id=0,
        player_auth={"slot": 0, "token": "test-token"},
    )

    assert "captureFocusedNameDraft" in html
    assert "restoreFocusedNameDraft" in html
    assert 'form.dataset.playerId = String(player.id)' in html
    assert 'input.name = "display_name"' in html
    assert "input.setSelectionRange" in html
    assert "restoreFocusedNameDraft(focusedNameDraft)" in html


def test_render_client_html_draws_noise_markers_in_corridors() -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=1, max_steps=1, seed=7).build_world())
    sim.world.noise_markers.add(("atrium", 1))
    frame = client_frame(sim)

    html = render_client_html([frame])

    assert "drawNoiseMarkers" in html
    assert "corridorNoisePosition" in html
    assert "noise-marker" in html
    assert "noise-marker-label" in html
    assert "frame.layout.edges" in html


def test_render_player_client_does_not_include_god_mode() -> None:
    sim = CogisisSimulator(CogisisMission(num_cogs=1, max_steps=1, seed=10).build_world())
    frame = client_frame(sim)

    html = render_client_html(
        [frame],
        title="Cogisis player 0",
        selected_agent_id=0,
        player_auth={"slot": 0, "token": "test-token"},
    )

    assert "Cogisis player 0" in html
    assert "God Mode" not in html
    assert "godModeButton" not in html
    assert "Toggle God Mode" not in html
