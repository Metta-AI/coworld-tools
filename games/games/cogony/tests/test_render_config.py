"""Validate render config: asset keys match entity types, sprites exist."""

from __future__ import annotations

import os

from cogony.cli import _mettascope_wasm_dir
from cogony.mission import CogonyMission

DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..",
    ".mettagrid", "nim",
    "mettascope", "data",
)


def _entity_type_names(cfg) -> set[str]:
    """All entity type names and map names that exist in the game config."""
    names = {"agent"}
    for key, obj in cfg.game.objects.items():
        names.add(obj.name)
        names.add(key)
    return names


def test_render_asset_keys_match_entity_types():
    """Every key in render.assets must match an entity type or map name."""
    cfg = CogonyMission().make_env()
    types = _entity_type_names(cfg)
    for key in cfg.game.render.assets:
        assert key in types, (
            f"render.assets key '{key}' doesn't match any entity type or map name. "
            f"Known: {sorted(t for t in types if ':' not in t)[:20]}"
        )


def test_scrambled_icon_exists():
    """Scrambled overhead icon must exist."""
    sprite = os.path.join(DATA_DIR, "icons", "scrambled.png")
    assert os.path.exists(sprite), f"scrambled icon missing at {sprite}"


def test_vibe_sprites_exist():
    """Every vibe must have a sprite in data/vibe/."""
    cfg = CogonyMission().make_env()
    vibe_dir = os.path.join(DATA_DIR, "vibe")
    for vibe in cfg.game.vibe_names:
        sprite = os.path.join(vibe_dir, vibe + ".png")
        assert os.path.exists(sprite), (
            f"vibe '{vibe}' has no sprite at {sprite}"
        )


def test_node_object_status_shows_only_coherence():
    """Node selection panels should not render subsystem bars."""
    cfg = CogonyMission().make_env()
    for obj_name in [
        "junction",
        "observatory",
        "datacenter",
        "carbon_extractor",
        "oxygen_extractor",
        "germanium_extractor",
        "silicon_extractor",
    ]:
        status = cfg.game.render.object_status[obj_name]
        assert list(status) == ["coherence"]


def test_cli_uses_repo_local_mettascope_wasm():
    """The web client should not depend on an external metta checkout."""
    wasm_dir = _mettascope_wasm_dir()
    assert wasm_dir is not None
    assert "metta.3" not in str(wasm_dir)
    assert wasm_dir.name == "dist"
