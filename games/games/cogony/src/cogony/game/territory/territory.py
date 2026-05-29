"""Territory variant: adds team territory, junction network, and territory control."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from pydantic import Field

from mettagrid.cogame.core import CoGameMissionVariant, Deps
from cogony.game.junction import JunctionVariant
from cogony.game.teams.hub import TeamHubVariant
from cogony.game.teams.team import TeamVariant
from mettagrid.config.filter import hasTag, maxDistance
from mettagrid.config.handler_config import Handler
from mettagrid.config.mettagrid_config import GridObjectConfig, MettaGridConfig
from mettagrid.config.mutation import recomputeMaterializedQuery
from mettagrid.config.mutation.mutation import EntityTarget
from mettagrid.config.mutation.tag_mutation import removeTagPrefix
from mettagrid.config.query import ClosureQuery, MaterializedQuery, materializedQuery, query
from mettagrid.config.territory_config import TerritoryConfig, TerritoryControlConfig

JUNCTION_ALIGN_DISTANCE = 15
HUB_ALIGN_DISTANCE = 25
TERRITORY_CONTROL_RADIUS = 10

if TYPE_CHECKING:
    from cogony.game.teams import TeamConfig
    from cogony.mission import CogonyMission


def net_materialized_query(team: TeamConfig) -> MaterializedQuery:
    """Build the closure query that computes which research nodes are in a team's network."""
    net_tag = f"net:{team.name}"
    return materializedQuery(
        net_tag,
        ClosureQuery(
            source=team.network_seed_query(),
            candidates=query("node", hasTag(team.team_tag())),
            edge_filters=[maxDistance(max(JUNCTION_ALIGN_DISTANCE, HUB_ALIGN_DISTANCE))],
        ),
    )


class TerritoryVariant(CoGameMissionVariant):
    """Add team territory with junction-based influence, network queries, and alignment stats."""

    name: str = "territory"
    description: str = "Team territory with junction network and alignment tracking."

    control_range: int = Field(default=TERRITORY_CONTROL_RADIUS)

    @override
    def dependencies(self) -> Deps:
        from cogony.game.datacenter import DatacenterVariant  # noqa: PLC0415
        from cogony.game.observatory import ObservatoryVariant  # noqa: PLC0415

        return Deps(required=[TeamHubVariant, JunctionVariant, TeamVariant],
                    optional=[ObservatoryVariant, DatacenterVariant])

    @override
    def modify_env(self, mission: CogonyMission, env: MettaGridConfig) -> None:
        presence: dict[str, Handler] = {}

        env.game.territories["team_territory"] = TerritoryConfig(
            tag_prefix="team:",
            presence=presence,
        )

        tc = TerritoryControlConfig(territory="team_territory", strength=self.control_range)
        hub_tc = TerritoryControlConfig(territory="team_territory", strength=self.control_range * 2)

        for obj in env.game.objects.values():
            if isinstance(obj, GridObjectConfig) and obj.name in ("hub", "junction", "observatory", "datacenter"):
                is_hub = obj.name == "hub"
                obj.territory_controls.append((hub_tc if is_hub else tc).model_copy())

        team_v = mission.required_variant(TeamVariant)
        all_teams = list(team_v.teams.values())

        for team in all_teams:
            env.game.materialize_queries.append(net_materialized_query(team))

        recompute_mutations = [recomputeMaterializedQuery(t.net_tag()) for t in all_teams]
        reboot_init = env.game.events.get("node_reboot_init")
        if reboot_init is not None:
            reboot_init.mutations.extend([
                removeTagPrefix("team:", target=EntityTarget.TARGET),
                *recompute_mutations,
            ])
