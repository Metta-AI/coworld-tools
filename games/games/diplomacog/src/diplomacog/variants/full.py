"""Challenge bundle variants for diplomacy."""

from cogames.core import CoGameMissionVariant, Deps

from diplomacog.variants.layout import CompactArenaVariant
from diplomacog.variants.pressure import CrisisSurgeVariant, SabotageHeavyVariant


class FullVariant(CoGameMissionVariant):
    name: str = "full"
    description: str = "All challenge modifiers enabled: compact map, crisis surge, and heavy sabotage."

    def dependencies(self) -> Deps:
        return Deps(required=[CompactArenaVariant, CrisisSurgeVariant, SabotageHeavyVariant])

    def modify_mission(self, mission) -> None:
        CompactArenaVariant().modify_mission(mission)
