from __future__ import annotations

from pathlib import Path

from PIL import Image

import amongcogs
import mettagrid
from amongcogs.constants import (
    CORPSE_RESOURCE,
    EJECTED_RESOURCE,
    MEETING_ACTIVE_RESOURCE,
    MEETING_BALLOT_RESOURCE,
    MEETING_DISCUSSION_RESOURCE,
    MEETING_REPORTED_BODY_RESOURCE,
    MEETING_TOKEN_RESOURCE,
    ROLE_CREW,
    ROLE_IMPOSTOR,
    TASK_PROGRESS_RESOURCE,
    VENT_COOLDOWN_RESOURCE,
    VENT_STATION_NAMES,
    VOTED_RESOURCE,
    VOTE_IMPOSTOR_RESOURCE,
    VOTE_SKIP_RESOURCE,
    WIN_REWARD_RESOURCE,
)
from amongcogs.missions import AmongUsGame


def _mettascope_data_dir() -> Path:
    package_root = Path(mettagrid.__file__).resolve().parent
    amongcogs_root = Path(amongcogs.__file__).resolve().parent
    candidates = [
        amongcogs_root / "assets" / "mettascope" / "data",
        package_root / "nim" / "mettascope" / "data",
        package_root.parent.parent.parent / "nim" / "mettascope" / "data",
    ]
    for candidate in candidates:
        if (candidate / "amongus" / "agents" / "crewmate.e.png").exists():
            return candidate
    raise AssertionError(f"Could not find mettascope data dir from {package_root}")


def _make_env():
    return AmongUsGame.create(num_agents=12, max_steps=120).make_env()


def test_among_us_station_assets_have_object_minimap_and_profile_sprites() -> None:
    env = _make_env()
    render_assets = env.game.render.assets
    assert env.game.render.terrain_tile == "amongus/terrain/repeating.among_us.png"
    expected_stamp_assets = {
        "admin_station",
        "comms_station",
        "crew_station",
        "emergency_button",
        "impostor_station",
        "lights_station",
        "medbay_station",
        "security_station",
        "shields_station",
        "weapons_station",
        "wiring_station",
        "reactor_station",
        "navigation_station",
        "oxygen_station",
    }
    assert expected_stamp_assets.issubset(set(env.game.render.stamp_assets))

    mettascope_data = _mettascope_data_dir()
    mettascope_amongus_data = mettascope_data / "amongus"

    station_type_names = [
        "admin_station",
        "comms_station",
        "crew_station",
        "emergency_button",
        "impostor_station",
        "lights_station",
        "medbay_station",
        "security_station",
        "shields_station",
        "weapons_station",
        "wiring_station",
        "reactor_station",
        "navigation_station",
        "oxygen_station",
    ]

    for station_type in station_type_names:
        rules = render_assets.get(station_type, [])
        assert rules, f"Missing render asset mapping for {station_type}"
        asset_name = rules[0].asset
        assert asset_name, f"Empty render asset name for {station_type}"
        assert asset_name == station_type, (
            f"Render asset for {station_type} should be canonical '{station_type}', got '{asset_name}'"
        )

        assert (mettascope_amongus_data / "objects" / f"{asset_name}.png").exists(), (
            f"Missing objects sprite for {station_type}: {asset_name}.png"
        )
        assert (mettascope_amongus_data / "minimap" / f"{asset_name}.png").exists(), (
            f"Missing minimap sprite for {station_type}: {asset_name}.png"
        )
        assert (mettascope_amongus_data / "profiles" / f"{asset_name}.png").exists(), (
            f"Missing profile sprite for {station_type}: {asset_name}.png"
        )

        assert (mettascope_amongus_data / "objects" / f"{station_type}.png").exists(), (
            f"Missing objects fallback sprite for {station_type}: {station_type}.png"
        )
        assert (mettascope_amongus_data / "minimap" / f"{station_type}.png").exists(), (
            f"Missing minimap fallback sprite for {station_type}: {station_type}.png"
        )
        assert (mettascope_amongus_data / "profiles" / f"{station_type}.png").exists(), (
            f"Missing profile fallback sprite for {station_type}: {station_type}.png"
        )
        assert not (mettascope_data / "objects" / f"{station_type}.png").exists(), (
            f"Station object sprite should be namespaced under data/amongus: {station_type}.png"
        )
        assert not (mettascope_data / "minimap" / f"{station_type}.png").exists(), (
            f"Station minimap sprite should be namespaced under data/amongus: {station_type}.png"
        )
        assert not (mettascope_data / "profiles" / f"{station_type}.png").exists(), (
            f"Station profile sprite should be namespaced under data/amongus: {station_type}.png"
        )


def test_among_us_agents_use_role_specific_sprites() -> None:
    env = _make_env()
    agent_rules = env.game.render.assets["agent"]
    expected_state_rules = [
        ("ejected_impostor", {EJECTED_RESOURCE: 1, ROLE_IMPOSTOR: 1}),
        ("body_impostor", {CORPSE_RESOURCE: 1, ROLE_IMPOSTOR: 1}),
        ("vote_impostor_impostor", {VOTE_IMPOSTOR_RESOURCE: 1, ROLE_IMPOSTOR: 1}),
        ("vote_skip_impostor", {VOTE_SKIP_RESOURCE: 1, ROLE_IMPOSTOR: 1}),
        ("ballot_impostor", {MEETING_BALLOT_RESOURCE: 1, ROLE_IMPOSTOR: 1}),
        ("discussion_impostor", {MEETING_DISCUSSION_RESOURCE: 1, ROLE_IMPOSTOR: 1}),
        ("ejected_crewmate", {EJECTED_RESOURCE: 1, ROLE_CREW: 1}),
        ("body_crewmate", {CORPSE_RESOURCE: 1, ROLE_CREW: 1}),
        ("vote_impostor_crewmate", {VOTE_IMPOSTOR_RESOURCE: 1, ROLE_CREW: 1}),
        ("vote_skip_crewmate", {VOTE_SKIP_RESOURCE: 1, ROLE_CREW: 1}),
        ("ballot_crewmate", {MEETING_BALLOT_RESOURCE: 1, ROLE_CREW: 1}),
        ("discussion_crewmate", {MEETING_DISCUSSION_RESOURCE: 1, ROLE_CREW: 1}),
    ]
    assert [(rule.asset, rule.resources) for rule in agent_rules[:12]] == expected_state_rules
    assert agent_rules[12].asset == "impostor"
    assert agent_rules[12].resources == {ROLE_IMPOSTOR: 1}
    assert agent_rules[13].asset == "crewmate"
    assert agent_rules[13].resources == {ROLE_CREW: 1}

    mettascope_amongus_data = _mettascope_data_dir() / "amongus"
    directions = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
    agent_asset_names = ("crewmate", "impostor", *(asset_name for asset_name, _ in expected_state_rules))
    for role in agent_asset_names:
        for direction in directions:
            sprite = mettascope_amongus_data / "agents" / f"{role}.{direction}.png"
            assert sprite.exists()
            with Image.open(sprite) as image:
                assert image.size == (192, 192)
        with Image.open(mettascope_amongus_data / "profiles" / f"{role}.png") as image:
            assert image.size == (169, 219)
        with Image.open(mettascope_amongus_data / "minimap" / f"{role}.png") as image:
            assert image.size == (33, 33)


def test_among_us_meeting_vote_state_is_visible_in_render_config() -> None:
    env = _make_env()
    agent_status = env.game.render.object_status["agent"]
    expected_statuses = {
        TASK_PROGRESS_RESOURCE: "PROG",
        MEETING_ACTIVE_RESOURCE: "MTG",
        MEETING_DISCUSSION_RESOURCE: "TALK",
        MEETING_BALLOT_RESOURCE: "BAL",
        MEETING_REPORTED_BODY_RESOURCE: "BODY",
        VOTED_RESOURCE: "VTD",
        VOTE_IMPOSTOR_RESOURCE: "ACC",
        VOTE_SKIP_RESOURCE: "SKIP",
        EJECTED_RESOURCE: "OUT",
        WIN_REWARD_RESOURCE: "WIN",
        MEETING_TOKEN_RESOURCE: "BTN",
        VENT_COOLDOWN_RESOURCE: "VENT",
    }
    for resource_name, short_name in expected_statuses.items():
        assert agent_status[resource_name].short_name == short_name


def test_among_us_assets_are_reasonably_sized_like_cogsguard_assets() -> None:
    mettascope_data = _mettascope_data_dir()
    mettascope_amongus_data = mettascope_data / "amongus"

    budgets = {
        "agents": {"dim": (192, 192), "max_bytes": 12_000},
        "objects": {"dim": (64, 64), "max_bytes": 12_000},
        "minimap": {"dim": (33, 33), "max_bytes": 2_500},
        "profiles": {"dim": (169, 219), "max_bytes": 15_000},
        "terrain": {"dim": (256, 256), "max_bytes": 100_000},
    }

    for group, cfg in budgets.items():
        pngs = sorted((mettascope_amongus_data / group).glob("*.png"))
        assert pngs, f"No Among Us {group} assets found"
        for png in pngs:
            with Image.open(png) as image:
                assert image.size == cfg["dim"], (
                    f"Unexpected {group} dimensions for {png.name}: {image.size}, expected {cfg['dim']}"
                )
            assert png.stat().st_size <= cfg["max_bytes"], (
                f"{png.name} is too large for {group}: {png.stat().st_size} > {cfg['max_bytes']}"
            )


def test_among_us_vent_assets_have_render_and_alias_sprites() -> None:
    env = _make_env()
    mettascope_amongus_data = _mettascope_data_dir() / "amongus"

    for vent_name in VENT_STATION_NAMES:
        rules = env.game.render.assets.get(vent_name, [])
        assert rules and rules[0].asset == "vent"
        for asset_name in ("vent", vent_name):
            assert (mettascope_amongus_data / "objects" / f"{asset_name}.png").exists()
            assert (mettascope_amongus_data / "minimap" / f"{asset_name}.png").exists()
            assert (mettascope_amongus_data / "profiles" / f"{asset_name}.png").exists()

    assert (mettascope_amongus_data / "terrain" / "stamp.among_us_vent.png").exists()
