"""Object-resolution tests: labels + id ranges -> entities (design §4)."""

from __future__ import annotations

from players.crewrift.crewborg.coworld.scene import SceneState
from players.crewrift.crewborg.perception.resolve import resolve_scene
from players.crewrift.crewborg.tests import sprite_wire as w


def _scene_with_camera() -> SceneState:
    scene = SceneState()
    # Map object at (-1000, -500) => camera (1000, 500).
    scene.apply(w.define_sprite(1, 1235, 659, "map") + w.define_object(1, -1000, -500, 0, 0, 1))
    return scene


def test_players_and_bodies_resolve_with_world_coords() -> None:
    scene = _scene_with_camera()
    scene.apply(
        w.define_sprite(1042, 10, 10, "player light blue right")
        + w.define_object(1042, 30, 40, 5, 0, 1042)  # world (1030, 540)
        + w.define_sprite(2003, 10, 10, "body green")
        + w.define_object(2003, -5, 8, 5, 0, 2003)  # world (995, 508)
    )
    resolved = resolve_scene(scene, tick=7)

    assert resolved.camera_ready
    assert len(resolved.visible_players) == 1
    player = resolved.visible_players[0]
    assert (player.color, player.facing) == ("light blue", "right")
    # Draw pos (1030, 540) + collision offset (3, 9) = the server's collision point.
    assert (player.world_x, player.world_y) == (1033, 549)

    assert len(resolved.visible_bodies) == 1
    body = resolved.visible_bodies[0]
    assert body.color == "green" and (body.world_x, body.world_y) == (998, 517)


def test_task_bubble_and_arrow_distinguished() -> None:
    scene = _scene_with_camera()
    scene.apply(
        w.define_sprite(500, 8, 8, "task bubble")
        + w.define_object(3002, 12, 12, 1, 0, 500)  # task index 2, on-screen bubble
        + w.define_sprite(501, 1, 1, "task arrow")
        + w.define_object(7005, 0, 64, 1, 0, 501)  # task index 5, off-screen arrow
    )
    resolved = resolve_scene(scene, tick=1)
    by_index = {t.task_index: t for t in resolved.task_signals}

    assert by_index[2].kind == "bubble" and by_index[2].world == (1012, 512)
    assert by_index[5].kind == "arrow" and by_index[5].world is None
    assert by_index[5].screen == (0, 64)


def test_self_role_from_hud_icons() -> None:
    scene = SceneState()
    scene.apply(w.define_sprite(900, 8, 8, "imposter icon cooldown") + w.define_object(900, 4, 4, 9, 0, 900))
    resolved = resolve_scene(scene, tick=1)
    assert resolved.self_role == "imposter" and resolved.self_kill_ready is False


def test_progress_counter_and_voting_resolved() -> None:
    scene = SceneState()
    scene.apply(
        w.define_sprite(910, 8, 8, "progress bar 45%")
        + w.define_object(910, 1, 1, 9, 0, 910)
        + w.define_sprite(911, 8, 8, "task counter 7")
        + w.define_object(911, 1, 1, 9, 0, 911)
        + w.define_sprite(920, 4, 4, "vote timer")
        + w.define_object(920, 1, 1, 9, 0, 920)
        + w.define_sprite(921, 4, 4, "vote dot red")
        # id 10100 + target(3)*16 + voter(2) = 10150
        + w.define_object(10150, 1, 1, 9, 0, 921)
    )
    resolved = resolve_scene(scene, tick=1)
    assert resolved.active_task_progress_pct == 45
    assert resolved.crew_tasks_remaining == 7
    assert resolved.voting.timer_present and resolved.voting.active
    assert resolved.voting.dots == (resolved.voting.dots[0],)
    dot = resolved.voting.dots[0]
    assert (dot.target, dot.voter) == (3, 2)


def test_skip_vote_dots_decode_as_skip_not_a_player_target() -> None:
    scene = SceneState()
    scene.apply(
        w.define_sprite(921, 4, 4, "vote dot red")
        # Skip vote from voter 2 uses the separate base 10400 + voter.
        + w.define_object(10402, 1, 1, 9, 0, 921)
        # A normal vote: voter 1 -> target 0 at 10100 + 0*16 + 1 = 10101.
        + w.define_object(10101, 1, 1, 9, 0, 921)
    )
    resolved = resolve_scene(scene, tick=1)
    by_voter = {d.voter: d for d in resolved.voting.dots}

    assert by_voter[2].is_skip and by_voter[2].target == -2
    assert not by_voter[1].is_skip and by_voter[1].target == 0
