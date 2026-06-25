"""Cogony-specific mutation configs for the custom C++ mutations."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from mettagrid.config.mutation.mutation import Mutation


class CogonyAttackMutation(Mutation):
    """Multi-channel attack: sum per-channel max(0, atk-def), with strike-back."""

    mutation_type: Literal["cogony_attack"] = "cogony_attack"
    channels: list[tuple[str, str]] = Field(
        description="List of (attack_resource, defend_resource) pairs",
    )
    health: str = Field(default="coherence", description="Health resource name")
    damage_tracking: list[str] = Field(
        default_factory=list,
        description="Per-channel damage tracking resource names (same length as channels)",
    )
    strike_back: bool = Field(default=True, description="Target strikes back if it survives")


class CogonyRebootMutation(Mutation):
    """Node reboot: level up, recompute stats, upgrade most-damaged defense."""

    mutation_type: Literal["cogony_reboot"] = "cogony_reboot"
    health: str = Field(default="coherence")
    reboot: str = Field(default="reboot")
    level: str = Field(default="level")
    resist_stats: list[str] = Field(description="Defense resource names")
    dmg_stats: list[str] = Field(description="Attack resource names")
    sys_damage_stats: list[str] = Field(description="Damage tracking resource names")
    coherence_per_level: int = Field(default=20)
    dmg_level_offset: int = Field(default=-3)


class CogonyLootMutation(Mutation):
    """Transfer all of listed resources from target to actor."""

    mutation_type: Literal["cogony_loot"] = "cogony_loot"
    resources: list[str] = Field(description="Resource names to transfer")


class CogonyHealMutation(Mutation):
    """Heal: target.coherence += actor.patch."""

    mutation_type: Literal["cogony_heal"] = "cogony_heal"
    patch: str = Field(default="patch", description="Actor's heal stat resource")
    health: str = Field(default="coherence", description="Target's health resource")
