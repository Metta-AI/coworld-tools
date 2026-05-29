"""Map layout modifiers for diplomacy."""

from mettagrid.cogame.core import CoGameMissionVariant, Deps

from diplomacog.variants.discussion import DiscussionSessionsVariant


class CompactArenaVariant(CoGameMissionVariant):
    name: str = "compact"
    description: str = "Smaller map and tighter station spacing for faster interactions."

    def dependencies(self) -> Deps:
        return Deps(required=[DiscussionSessionsVariant])

    def modify_mission(self, mission) -> None:
        if hasattr(mission, "map_width"):
            mission.map_width = min(int(mission.map_width), 56)
        if hasattr(mission, "map_height"):
            mission.map_height = min(int(mission.map_height), 56)
        if hasattr(mission, "placement_variant"):
            mission.placement_variant = "compact"


class WorldLayoutVariant(CoGameMissionVariant):
    name: str = "world_layout"
    description: str = "Use wide-country world placement geometry for hubs and stations."

    def dependencies(self) -> Deps:
        return Deps(required=[DiscussionSessionsVariant])

    def modify_mission(self, mission) -> None:
        if hasattr(mission, "placement_variant"):
            mission.placement_variant = "world"
