"""Unit tests for pure functions in cvc.agent.coglet_policy."""

from __future__ import annotations

from cvc_policy.agent.coglet_policy import _least_resource, _shared_resources


class TestSharedResources:
    """Tests for _shared_resources(state)."""

    def test_returns_shared_amounts_from_team_summary(self, make_state):
        state = make_state(shared_inventory={"carbon": 5, "oxygen": 20, "germanium": 3, "silicon": 8})
        result = _shared_resources(state)
        assert result == {"carbon": 5, "oxygen": 20, "germanium": 3, "silicon": 8}

    def test_uses_default_shared_inventory(self, make_state):
        # Default shared_inventory has 10 of each element
        state = make_state()
        result = _shared_resources(state)
        assert result == {"carbon": 10, "oxygen": 10, "germanium": 10, "silicon": 10}

    def test_no_team_summary_returns_zeros(self, make_state):
        state = make_state(team_summary=None)
        result = _shared_resources(state)
        assert result == {"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0}

    def test_only_includes_elements(self, make_state):
        # shared_inventory contains "heart" too, but _shared_resources should only
        # return the four elements
        state = make_state()
        result = _shared_resources(state)
        assert set(result.keys()) == {"carbon", "oxygen", "germanium", "silicon"}
        assert "heart" not in result

    def test_missing_element_in_shared_inventory_defaults_to_zero(self, make_state):
        from mettagrid.sdk.agent import TeamSummary

        # Build a team_summary with a shared_inventory that omits some elements
        ts = TeamSummary(
            team_id="team_0",
            members=[],
            shared_inventory={"carbon": 7},
        )
        state = make_state(team_summary=ts)
        result = _shared_resources(state)
        assert result["carbon"] == 7
        assert result["oxygen"] == 0
        assert result["germanium"] == 0
        assert result["silicon"] == 0

    def test_values_are_int_type(self, make_state):
        state = make_state(shared_inventory={"carbon": 3, "oxygen": 1, "germanium": 0, "silicon": 7})
        result = _shared_resources(state)
        assert all(isinstance(v, int) for v in result.values())
        assert result["carbon"] == 3
        assert result["oxygen"] == 1
        assert result["germanium"] == 0
        assert result["silicon"] == 7


class TestLeastResource:
    """Tests for _least_resource(resources)."""

    def test_returns_element_with_lowest_value(self):
        resources = {"carbon": 10, "oxygen": 5, "germanium": 20, "silicon": 15}
        assert _least_resource(resources) == "oxygen"

    def test_single_zero(self):
        resources = {"carbon": 10, "oxygen": 10, "germanium": 0, "silicon": 10}
        assert _least_resource(resources) == "germanium"

    def test_all_equal_returns_first_element(self):
        # When tied, min() returns the first element checked, which follows ELEMENTS order
        resources = {"carbon": 5, "oxygen": 5, "germanium": 5, "silicon": 5}
        assert _least_resource(resources) == "carbon"

    def test_tie_between_non_first_elements(self):
        # oxygen and silicon tied at 1, oxygen comes first in ELEMENTS
        resources = {"carbon": 10, "oxygen": 1, "germanium": 5, "silicon": 1}
        assert _least_resource(resources) == "oxygen"

    def test_tie_germanium_silicon(self):
        # germanium comes before silicon in ELEMENTS
        resources = {"carbon": 10, "oxygen": 10, "germanium": 2, "silicon": 2}
        assert _least_resource(resources) == "germanium"

    def test_all_zeros(self):
        resources = {"carbon": 0, "oxygen": 0, "germanium": 0, "silicon": 0}
        assert _least_resource(resources) == "carbon"

    def test_large_values(self):
        resources = {"carbon": 999, "oxygen": 1000, "germanium": 998, "silicon": 1001}
        assert _least_resource(resources) == "germanium"
