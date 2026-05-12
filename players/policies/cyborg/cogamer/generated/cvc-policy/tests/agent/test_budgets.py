"""Tests for cvc.agent.budgets – role assignment, pressure budgets, retreat, and metrics."""

from __future__ import annotations

from cvc_policy.agent.budgets import (
    _SCRAMBLER_PRIORITY,
    PressureMetrics,
    assign_role,
    compute_pressure_budgets,
    compute_pressure_metrics,
    compute_retreat_margin,
)
from cvc_policy.agent.types import JUNCTION_ALIGN_DISTANCE

# ---------------------------------------------------------------------------
# assign_role
# ---------------------------------------------------------------------------


class TestAssignRole:
    """Tests for assign_role(role_id, aligner_budget, scrambler_budget)."""

    def test_budget_4_1_scrambler(self):
        # scrambler_budget=1 → first from _SCRAMBLER_PRIORITY = (7,...)
        assert assign_role(7, aligner_budget=4, scrambler_budget=1) == "scrambler"

    def test_budget_4_1_aligner(self):
        # aligner_budget=4, skip scrambler id 7 → aligners from (4,5,6,3,...) = [4,5,6,3]
        assert assign_role(4, aligner_budget=4, scrambler_budget=1) == "aligner"

    def test_budget_4_1_miner(self):
        # role_id=0 is neither scrambler nor in first 4 aligners
        assert assign_role(0, aligner_budget=4, scrambler_budget=1) == "miner"

    def test_budget_0_0_all_miners(self):
        for role_id in range(8):
            assert assign_role(role_id, aligner_budget=0, scrambler_budget=0) == "miner"

    def test_budget_8_0_all_aligners(self):
        for role_id in range(8):
            assert assign_role(role_id, aligner_budget=8, scrambler_budget=0) == "aligner"

    def test_scrambler_ids_filled_first(self):
        # scrambler_budget=3 → ids (7, 6, 3) are scramblers
        for sid in _SCRAMBLER_PRIORITY[:3]:
            assert assign_role(sid, aligner_budget=5, scrambler_budget=3) == "scrambler"

    def test_aligner_skips_scrambler_ids(self):
        # With scrambler_budget=2 → scrambler ids {7, 6}
        # Aligners from priority (4,5,6,7,3,2,1,0), skipping 7 and 6 → [4,5,3,2,1]
        assert assign_role(6, aligner_budget=5, scrambler_budget=2) == "scrambler"
        assert assign_role(4, aligner_budget=5, scrambler_budget=2) == "aligner"
        assert assign_role(5, aligner_budget=5, scrambler_budget=2) == "aligner"
        assert assign_role(3, aligner_budget=5, scrambler_budget=2) == "aligner"
        assert assign_role(2, aligner_budget=5, scrambler_budget=2) == "aligner"
        assert assign_role(1, aligner_budget=5, scrambler_budget=2) == "aligner"
        assert assign_role(0, aligner_budget=5, scrambler_budget=2) == "miner"

    def test_large_scrambler_budget_takes_all(self):
        # scrambler_budget covers all scrambler priority slots
        for sid in _SCRAMBLER_PRIORITY:
            assert assign_role(sid, aligner_budget=2, scrambler_budget=6) == "scrambler"
        # Remaining ids (4, 5) should be aligners
        assert assign_role(4, aligner_budget=2, scrambler_budget=6) == "aligner"
        assert assign_role(5, aligner_budget=2, scrambler_budget=6) == "aligner"


# ---------------------------------------------------------------------------
# compute_pressure_budgets
# ---------------------------------------------------------------------------


class TestComputePressureBudgets:
    """Tests for compute_pressure_budgets(step, min_resource, can_refill_hearts, objective)."""

    def test_early_game_below_30(self):
        a, s = compute_pressure_budgets(step=10, min_resource=10, can_refill_hearts=True)
        assert a == 2
        assert s == 0

    def test_early_game_step_29(self):
        a, s = compute_pressure_budgets(step=29, min_resource=0, can_refill_hearts=False)
        assert a == 2
        assert s == 0

    def test_mid_game_normal(self):
        # step=500, min_resource=10, can_refill → budget=5, scrambler=1, aligner=4
        a, s = compute_pressure_budgets(step=500, min_resource=10, can_refill_hearts=True)
        assert a == 4
        assert s == 1

    def test_mid_game_low_resource(self):
        # min_resource=2 (<3) → budget=4, scrambler=1, aligner=3
        a, s = compute_pressure_budgets(step=500, min_resource=2, can_refill_hearts=True)
        assert a == 3
        assert s == 1

    def test_mid_game_very_low_no_hearts(self):
        # min_resource=0 (<1) and no hearts → budget=2, scrambler=1, aligner=1
        a, s = compute_pressure_budgets(step=500, min_resource=0, can_refill_hearts=False)
        assert a == 1
        assert s == 1

    def test_mid_game_very_low_with_hearts(self):
        # min_resource=0 but can_refill_hearts → falls to min_resource<3 branch → budget=4
        a, s = compute_pressure_budgets(step=500, min_resource=0, can_refill_hearts=True)
        assert a == 3
        assert s == 1

    def test_mid_game_no_scrambler_below_100(self):
        a, s = compute_pressure_budgets(step=50, min_resource=10, can_refill_hearts=True)
        assert s == 0
        assert a == 5

    def test_mid_game_scrambler_at_100(self):
        a, s = compute_pressure_budgets(step=100, min_resource=10, can_refill_hearts=True)
        assert s == 1

    def test_late_game_normal(self):
        # step=3000, budget=6, scrambler=1, aligner=5
        a, s = compute_pressure_budgets(step=3000, min_resource=10, can_refill_hearts=True)
        assert a == 5
        assert s == 1

    def test_late_game_very_low_no_hearts(self):
        # budget=3, scrambler=1, aligner=2
        a, s = compute_pressure_budgets(step=5000, min_resource=0, can_refill_hearts=False)
        assert a == 2
        assert s == 1

    def test_objective_resource_coverage(self):
        a, s = compute_pressure_budgets(
            step=500, min_resource=10, can_refill_hearts=True, objective="resource_coverage"
        )
        assert (a, s) == (0, 0)

    def test_objective_economy_bootstrap(self):
        # Normal mid-game would give aligner=4, but bootstrap caps at 2, scrambler=0
        a, s = compute_pressure_budgets(
            step=500, min_resource=10, can_refill_hearts=True, objective="economy_bootstrap"
        )
        assert a == 2
        assert s == 0

    def test_economy_bootstrap_low_budget(self):
        # step=10 → budget=2, scrambler=0, aligner=2 → min(2, 2) = 2
        a, s = compute_pressure_budgets(step=10, min_resource=10, can_refill_hearts=True, objective="economy_bootstrap")
        assert a == 2
        assert s == 0

    def test_economy_bootstrap_caps_at_2(self):
        # Late game: aligner=5 → min(5, 2) = 2
        a, s = compute_pressure_budgets(
            step=5000, min_resource=10, can_refill_hearts=True, objective="economy_bootstrap"
        )
        assert a == 2
        assert s == 0


# ---------------------------------------------------------------------------
# compute_retreat_margin
# ---------------------------------------------------------------------------


class TestComputeRetreatMargin:
    """Tests for compute_retreat_margin – returns True when hp <= safe_steps + margin."""

    _BASE = dict(
        in_enemy_aoe=False,
        near_enemy_territory=False,
        heart_count=0,
        resource_cargo=0,
        has_gear=True,
        late_game=False,
        role="miner",
    )

    def test_base_margin_should_retreat(self):
        # margin=15, hp=20, safe_steps=5 → 20 <= 5+15 → True
        assert compute_retreat_margin(hp=20, safe_steps=5, **self._BASE) is True

    def test_base_margin_should_not_retreat(self):
        # margin=15, hp=21, safe_steps=5 → 21 <= 20 → False
        assert compute_retreat_margin(hp=21, safe_steps=5, **self._BASE) is False

    def test_exact_boundary(self):
        # hp exactly equals safe_steps + margin
        assert compute_retreat_margin(hp=15, safe_steps=0, **self._BASE) is True

    def test_in_enemy_aoe_adds_10(self):
        # margin=15+10=25
        assert (
            compute_retreat_margin(
                hp=30,
                safe_steps=5,
                in_enemy_aoe=True,
                near_enemy_territory=False,
                heart_count=0,
                resource_cargo=0,
                has_gear=True,
                late_game=False,
                role="miner",
            )
            is True
        )  # 30 <= 5+25=30

    def test_near_enemy_territory_adds_5(self):
        # margin=15+5=20
        assert (
            compute_retreat_margin(
                hp=25,
                safe_steps=5,
                in_enemy_aoe=False,
                near_enemy_territory=True,
                heart_count=0,
                resource_cargo=0,
                has_gear=True,
                late_game=False,
                role="miner",
            )
            is True
        )  # 25 <= 5+20=25

    def test_aoe_takes_priority_over_territory(self):
        # Both true → only +10 (aoe), not +15
        result = compute_retreat_margin(
            hp=26,
            safe_steps=0,
            in_enemy_aoe=True,
            near_enemy_territory=True,
            heart_count=0,
            resource_cargo=0,
            has_gear=True,
            late_game=False,
            role="miner",
        )
        assert result is False  # margin=25, 26 <= 25 → False

    def test_heart_count_adds_per_heart(self):
        # margin=15 + 3*5=30
        assert (
            compute_retreat_margin(
                hp=30,
                safe_steps=0,
                heart_count=3,
                in_enemy_aoe=False,
                near_enemy_territory=False,
                resource_cargo=0,
                has_gear=True,
                late_game=False,
                role="miner",
            )
            is True
        )

    def test_resource_cargo_contribution(self):
        # min(10, 12)//2 = 5 → margin=15+5=20
        assert (
            compute_retreat_margin(
                hp=20,
                safe_steps=0,
                resource_cargo=10,
                in_enemy_aoe=False,
                near_enemy_territory=False,
                heart_count=0,
                has_gear=True,
                late_game=False,
                role="miner",
            )
            is True
        )

    def test_resource_cargo_capped_at_12(self):
        # min(100, 12)//2 = 6 → margin=15+6=21
        assert (
            compute_retreat_margin(
                hp=21,
                safe_steps=0,
                resource_cargo=100,
                in_enemy_aoe=False,
                near_enemy_territory=False,
                heart_count=0,
                has_gear=True,
                late_game=False,
                role="miner",
            )
            is True
        )
        assert (
            compute_retreat_margin(
                hp=22,
                safe_steps=0,
                resource_cargo=100,
                in_enemy_aoe=False,
                near_enemy_territory=False,
                heart_count=0,
                has_gear=True,
                late_game=False,
                role="miner",
            )
            is False
        )

    def test_no_gear_adds_10(self):
        # margin=15+10=25
        assert (
            compute_retreat_margin(
                hp=25,
                safe_steps=0,
                has_gear=False,
                in_enemy_aoe=False,
                near_enemy_territory=False,
                heart_count=0,
                resource_cargo=0,
                late_game=False,
                role="miner",
            )
            is True
        )

    def test_late_game_aligner_adds_10(self):
        # margin=15+10=25
        assert (
            compute_retreat_margin(
                hp=25,
                safe_steps=0,
                late_game=True,
                role="aligner",
                in_enemy_aoe=False,
                near_enemy_territory=False,
                heart_count=0,
                resource_cargo=0,
                has_gear=True,
            )
            is True
        )

    def test_late_game_scrambler_adds_10(self):
        assert (
            compute_retreat_margin(
                hp=25,
                safe_steps=0,
                late_game=True,
                role="scrambler",
                in_enemy_aoe=False,
                near_enemy_territory=False,
                heart_count=0,
                resource_cargo=0,
                has_gear=True,
            )
            is True
        )

    def test_late_game_miner_adds_5(self):
        # margin=15+5=20
        assert (
            compute_retreat_margin(
                hp=20,
                safe_steps=0,
                late_game=True,
                role="miner",
                in_enemy_aoe=False,
                near_enemy_territory=False,
                heart_count=0,
                resource_cargo=0,
                has_gear=True,
            )
            is True
        )
        assert (
            compute_retreat_margin(
                hp=21,
                safe_steps=0,
                late_game=True,
                role="miner",
                in_enemy_aoe=False,
                near_enemy_territory=False,
                heart_count=0,
                resource_cargo=0,
                has_gear=True,
            )
            is False
        )

    def test_all_modifiers_combined(self):
        # aoe=+10, hearts=2*5=10, cargo=min(12,12)//2=6, no_gear=+10, late+aligner=+10
        # margin = 15+10+10+6+10+10 = 61
        assert (
            compute_retreat_margin(
                hp=71,
                safe_steps=10,
                in_enemy_aoe=True,
                near_enemy_territory=True,
                heart_count=2,
                resource_cargo=12,
                has_gear=False,
                late_game=True,
                role="aligner",
            )
            is True
        )  # 71 <= 10+61=71
        assert (
            compute_retreat_margin(
                hp=72,
                safe_steps=10,
                in_enemy_aoe=True,
                near_enemy_territory=True,
                heart_count=2,
                resource_cargo=12,
                has_gear=False,
                late_game=True,
                role="aligner",
            )
            is False
        )


# ---------------------------------------------------------------------------
# compute_pressure_metrics
# ---------------------------------------------------------------------------


class TestComputePressureMetrics:
    """Tests for compute_pressure_metrics using make_entity fixture."""

    def test_empty_inputs(self, make_entity):
        m = compute_pressure_metrics(
            friendly_sources=[],
            neutral_junctions=[],
            enemy_junctions=[],
        )
        assert m == PressureMetrics(
            frontier_neutral_junctions=0,
            best_frontier_coverage=0,
            best_enemy_scramble_block=0,
        )

    def test_no_neutrals_near_friendly(self, make_entity):
        # Friendly source at (0, 0), neutral far away at (200, 200)
        source = make_entity(entity_type="junction", x=0, y=0, team="team_0")
        neutral = make_entity(entity_type="junction", x=200, y=200)
        m = compute_pressure_metrics(
            friendly_sources=[source],
            neutral_junctions=[neutral],
            enemy_junctions=[],
        )
        assert m.frontier_neutral_junctions == 0

    def test_frontier_junctions_within_align_distance(self, make_entity):
        # Friendly junction at (50, 50), neutral at (50, 50 + ALIGN_DIST) → within range
        source = make_entity(entity_type="junction", x=50, y=50, team="team_0")
        near = make_entity(x=50, y=50 + JUNCTION_ALIGN_DISTANCE)
        far = make_entity(x=50, y=50 + JUNCTION_ALIGN_DISTANCE + 1)
        m = compute_pressure_metrics(
            friendly_sources=[source],
            neutral_junctions=[near, far],
            enemy_junctions=[],
        )
        assert m.frontier_neutral_junctions == 1

    def test_hub_source_uses_larger_align_distance(self, make_entity):
        # Hub has HUB_ALIGN_DISTANCE=25, junction has 15
        hub = make_entity(entity_type="hub", x=50, y=50, team="team_0")
        # Distance 20: within hub range (25) but outside junction range (15)
        neutral = make_entity(x=50, y=70)
        m = compute_pressure_metrics(
            friendly_sources=[hub],
            neutral_junctions=[neutral],
            enemy_junctions=[],
        )
        assert m.frontier_neutral_junctions == 1

    def test_best_frontier_coverage(self, make_entity):
        # Source at origin, one frontier neutral at (10,0), two unreachable at (20,5) and (22,0)
        # Frontier neutral (10,0) covers unreachable within JUNCTION_ALIGN_DISTANCE of it
        source = make_entity(entity_type="junction", x=0, y=0, team="team_0")
        frontier = make_entity(x=10, y=0)  # dist 10 from source, within 15
        # unreachable neutrals far from source but near frontier
        make_entity(x=20, y=0)  # dist 20 from source (out), dist 10 from frontier (in)
        make_entity(x=10, y=14)  # dist 14 from source (in range!) -- actually frontier
        # Let's pick a truly unreachable one
        unreachable_far = make_entity(x=25, y=0)  # dist 25 from source (out), dist 15 from frontier (in)
        unreachable_far2 = make_entity(x=26, y=0)  # dist 26 from source (out), dist 16 from frontier (out)
        m = compute_pressure_metrics(
            friendly_sources=[source],
            neutral_junctions=[frontier, unreachable_far, unreachable_far2],
            enemy_junctions=[],
        )
        # frontier_junctions = [frontier] (dist 10 <= 15)
        # unreachable = [unreachable_far (dist 25 > 15), unreachable_far2 (dist 26 > 15)]
        # coverage of frontier: unreachable_far dist=15 (<=15 yes), unreachable_far2 dist=16 (>15 no) → 1
        assert m.frontier_neutral_junctions == 1
        assert m.best_frontier_coverage == 1

    def test_best_frontier_coverage_multiple_candidates(self, make_entity):
        source = make_entity(entity_type="junction", x=0, y=0, team="team_0")
        # Two frontier neutrals
        f1 = make_entity(x=5, y=0)  # frontier
        f2 = make_entity(x=10, y=0)  # frontier
        # Unreachable neutrals clustered near f2
        u1 = make_entity(x=20, y=0)  # dist 10 from f2, dist 15 from f1
        u2 = make_entity(x=22, y=0)  # dist 12 from f2, dist 17 from f1 (out for f1)
        u3 = make_entity(x=24, y=0)  # dist 14 from f2, dist 19 from f1 (out for f1)
        m = compute_pressure_metrics(
            friendly_sources=[source],
            neutral_junctions=[f1, f2, u1, u2, u3],
            enemy_junctions=[],
        )
        assert m.frontier_neutral_junctions == 2  # both f1, f2 within 15 of source
        # unreachable = [u1, u2, u3]
        # f1 covers: u1 (dist 15 <=15 yes), u2 (dist 17 no), u3 (dist 19 no) → 1
        # f2 covers: u1 (dist 10 yes), u2 (dist 12 yes), u3 (dist 14 yes) → 3
        assert m.best_frontier_coverage == 3

    def test_best_enemy_scramble_block(self, make_entity):
        source = make_entity(entity_type="junction", x=0, y=0, team="team_0")
        n1 = make_entity(x=100, y=100)
        n2 = make_entity(x=105, y=100)
        n3 = make_entity(x=120, y=100)
        enemy = make_entity(x=100, y=100, team="team_1")
        m = compute_pressure_metrics(
            friendly_sources=[source],
            neutral_junctions=[n1, n2, n3],
            enemy_junctions=[enemy],
        )
        # enemy at (100,100): n1 dist=0 (yes), n2 dist=5 (yes<=8), n3 dist=20 (no)
        assert m.best_enemy_scramble_block == 2

    def test_enemy_scramble_block_multiple_enemies(self, make_entity):
        n1 = make_entity(x=50, y=50)
        n2 = make_entity(x=55, y=50)
        n3 = make_entity(x=62, y=50)
        n4 = make_entity(x=67, y=50)
        enemy1 = make_entity(x=50, y=50, team="team_1")  # covers n1(0), n2(5) → 2
        enemy2 = make_entity(x=62, y=50, team="team_1")  # covers n2(7), n3(0), n4(5) → 3
        m = compute_pressure_metrics(
            friendly_sources=[],
            neutral_junctions=[n1, n2, n3, n4],
            enemy_junctions=[enemy1, enemy2],
        )
        assert m.best_enemy_scramble_block == 3

    def test_no_enemy_junctions(self, make_entity):
        source = make_entity(entity_type="junction", x=0, y=0, team="team_0")
        n1 = make_entity(x=5, y=0)
        m = compute_pressure_metrics(
            friendly_sources=[source],
            neutral_junctions=[n1],
            enemy_junctions=[],
        )
        assert m.best_enemy_scramble_block == 0

    def test_scramble_block_uses_all_neutrals_not_just_unreachable(self, make_entity):
        # Enemy scramble block counts over ALL neutral junctions, including frontier ones
        source = make_entity(entity_type="junction", x=0, y=0, team="team_0")
        n_frontier = make_entity(x=5, y=0)  # within align distance of source → frontier
        n_far = make_entity(x=200, y=200)  # unreachable
        # Enemy near frontier neutral
        enemy = make_entity(x=5, y=0, team="team_1")
        m = compute_pressure_metrics(
            friendly_sources=[source],
            neutral_junctions=[n_frontier, n_far],
            enemy_junctions=[enemy],
        )
        # enemy at (5,0): n_frontier dist=0 (yes), n_far dist=395 (no) → 1
        assert m.best_enemy_scramble_block == 1
