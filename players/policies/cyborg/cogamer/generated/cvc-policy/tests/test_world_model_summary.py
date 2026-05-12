"""world_model_summary event emission at episode end."""

from __future__ import annotations

from cvc_policy.agent.world_model import WorldModel


def test_empty_world_model_summary() -> None:
    wm = WorldModel()
    s = wm.summary()
    assert s == {"known_entities": 0, "extractors_currently_known": 0}


def test_summary_schema_has_no_fake_reachable_cells() -> None:
    """Schema check: `reachable_cells` was a bogus placeholder; it must be gone.
    Also: old misleading names `known_cells` / `extractors_known` are renamed."""
    wm = WorldModel()
    s = wm.summary()
    assert set(s.keys()) == {"known_entities", "extractors_currently_known"}
    assert "reachable_cells" not in s
    assert "known_cells" not in s
    assert "extractors_known" not in s
    assert "frontier_cells" not in s
