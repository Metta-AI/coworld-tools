"""Tests for cvc.agent.scoring functions."""

from __future__ import annotations

from cvc_policy.agent.scoring import (
    aligner_target_score,
    is_usable_extractor,
    scramble_target_score,
    spawn_relative_station_target,
    teammate_closer_to_target,
    within_alignment_network,
)
from cvc_policy.agent.types import (
    HUB_ALIGN_DISTANCE,
    JUNCTION_ALIGN_DISTANCE,
    JUNCTION_AOE_RANGE,
    _STATION_TARGETS_BY_AGENT,
)

# ---------------------------------------------------------------------------
# within_alignment_network
# ---------------------------------------------------------------------------


class TestWithinAlignmentNetwork:
    def test_within_hub_distance(self, make_entity):
        hub = make_entity(entity_type="hub", x=50, y=50)
        candidate = (50 + HUB_ALIGN_DISTANCE, 50)
        assert within_alignment_network(candidate, [hub]) is True

    def test_outside_hub_distance(self, make_entity):
        hub = make_entity(entity_type="hub", x=50, y=50)
        candidate = (50 + HUB_ALIGN_DISTANCE + 1, 50)
        assert within_alignment_network(candidate, [hub]) is False

    def test_within_junction_distance(self, make_entity):
        junction = make_entity(entity_type="junction", x=50, y=50)
        candidate = (50 + JUNCTION_ALIGN_DISTANCE, 50)
        assert within_alignment_network(candidate, [junction]) is True

    def test_outside_junction_distance(self, make_entity):
        junction = make_entity(entity_type="junction", x=50, y=50)
        candidate = (50 + JUNCTION_ALIGN_DISTANCE + 1, 50)
        assert within_alignment_network(candidate, [junction]) is False

    def test_exact_boundary_hub(self, make_entity):
        hub = make_entity(entity_type="hub", x=0, y=0)
        # Manhattan distance exactly HUB_ALIGN_DISTANCE
        candidate = (HUB_ALIGN_DISTANCE, 0)
        assert within_alignment_network(candidate, [hub]) is True

    def test_exact_boundary_junction(self, make_entity):
        junction = make_entity(entity_type="junction", x=0, y=0)
        candidate = (JUNCTION_ALIGN_DISTANCE, 0)
        assert within_alignment_network(candidate, [junction]) is True

    def test_empty_sources(self):
        assert within_alignment_network((50, 50), []) is False

    def test_multiple_sources_one_in_range(self, make_entity):
        far_junction = make_entity(entity_type="junction", x=0, y=0)
        close_hub = make_entity(entity_type="hub", x=50, y=50)
        candidate = (50, 50 + HUB_ALIGN_DISTANCE)
        assert within_alignment_network(candidate, [far_junction, close_hub]) is True

    def test_multiple_sources_none_in_range(self, make_entity):
        j1 = make_entity(entity_type="junction", x=0, y=0)
        j2 = make_entity(entity_type="junction", x=100, y=100)
        candidate = (50, 50)
        assert within_alignment_network(candidate, [j1, j2]) is False

    def test_hub_uses_hub_distance_not_junction(self, make_entity):
        """Hub sources use HUB_ALIGN_DISTANCE which is larger than junction."""
        hub = make_entity(entity_type="hub", x=50, y=50)
        # Between junction and hub distance
        candidate = (50 + JUNCTION_ALIGN_DISTANCE + 1, 50)
        assert JUNCTION_ALIGN_DISTANCE < HUB_ALIGN_DISTANCE
        assert within_alignment_network(candidate, [hub]) is True

    def test_same_position(self, make_entity):
        junction = make_entity(entity_type="junction", x=10, y=10)
        assert within_alignment_network((10, 10), [junction]) is True

    def test_diagonal_manhattan_distance(self, make_entity):
        junction = make_entity(entity_type="junction", x=50, y=50)
        # Split distance across both axes
        half = JUNCTION_ALIGN_DISTANCE // 2
        remainder = JUNCTION_ALIGN_DISTANCE - half
        candidate = (50 + half, 50 + remainder)
        assert within_alignment_network(candidate, [junction]) is True


# ---------------------------------------------------------------------------
# teammate_closer_to_target
# ---------------------------------------------------------------------------


class TestTeammateCloserToTarget:
    def test_teammate_closer(self):
        assert (
            teammate_closer_to_target(
                current_position=(0, 0),
                target=(10, 10),
                teammate_positions=[(5, 5)],
            )
            is True
        )

    def test_no_teammate_closer(self):
        assert (
            teammate_closer_to_target(
                current_position=(5, 5),
                target=(10, 10),
                teammate_positions=[(0, 0)],
            )
            is False
        )

    def test_teammate_same_distance(self):
        """Equal distance should NOT count as closer (strict <)."""
        assert (
            teammate_closer_to_target(
                current_position=(0, 0),
                target=(10, 0),
                teammate_positions=[(20, 0)],  # teammate dist=10, same as ours
            )
            is False
        )

    def test_empty_teammates(self):
        assert (
            teammate_closer_to_target(
                current_position=(0, 0),
                target=(10, 10),
                teammate_positions=[],
            )
            is False
        )

    def test_multiple_teammates_one_closer(self):
        assert (
            teammate_closer_to_target(
                current_position=(5, 5),
                target=(10, 10),
                teammate_positions=[(0, 0), (8, 8)],
            )
            is True
        )

    def test_at_target(self):
        """If we are at the target, teammates can only tie, not be closer."""
        assert (
            teammate_closer_to_target(
                current_position=(10, 10),
                target=(10, 10),
                teammate_positions=[(10, 10)],
            )
            is False
        )


# ---------------------------------------------------------------------------
# aligner_target_score
# ---------------------------------------------------------------------------


class TestAlignerTargetScore:
    def test_basic_distance_score(self, make_entity):
        candidate = make_entity(entity_type="junction", x=10, y=0)
        score, neg_expansion = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],        )
        # distance = 10, no penalties/bonuses
        assert score == 10.0
        assert neg_expansion == 0.0

    def test_expansion_reduces_score(self, make_entity):
        candidate = make_entity(entity_type="junction", x=10, y=0)
        # Place unreachable entities within JUNCTION_ALIGN_DISTANCE of candidate
        nearby = make_entity(entity_type="junction", x=10 + JUNCTION_ALIGN_DISTANCE, y=0)
        score_with, neg_exp = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[nearby],
            enemy_junctions=[],        )
        score_without, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],        )
        assert score_with < score_without
        assert neg_exp == -1.0

    def test_expansion_capped_at_30(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        # Create 10 unreachable entities all near candidate (expansion=10, but 10*5=50 capped to 30)
        unreachable = [make_entity(x=50 + i, y=50) for i in range(10)]
        score, neg_exp = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=unreachable,
            enemy_junctions=[],        )
        # distance=0, expansion capped at -30, score = 0 - 30 = -30
        assert score == -30.0
        assert neg_exp == -10.0

    def test_enemy_aoe_penalty(self, make_entity):
        candidate = make_entity(entity_type="junction", x=10, y=0)
        enemy = make_entity(entity_type="junction", x=10 + JUNCTION_AOE_RANGE, y=0)
        score_with_enemy, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[enemy],        )
        score_without, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],        )
        assert score_with_enemy == score_without + 8.0

    def test_enemy_outside_aoe_no_penalty(self, make_entity):
        candidate = make_entity(entity_type="junction", x=10, y=0)
        enemy = make_entity(entity_type="junction", x=10 + JUNCTION_AOE_RANGE + 1, y=0)
        score_with, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[enemy],        )
        score_without, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],        )
        assert score_with == score_without


    def test_hub_penalty_close(self, make_entity):
        """Hub distance <= 10: penalty = hub_dist * 0.3"""
        candidate = make_entity(entity_type="junction", x=55, y=50)
        hub_pos = (50, 50)  # hub_dist = 5
        score, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hub_position=hub_pos,
        )
        # distance=5, hub_penalty=5*0.3=1.5
        assert score == 5.0 + 1.5

    def test_hub_penalty_medium(self, make_entity):
        """Hub distance 10-15: penalty = (dist-10)*1.5 + 2.0"""
        candidate = make_entity(entity_type="junction", x=62, y=50)
        hub_pos = (50, 50)  # hub_dist = 12
        score, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hub_position=hub_pos,
        )
        # distance=12, hub_penalty=(12-10)*1.5+2.0=5.0
        assert score == 12.0 + 5.0

    def test_hub_penalty_far(self, make_entity):
        """Hub distance 15-25: penalty = (dist-15)*3.0 + 10.0"""
        candidate = make_entity(entity_type="junction", x=70, y=50)
        hub_pos = (50, 50)  # hub_dist = 20
        score, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hub_position=hub_pos,
        )
        # distance=20, hub_penalty=(20-15)*3.0+10.0=25.0
        assert score == 20.0 + 25.0

    def test_hub_penalty_very_far(self, make_entity):
        """Hub distance > 25: penalty = (dist-25)*8.0 + 50.0"""
        candidate = make_entity(entity_type="junction", x=80, y=50)
        hub_pos = (50, 50)  # hub_dist = 30
        score, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hub_position=hub_pos,
        )
        # distance=30, hub_penalty=(30-25)*8.0+50.0=90.0
        assert score == 30.0 + 90.0

    def test_no_hub_position_no_hub_penalty(self, make_entity):
        candidate = make_entity(entity_type="junction", x=80, y=50)
        score, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hub_position=None,
        )
        # distance=30, no hub penalty
        assert score == 30.0

    def test_hotspot_penalty(self, make_entity):
        candidate = make_entity(entity_type="junction", x=10, y=0)
        score_hotspot, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hotspot_count=2,
        )
        score_no_hotspot, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hotspot_count=0,
        )
        # default hotspot_weight=8.0 (no hub), penalty = min(2,3)*8 = 16
        assert score_hotspot == score_no_hotspot + 16.0

    def test_hotspot_capped_at_3(self, make_entity):
        candidate = make_entity(entity_type="junction", x=10, y=0)
        score_3, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hotspot_count=3,
        )
        score_5, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hotspot_count=5,
        )
        assert score_3 == score_5

    def test_hotspot_weight_reduced_near_hub(self, make_entity):
        """Hotspot weight is 2.0 when hub_dist <= 10."""
        candidate = make_entity(entity_type="junction", x=55, y=50)
        hub_pos = (50, 50)  # hub_dist = 5
        score, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            hub_position=hub_pos,
            hotspot_count=2,
        )
        # distance=5, hub_penalty=5*0.3=1.5, hotspot=min(2,3)*2.0=4.0
        assert score == 5.0 + 1.5 + 4.0

    def test_network_bonus(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        friendly = make_entity(entity_type="junction", x=50 + JUNCTION_ALIGN_DISTANCE, y=50)
        score_with, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            friendly_sources=[friendly],
        )
        score_without, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],        )
        # 1 nearby friendly * 0.5 = 0.5 bonus (lower score)
        assert score_with == score_without - 0.5

    def test_network_bonus_excludes_hubs(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        hub = make_entity(entity_type="hub", x=50, y=50)
        score_with, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            friendly_sources=[hub],
        )
        score_without, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],        )
        assert score_with == score_without  # hub excluded from network bonus

    def test_network_bonus_capped_at_4(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        friendlies = [make_entity(entity_type="junction", x=50 + i, y=50) for i in range(6)]
        score, _ = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            friendly_sources=friendlies,
        )
        # Capped at 4 * 0.5 = 2.0
        assert score == 0.0 - 2.0

    def test_teammate_closer_penalty(self, make_entity):
        candidate = make_entity(entity_type="junction", x=10, y=0)
        score_closer, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            teammate_closer=True,
        )
        score_not, _ = aligner_target_score(
            current_position=(0, 0),
            candidate=candidate,
            unreachable=[],
            enemy_junctions=[],            teammate_closer=False,
        )
        assert score_closer == score_not + 6.0

    def test_returns_negative_expansion(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        nearby1 = make_entity(x=50 + 1, y=50)
        nearby2 = make_entity(x=50, y=50 + 1)
        _, neg_exp = aligner_target_score(
            current_position=(50, 50),
            candidate=candidate,
            unreachable=[nearby1, nearby2],
            enemy_junctions=[],        )
        assert neg_exp == -2.0


# ---------------------------------------------------------------------------
class TestIsUsableExtractor:
    def test_generic_extractor_is_usable(self, make_entity):
        entity = make_entity(entity_type="extractor")
        assert is_usable_extractor(entity) is True

    def test_empty_extractor_is_skipped(self, make_entity):
        entity = make_entity(entity_type="carbon_extractor", attributes={"carbon": 0})
        assert is_usable_extractor(entity) is False

    def test_nonempty_extractor_is_usable(self, make_entity):
        entity = make_entity(entity_type="oxygen_extractor", attributes={"oxygen": 42})
        assert is_usable_extractor(entity) is True

    def test_missing_resource_attribute_is_empty(self, make_entity):
        """Drained extractors have the resource key removed, not set to 0."""
        entity = make_entity(entity_type="carbon_extractor")
        assert is_usable_extractor(entity) is False


# ---------------------------------------------------------------------------
# scramble_target_score
# ---------------------------------------------------------------------------


class TestScrambleTargetScore:
    def test_basic_distance(self, make_entity):
        candidate = make_entity(entity_type="junction", x=60, y=50)
        score, neg_blocked = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[],
        )
        # distance=10, blocked=0, corner_pressure=min(10/8, 10)=1.25
        assert score == 10.0 - 1.25
        assert neg_blocked == 0.0

    def test_blocked_neutrals_bonus(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        neutral = make_entity(entity_type="junction", x=50 + JUNCTION_AOE_RANGE, y=50)
        score, neg_blocked = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[neutral],
        )
        assert neg_blocked == -1.0
        # Each blocked neutral reduces score by 6.0
        score_no_neutral, _ = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[],
        )
        assert score == score_no_neutral - 6.0

    def test_neutral_outside_aoe(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        neutral = make_entity(entity_type="junction", x=50 + JUNCTION_AOE_RANGE + 1, y=50)
        _, neg_blocked = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[neutral],
        )
        assert neg_blocked == 0.0

    def test_corner_pressure_capped_at_10(self, make_entity):
        candidate = make_entity(entity_type="junction", x=150, y=50)
        hub_pos = (50, 50)  # hub_dist = 100, 100/8=12.5 capped to 10
        score, _ = scramble_target_score(
            current_position=(50, 50),
            hub_position=hub_pos,
            candidate=candidate,
            neutral_junctions=[],
        )
        assert score == 100.0 - 10.0

    def test_threat_bonus_from_friendly_junctions(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        friendly = make_entity(entity_type="junction", x=50 + JUNCTION_ALIGN_DISTANCE, y=50)
        score_with, _ = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[],
            friendly_junctions=[friendly],
        )
        score_without, _ = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[],
        )
        assert score_with == score_without - 10.0

    def test_friendly_outside_align_distance_no_threat(self, make_entity):
        candidate = make_entity(entity_type="junction", x=50, y=50)
        friendly = make_entity(entity_type="junction", x=50 + JUNCTION_ALIGN_DISTANCE + 1, y=50)
        score_with, _ = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[],
            friendly_junctions=[friendly],
        )
        score_without, _ = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[],
        )
        assert score_with == score_without

    def test_no_friendly_junctions(self, make_entity):
        candidate = make_entity(entity_type="junction", x=60, y=50)
        score_none, _ = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[],
            friendly_junctions=None,
        )
        score_empty, _ = scramble_target_score(
            current_position=(50, 50),
            hub_position=(50, 50),
            candidate=candidate,
            neutral_junctions=[],
            friendly_junctions=[],
        )
        assert score_none == score_empty


# ---------------------------------------------------------------------------
# spawn_relative_station_target
# ---------------------------------------------------------------------------


class TestSpawnRelativeStationTarget:
    def test_aligner_known_agent(self):
        result = spawn_relative_station_target(0, "aligner")
        assert result == _STATION_TARGETS_BY_AGENT["aligner"][0]

    def test_scrambler_known_agent(self):
        result = spawn_relative_station_target(1, "scrambler")
        assert result == _STATION_TARGETS_BY_AGENT["scrambler"][1]

    def test_miner_known_agent(self):
        result = spawn_relative_station_target(2, "miner")
        assert result == _STATION_TARGETS_BY_AGENT["miner"][2]

    def test_unknown_role(self):
        assert spawn_relative_station_target(0, "unknown_role") is None

    def test_unknown_agent_id(self):
        assert spawn_relative_station_target(999, "aligner") is None

    def test_all_aligner_agents_have_targets(self):
        for agent_id in _STATION_TARGETS_BY_AGENT["aligner"]:
            result = spawn_relative_station_target(agent_id, "aligner")
            assert result is not None
            assert isinstance(result, tuple)
            assert len(result) == 2
