"""
Evolutionary role system for CogsGuard agents.

This module implements evolutionary role recombination based on tribal-village's
evolution.nim. It provides mechanisms for:
- Sampling new roles with random behavior tiers
- Crossover (recombination) of successful roles
- Point mutations of roles
- Fitness tracking using exponential moving average
- Fitness-weighted selection for reproduction

The system allows roles to evolve over time based on game performance,
creating new role variations that can be tested and refined.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Optional

from mettagrid.simulator import Action

if TYPE_CHECKING:
    from cogames_agents.policy.scripted_agent.cogsguard.types import CogsguardAgentState


class BehaviorSource(Enum):
    """Source category for behaviors."""

    MINER = "miner"
    SCOUT = "scout"
    ALIGNER = "aligner"
    SCRAMBLER = "scrambler"
    COMMON = "common"  # Shared behaviors like explore, recharge


class TierSelection(Enum):
    """How to select behavior order within a tier."""

    FIXED = "fixed"  # Keep behavior order as provided
    SHUFFLE = "shuffle"  # Shuffle behavior order per materialization
    WEIGHTED = "weighted"  # Weighted shuffle using tier weights


@dataclass
class EvolutionConfig:
    """Configuration for evolutionary role sampling and mutation.

    Attributes:
        min_tiers: Minimum number of tiers per role (default: 2)
        max_tiers: Maximum number of tiers per role (default: 4)
        min_tier_size: Minimum behaviors per tier (default: 1)
        max_tier_size: Maximum behaviors per tier (default: 3)
        mutation_rate: Probability of mutating each tier (default: 0.15)
        lock_fitness_threshold: Fitness level at which to lock successful roles (default: 0.7)
        max_behaviors_per_role: Maximum total behaviors across all tiers (default: 12)
        fitness_alpha: EMA alpha for fitness updates (default: 0.2)
    """

    min_tiers: int = 2
    max_tiers: int = 4
    min_tier_size: int = 1
    max_tier_size: int = 3
    mutation_rate: float = 0.15
    lock_fitness_threshold: float = 0.7
    max_behaviors_per_role: int = 12
    fitness_alpha: float = 0.2


if TYPE_CHECKING:
    BehaviorFunc = Callable[[CogsguardAgentState], Action]
else:
    BehaviorFunc = Callable[[Any], Action]


@dataclass
class BehaviorDef:
    """Definition of a single behavior in the role system.

    Attributes:
        id: Unique identifier for this behavior
        name: Human-readable name (e.g., "mine_resource", "explore")
        source: Category this behavior belongs to
        can_start: Predicate to check if behavior can start
        act: The action function to execute
        should_terminate: Predicate to check if behavior should end
        interruptible: Whether higher-priority behaviors can interrupt this one
        fitness: Tracked fitness score (0.0 to 1.0)
        games: Number of games this behavior has been used in
        uses: Total number of times this behavior has been executed
    """

    id: int
    name: str
    source: BehaviorSource
    can_start: Callable[[CogsguardAgentState], bool]
    act: BehaviorFunc
    should_terminate: Callable[[CogsguardAgentState], bool]
    interruptible: bool = True
    fitness: float = 0.0
    games: int = 0
    uses: int = 0


@dataclass
class RoleTier:
    """A priority tier within a role definition.

    Behaviors within a tier are evaluated in order (or shuffled/weighted).
    Higher tiers (earlier in the list) have higher priority.

    Attributes:
        behavior_ids: List of behavior IDs in this tier
        weights: Optional weights for weighted selection
        selection: How to order behaviors when materializing
    """

    behavior_ids: list[int] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)
    selection: TierSelection = TierSelection.FIXED


@dataclass
class RoleDef:
    """Definition of an evolutionary role.

    A role consists of multiple tiers of behaviors, where each tier
    represents a priority level. The role also tracks its performance
    for evolutionary selection.

    Attributes:
        id: Unique identifier for this role
        name: Human-readable name (may be auto-generated)
        tiers: Priority-ordered list of behavior tiers
        origin: How this role was created ("sampled", "recombined", "manual")
        locked_name: Whether to preserve name (for successful roles)
        fitness: Tracked fitness score (0.0 to 1.0)
        games: Number of games this role has participated in
        wins: Number of wins with this role
    """

    id: int
    name: str
    tiers: list[RoleTier] = field(default_factory=list)
    origin: str = "manual"
    locked_name: bool = False
    fitness: float = 0.0
    games: int = 0
    wins: int = 0


@dataclass
class RoleCatalog:
    """Registry of behaviors and roles for evolutionary selection.

    The catalog maintains all known behaviors and roles, supporting
    operations like sampling new roles, crossover, and mutation.

    Attributes:
        behaviors: All registered behaviors
        roles: All registered roles
        next_role_id: Counter for generating unique role IDs
        next_name_id: Counter for generating unique role names
    """

    behaviors: list[BehaviorDef] = field(default_factory=list)
    roles: list[RoleDef] = field(default_factory=list)
    next_role_id: int = 0
    next_name_id: int = 0

    def find_behavior_id(self, name: str) -> int:
        """Find behavior ID by name, returns -1 if not found."""
        for behavior in self.behaviors:
            if behavior.name == name:
                return behavior.id
        return -1

    def add_behavior(
        self,
        name: str,
        source: BehaviorSource,
        can_start: Callable[[CogsguardAgentState], bool],
        act: BehaviorFunc,
        should_terminate: Callable[[CogsguardAgentState], bool],
        interruptible: bool = True,
    ) -> int:
        """Add a behavior to the catalog, returns behavior ID."""
        existing = self.find_behavior_id(name)
        if existing >= 0:
            return existing

        behavior_id = len(self.behaviors)
        self.behaviors.append(
            BehaviorDef(
                id=behavior_id,
                name=name,
                source=source,
                can_start=can_start,
                act=act,
                should_terminate=should_terminate,
                interruptible=interruptible,
            )
        )
        return behavior_id

    def find_role_id(self, name: str) -> int:
        """Find role ID by name, returns -1 if not found."""
        for role in self.roles:
            if role.name == name:
                return role.id
        return -1

    def register_role(self, role: RoleDef) -> int:
        """Register a role in the catalog, returns role ID."""
        role_id = len(self.roles)
        role.id = role_id
        self.roles.append(role)
        self.next_role_id = len(self.roles)
        return role_id

    def generate_role_name(self, tiers: list[RoleTier]) -> str:
        """Generate a unique role name based on primary behavior."""
        base_name = "Role"
        if tiers and tiers[0].behavior_ids:
            first_id = tiers[0].behavior_ids[0]
            if 0 <= first_id < len(self.behaviors):
                # Use shortened behavior name
                full_name = self.behaviors[first_id].name
                base_name = self._short_behavior_name(full_name)

        suffix = self.next_name_id
        self.next_name_id += 1
        return f"{base_name}-{suffix}"

    def _short_behavior_name(self, name: str) -> str:
        """Create a shortened behavior name for role naming."""
        # Remove common prefixes
        for prefix in ["behavior_", "miner_", "scout_", "aligner_", "scrambler_"]:
            if name.lower().startswith(prefix):
                name = name[len(prefix) :]
                break
        # Capitalize first letter
        return name.capitalize() if name else "Behavior"


def behavior_selection_weight(behavior: BehaviorDef) -> float:
    """Calculate selection weight for a behavior based on fitness.

    Behaviors with no games get weight 1.0 (explore new behaviors).
    Otherwise, weight is based on fitness with minimum 0.1.
    """
    if behavior.games <= 0:
        return 1.0
    return max(0.1, behavior.fitness)


def role_selection_weight(role: RoleDef) -> float:
    """Calculate selection weight for a role based on fitness.

    Roles with no games get weight 0.1 (slight exploration).
    Otherwise, weight is based on fitness with minimum 0.1.
    """
    if role.games <= 0:
        return 0.1
    return max(0.1, role.fitness)


def record_behavior_score(behavior: BehaviorDef, score: float, alpha: float = 0.2, weight: int = 1) -> None:
    """Update behavior fitness using exponential moving average.

    Args:
        behavior: The behavior to update
        score: The score to record (0.0 to 1.0)
        alpha: EMA smoothing factor (higher = more recent weight)
        weight: Number of times to apply this score
    """
    count = max(1, weight)
    for _ in range(count):
        behavior.games += 1
        if behavior.games == 1:
            behavior.fitness = score
        else:
            behavior.fitness = behavior.fitness * (1 - alpha) + score * alpha


def record_role_score(role: RoleDef, score: float, won: bool, alpha: float = 0.2, weight: int = 1) -> None:
    """Update role fitness using exponential moving average.

    Args:
        role: The role to update
        score: The score to record (0.0 to 1.0)
        won: Whether the game was won
        alpha: EMA smoothing factor (higher = more recent weight)
        weight: Number of times to apply this score
    """
    count = max(1, weight)
    for _ in range(count):
        role.games += 1
        if won:
            role.wins += 1
        if role.games == 1:
            role.fitness = score
        else:
            role.fitness = role.fitness * (1 - alpha) + score * alpha


def lock_role_name_if_fit(role: RoleDef, threshold: float = 0.7) -> None:
    """Lock a role's name if it has achieved sufficient fitness."""
    if role.fitness >= threshold:
        role.locked_name = True


def _weighted_pick_index(weights: list[float], rng: Optional[random.Random] = None) -> int:
    """Pick an index weighted by the given weights.

    Args:
        weights: List of weights (higher = more likely)
        rng: Random number generator (uses module random if None)

    Returns:
        Selected index
    """
    if not weights:
        return 0

    total = sum(max(0, w) for w in weights)
    if total <= 0:
        # All weights zero or negative, pick uniformly
        if rng:
            return rng.randint(0, len(weights) - 1)
        return random.randint(0, len(weights) - 1)

    if rng:
        roll = rng.random() * total
    else:
        roll = random.random() * total

    acc = 0.0
    for i, w in enumerate(weights):
        if w <= 0:
            continue
        acc += w
        if roll <= acc:
            return i

    return len(weights) - 1


def _sample_unique_ids_weighted(
    catalog: RoleCatalog,
    count: int,
    used: set[int],
    rng: Optional[random.Random] = None,
) -> list[int]:
    """Sample unique behavior IDs weighted by fitness.

    Args:
        catalog: The role catalog to sample from
        count: Number of IDs to sample
        used: Set of already-used IDs to exclude
        rng: Random number generator

    Returns:
        List of sampled behavior IDs
    """
    if not catalog.behaviors or count <= 0:
        return []

    # Build candidates and weights
    candidates: list[int] = []
    weights: list[float] = []
    for behavior in catalog.behaviors:
        if behavior.id in used:
            continue
        candidates.append(behavior.id)
        weights.append(behavior_selection_weight(behavior))

    result: list[int] = []
    while len(result) < count and candidates:
        idx = _weighted_pick_index(weights, rng)
        result.append(candidates[idx])
        used.add(candidates[idx])
        candidates.pop(idx)
        weights.pop(idx)

    # Fallback: if no result but behaviors exist, pick any unused one
    if not result and catalog.behaviors:
        for behavior in catalog.behaviors:
            if behavior.id not in used:
                result.append(behavior.id)
                used.add(behavior.id)
                break
        # Last resort: pick any behavior
        if not result:
            max_idx = len(catalog.behaviors) - 1
            fallback_id = rng.randint(0, max_idx) if rng else random.randint(0, max_idx)
            result.append(fallback_id)

    return result


def sample_role(
    catalog: RoleCatalog,
    config: Optional[EvolutionConfig] = None,
    rng: Optional[random.Random] = None,
) -> RoleDef:
    """Create a new role by randomly sampling behaviors into tiers.

    Args:
        catalog: The catalog to sample behaviors from
        config: Evolution configuration (uses defaults if None)
        rng: Random number generator

    Returns:
        A new randomly-sampled RoleDef
    """
    if config is None:
        config = EvolutionConfig()

    if not catalog.behaviors:
        return RoleDef(id=-1, name="EmptyRole", origin="sampled")

    if config.max_behaviors_per_role <= 0:
        return RoleDef(id=-1, name="EmptyRole", origin="sampled")

    # Sample number of tiers
    if rng:
        tier_count = rng.randint(config.min_tiers, config.max_tiers)
    else:
        tier_count = random.randint(config.min_tiers, config.max_tiers)

    tiers: list[RoleTier] = []
    used: set[int] = set()
    remaining = config.max_behaviors_per_role

    for _ in range(tier_count):
        if remaining <= 0:
            break

        # Sample tier size
        if rng:
            max_size = min(config.max_tier_size, remaining)
            min_size = min(config.min_tier_size, max_size)
            if min_size <= 0:
                break
            tier_size = rng.randint(min_size, max_size)
        else:
            max_size = min(config.max_tier_size, remaining)
            min_size = min(config.min_tier_size, max_size)
            if min_size <= 0:
                break
            tier_size = random.randint(min_size, max_size)

        behavior_ids = _sample_unique_ids_weighted(catalog, tier_size, used, rng)
        remaining -= len(behavior_ids)

        # Random selection mode
        if rng:
            selection = TierSelection.SHUFFLE if rng.random() < 0.5 else TierSelection.FIXED
        else:
            selection = TierSelection.SHUFFLE if random.random() < 0.5 else TierSelection.FIXED

        tiers.append(RoleTier(behavior_ids=behavior_ids, selection=selection))

    name = catalog.generate_role_name(tiers)
    return RoleDef(id=-1, name=name, tiers=tiers, origin="sampled")


def recombine_roles(
    catalog: RoleCatalog,
    left: RoleDef,
    right: RoleDef,
    rng: Optional[random.Random] = None,
) -> RoleDef:
    """Create a new role by crossover of two parent roles.

    The crossover picks random cut points in each parent and combines
    the left parent's early tiers with the right parent's later tiers.

    Args:
        catalog: The role catalog (for name generation)
        left: First parent role
        right: Second parent role
        rng: Random number generator

    Returns:
        A new RoleDef combining aspects of both parents
    """
    if not left.tiers and not right.tiers:
        return RoleDef(id=-1, name="EmptyRole", origin="recombined")
    if not left.tiers:
        return RoleDef(
            id=-1,
            name=catalog.generate_role_name(right.tiers),
            tiers=right.tiers.copy(),
            origin="recombined",
        )
    if not right.tiers:
        return RoleDef(
            id=-1,
            name=catalog.generate_role_name(left.tiers),
            tiers=left.tiers.copy(),
            origin="recombined",
        )

    # Pick cut points
    if rng:
        cut_left = rng.randint(0, len(left.tiers))
        cut_right = rng.randint(0, len(right.tiers))
    else:
        cut_left = random.randint(0, len(left.tiers))
        cut_right = random.randint(0, len(right.tiers))

    # Combine: left's tiers before cut_left + right's tiers from cut_right
    tiers: list[RoleTier] = []
    if cut_left > 0:
        tiers.extend(left.tiers[:cut_left])
    if cut_right < len(right.tiers):
        tiers.extend(right.tiers[cut_right:])

    # Ensure at least one tier
    if not tiers:
        tiers.append(left.tiers[0])

    name = catalog.generate_role_name(tiers)
    return RoleDef(id=-1, name=name, tiers=tiers, origin="recombined")


def mutate_role(
    catalog: RoleCatalog,
    role: RoleDef,
    mutation_rate: float = 0.15,
    rng: Optional[random.Random] = None,
) -> RoleDef:
    """Apply point mutations to a role.

    Mutations include:
    - Replacing random behaviors (at mutation_rate probability per tier)
    - Flipping tier selection mode (at mutation_rate * 0.5 probability)

    Args:
        catalog: The role catalog (for behavior lookup)
        role: The role to mutate (not modified in place)
        mutation_rate: Base probability of mutation per tier
        rng: Random number generator

    Returns:
        A new RoleDef with mutations applied
    """
    if not catalog.behaviors:
        return role

    # Deep copy tiers
    new_tiers: list[RoleTier] = []
    for tier in role.tiers:
        new_tier = RoleTier(
            behavior_ids=tier.behavior_ids.copy(),
            weights=tier.weights.copy(),
            selection=tier.selection,
        )
        new_tiers.append(new_tier)

    for tier in new_tiers:
        if not tier.behavior_ids:
            continue

        # Chance to mutate a behavior
        roll = rng.random() if rng else random.random()
        if roll < mutation_rate:
            tier_max = len(tier.behavior_ids) - 1
            idx = rng.randint(0, tier_max) if rng else random.randint(0, tier_max)
            behav_max = len(catalog.behaviors) - 1
            replacement = rng.randint(0, behav_max) if rng else random.randint(0, behav_max)
            tier.behavior_ids[idx] = replacement

        # Chance to flip selection mode
        roll = rng.random() if rng else random.random()
        if roll < mutation_rate * 0.5:
            if tier.selection == TierSelection.FIXED:
                tier.selection = TierSelection.SHUFFLE
            else:
                tier.selection = TierSelection.FIXED

    return RoleDef(
        id=-1,
        name=role.name,  # Keep name (unless renamed later)
        tiers=new_tiers,
        origin="mutated",
        locked_name=role.locked_name,
        fitness=role.fitness,
        games=role.games,
        wins=role.wins,
    )


def pick_role_id_weighted(
    catalog: RoleCatalog,
    role_ids: list[int],
    rng: Optional[random.Random] = None,
) -> int:
    """Select a role ID from a list, weighted by fitness.

    Args:
        catalog: The role catalog
        role_ids: List of role IDs to choose from
        rng: Random number generator

    Returns:
        Selected role ID, or -1 if role_ids is empty
    """
    if not role_ids:
        return -1

    weights: list[float] = []
    for role_id in role_ids:
        if 0 <= role_id < len(catalog.roles):
            weights.append(role_selection_weight(catalog.roles[role_id]))
        else:
            weights.append(0.0)

    idx = _weighted_pick_index(weights, rng)
    return role_ids[idx]


def resolve_tier_order(tier: RoleTier, rng: Optional[random.Random] = None) -> list[int]:
    """Resolve the behavior order for a tier based on its selection mode.

    Args:
        tier: The tier to resolve
        rng: Random number generator

    Returns:
        List of behavior IDs in execution order
    """
    if not tier.behavior_ids:
        return []

    if tier.selection == TierSelection.FIXED:
        return tier.behavior_ids.copy()

    if tier.selection == TierSelection.SHUFFLE:
        result = tier.behavior_ids.copy()
        if rng:
            rng.shuffle(result)
        else:
            random.shuffle(result)
        return result

    # TierSelection.WEIGHTED
    ids = tier.behavior_ids.copy()
    weights = tier.weights.copy() if len(tier.weights) == len(ids) else [1.0] * len(ids)

    result: list[int] = []
    while ids:
        idx = _weighted_pick_index(weights, rng)
        result.append(ids[idx])
        ids.pop(idx)
        weights.pop(idx)

    return result


def materialize_role_behaviors(
    catalog: RoleCatalog,
    role: RoleDef,
    rng: Optional[random.Random] = None,
    max_behaviors: int = 0,
) -> list[BehaviorDef]:
    """Convert a role definition to an ordered list of behaviors.

    This "materializes" the role by resolving tier orders and returning
    the actual BehaviorDef objects ready for execution.

    Args:
        catalog: The role catalog
        role: The role to materialize
        rng: Random number generator
        max_behaviors: Maximum behaviors to return (0 = unlimited)

    Returns:
        List of BehaviorDef in priority order
    """
    result: list[BehaviorDef] = []

    for tier in role.tiers:
        ordered_ids = resolve_tier_order(tier, rng)
        for behavior_id in ordered_ids:
            if 0 <= behavior_id < len(catalog.behaviors):
                result.append(catalog.behaviors[behavior_id])
                if max_behaviors > 0 and len(result) >= max_behaviors:
                    return result

    return result
