"""Typed validation for shared commissioner cutover and retirement artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManifestVariant(StrictModel):
    seat_count: int = Field(gt=0)
    map: str | None = None
    turns_min: int | None = None
    turns_max: int | None = None


class ManifestTopology(StrictModel):
    coworld: str
    canonical_version: str
    captured_at: str
    seat_limits: dict[Literal["min", "max"], int]
    variants: dict[str, ManifestVariant]
    results_fields: list[str]


class RetirementArtifact(StrictModel):
    path: str
    phase: Literal["rollback_ready", "retired"]
    league_id: str
    owner_repo: str


class RetirementContract(StrictModel):
    artifacts: list[RetirementArtifact]


class Fulfillment(StrictModel):
    allowed_failures: float = Field(ge=0, le=1)
    retry_times: int = Field(ge=0)


class Division(StrictModel):
    division_id: str
    name: Literal["Competition"]
    disqualify_after_consecutive_failures: int = Field(gt=0)


class QualificationExperience(StrictModel):
    kind: Literal["self_play"]
    num_episodes: int = Field(gt=0)
    seat_count: int = Field(gt=0)


class QualificationPredicate(StrictModel):
    key: str
    operator: Literal["gte"]
    value: int


class QualificationGate(StrictModel):
    op: Literal["pred"]
    pred: QualificationPredicate


class Qualification(StrictModel):
    experience: QualificationExperience
    gate: QualificationGate
    max_attempts: int = Field(gt=0)
    attempt_timeout_minutes: int = Field(gt=0)


class NomicScheduler(StrictModel):
    strategy: Literal["round_robin"]
    insufficient_players: Literal["multiple_seats"]
    min_episodes_per_entrant: int = Field(gt=0)


class ScoreRanking(StrictModel):
    algorithm: Literal["score"]
    direction: Literal["maximize"]
    round_scoring_rule: Literal["mean"]
    standing_aggregation: Literal["ewma"]
    half_life_hours: float = Field(gt=0)
    initial_standing: float


class NomicLadder(StrictModel):
    enabled: bool
    scheduler: NomicScheduler
    fulfillment: Fulfillment
    ranking: ScoreRanking
    qualification: Qualification
    divisions: list[Division]


class NomicSettings(StrictModel):
    round_interval_minutes: int = Field(gt=0)
    ladder: NomicLadder


class ProxywarScheduler(StrictModel):
    strategy: Literal["scaling_roster"]
    insufficient_players: Literal["multiple_seats"]
    seat_rungs: list[int]
    episodes_per_round: int = Field(gt=0)
    roster_overflow: Literal["partition"]
    variant_rotation_by_seat_count: dict[int, list[str]]


class ProxywarLadder(StrictModel):
    enabled: bool
    scheduler: ProxywarScheduler
    fulfillment: Fulfillment
    ranking: ScoreRanking
    qualification: Qualification
    divisions: list[Division]


class ProxywarSettings(StrictModel):
    round_interval_minutes: int = Field(gt=0)
    ladder: ProxywarLadder


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def validate_nomic_fable() -> None:
    topology = ManifestTopology.model_validate(
        _load_json(HERE / "fixtures/nomic_fable_manifest_topology.json")
    )
    settings = NomicSettings.model_validate(
        _load_json(HERE / "settings/nomic_fable.json")
    )
    ladder = settings.ladder
    scheduler = ladder.scheduler
    assert settings.round_interval_minutes == 30
    assert ladder.enabled is False
    assert len(ladder.divisions) == 1
    assert (topology.seat_limits["min"], topology.seat_limits["max"]) == (3, 3)
    assert scheduler.min_episodes_per_entrant == 8
    assert ladder.qualification.experience.seat_count == 3
    assert ladder.qualification.gate.pred.key in {
        f"result.{field}" for field in topology.results_fields
    }
    assert ladder.ranking.half_life_hours == 2


def validate_proxywar() -> None:
    topology = ManifestTopology.model_validate(
        _load_json(HERE / "fixtures/proxywar_manifest_topology.json")
    )
    settings = ProxywarSettings.model_validate(
        _load_json(HERE / "settings/proxywar.json")
    )
    container = yaml.safe_load(
        (
            ROOT
            / "commissioners/commissioners/ruleset_strategy_commissioner/configs/proxywar.yaml"
        ).read_text()
    )
    ladder = settings.ladder
    scheduler = ladder.scheduler
    assert topology.canonical_version == "0.1.27"
    assert settings.round_interval_minutes == container["schedule_interval_minutes"]
    assert ladder.enabled is False
    assert len(ladder.divisions) == 1
    assert scheduler.seat_rungs == [2, 4, 8, 12]
    assert (
        scheduler.episodes_per_round
        == container["defaults"]["stage"]["min_episodes_per_entrant"]
    )
    qualifier_stage = container["divisions"]["qualifiers"]["stages"][0]["schedule"]
    assert (
        ladder.qualification.experience.num_episodes
        == qualifier_stage["min_episodes_per_entrant"]
    )
    assert ladder.qualification.max_attempts == qualifier_stage["attempts"]
    rotations = scheduler.variant_rotation_by_seat_count
    assert sorted(rotations) == scheduler.seat_rungs
    for seat_count, variant_ids in rotations.items():
        assert variant_ids
        assert all(
            topology.variants[variant_id].seat_count == seat_count
            for variant_id in variant_ids
        )
    assert set(topology.variants) == {
        variant_id for rotation in rotations.values() for variant_id in rotation
    }
    assert ladder.qualification.gate.pred.key in {
        f"result.{field}" for field in topology.results_fields
    }
    assert ladder.ranking.round_scoring_rule == container["scoring"]["round_score"]
    assert (
        ladder.ranking.standing_aggregation
        == container["scoring"]["leaderboard"]["type"]
    )
    assert (
        ladder.ranking.half_life_hours
        == container["scoring"]["leaderboard"]["half_life_hours"]
    )


def validate_retirement() -> None:
    contract = RetirementContract.model_validate(
        _load_json(HERE / "retirement_contract.json")
    )
    for artifact in contract.artifacts:
        exists = (ROOT / artifact.path).is_file()
        if artifact.phase == "rollback_ready":
            assert exists, (
                f"rollback artifact disappeared before its platform soak: {artifact.path}"
            )
        else:
            assert not exists, f"retired artifact still exists: {artifact.path}"


def validate_all() -> None:
    validate_nomic_fable()
    validate_proxywar()
    validate_retirement()


if __name__ == "__main__":
    validate_all()
    print("shared platform commissioner migration contracts are internally consistent")
