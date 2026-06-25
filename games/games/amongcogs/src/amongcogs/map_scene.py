"""Custom map scene for Among Us style station-task gameplay."""

from __future__ import annotations

from pydantic import Field

from mettagrid.mapgen.scene import Scene, SceneConfig


class AmongUsShipConfig(SceneConfig):
    spawn_count: int = Field(default=12, ge=1, le=64)


class AmongUsShipScene(Scene[AmongUsShipConfig]):
    """Build a Skeld-like spaceship topology with recognizable room connectivity."""

    def _carve_rect(self, x0: int, y0: int, x1: int, y1: int) -> None:
        self.grid[max(0, y0) : min(self.height, y1), max(0, x0) : min(self.width, x1)] = "empty"

    def _carve_hallway_h(self, x0: int, x1: int, y: int, thickness: int = 1) -> None:
        half = thickness // 2
        self._carve_rect(min(x0, x1), y - half, max(x0, x1) + 1, y + half + 1)

    def _carve_hallway_v(self, x: int, y0: int, y1: int, thickness: int = 1) -> None:
        half = thickness // 2
        self._carve_rect(x - half, min(y0, y1), x + half + 1, max(y0, y1) + 1)

    def _place(self, name: str, x: int, y: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.grid[y, x] = name

    def _spawn_candidates(self) -> list[tuple[int, int]]:
        return [
            # Cafeteria cluster.
            (25, 6),
            (23, 6),
            (27, 6),
            (21, 6),
            (29, 6),
            (24, 4),
            (26, 4),
            (24, 8),
            (26, 8),
            (22, 8),
            (28, 8),
            (24, 10),
            (26, 10),
            # Storage + hallway overflow.
            (23, 22),
            (25, 22),
            (27, 22),
            (21, 22),
            (29, 22),
            (24, 24),
            (26, 24),
            (22, 24),
            (28, 24),
            (24, 26),
            (26, 26),
            (24, 28),
            (26, 28),
            # Left / right corridor spillover.
            (16, 20),
            (9, 24),
            (6, 14),
            (10, 14),
            (16, 8),
            (38, 6),
            (38, 12),
            (45, 11),
            (32, 19),
            (33, 25),
            (38, 26),
        ]

    def render(self) -> None:
        self.grid[:] = "wall"

        # Skeld-like rooms.
        self._carve_rect(20, 2, 34, 12)  # cafeteria
        self._carve_rect(36, 3, 43, 8)  # weapons
        self._carve_rect(36, 10, 42, 14)  # O2
        self._carve_rect(43, 8, 48, 15)  # navigation
        self._carve_rect(30, 16, 36, 22)  # admin
        self._carve_rect(20, 18, 30, 30)  # storage
        self._carve_rect(13, 16, 20, 23)  # electrical
        self._carve_rect(3, 21, 11, 28)  # lower engine
        self._carve_rect(2, 11, 10, 19)  # reactor
        self._carve_rect(10, 12, 14, 17)  # security
        self._carve_rect(4, 3, 12, 10)  # upper engine
        self._carve_rect(14, 4, 20, 11)  # medbay
        self._carve_rect(30, 24, 36, 30)  # communications
        self._carve_rect(36, 23, 43, 30)  # shields

        # Hallways matching Skeld flow.
        self._carve_hallway_h(11, 20, 6, thickness=2)  # upper engine <-> medbay
        self._carve_hallway_h(20, 36, 6, thickness=2)  # medbay <-> cafeteria <-> weapons
        self._carve_hallway_h(42, 43, 12, thickness=2)  # O2 <-> navigation
        self._carve_hallway_v(39, 14, 23, thickness=2)  # O2/nav <-> shields spine
        self._carve_hallway_h(34, 36, 19, thickness=2)  # admin <-> right spine
        self._carve_hallway_v(27, 12, 18, thickness=2)  # cafeteria <-> admin/storage
        self._carve_hallway_h(20, 30, 19, thickness=2)  # storage <-> admin
        self._carve_hallway_h(20, 30, 28, thickness=2)  # storage <-> comms
        self._carve_hallway_h(36, 36, 27, thickness=2)  # comms <-> shields
        self._carve_hallway_h(11, 13, 20, thickness=2)  # electrical <-> storage
        self._carve_hallway_h(10, 13, 14, thickness=2)  # reactor/security <-> electrical/medbay
        self._carve_hallway_v(6, 19, 21, thickness=2)  # reactor <-> lower engine
        self._carve_hallway_v(6, 10, 11, thickness=2)  # upper engine <-> reactor

        # Skeld room stations.
        self._place("emergency_button", 27, 6)  # cafeteria button
        self._place("weapons_station", 39, 6)  # weapons
        self._place("oxygen_station", 38, 12)  # O2 code panel
        self._place("navigation_station", 45, 11)  # navigation
        self._place("admin_station", 33, 19)  # admin
        self._place("oxygen_station", 31, 19)  # admin O2 code panel
        self._place("comms_station", 33, 27)  # communications
        self._place("shields_station", 39, 27)  # shields
        self._place("wiring_station", 16, 19)  # electrical
        self._place("lights_station", 14, 19)  # electrical lights
        self._place("reactor_station", 5, 13)  # reactor left hand
        self._place("reactor_station", 7, 15)  # reactor right hand
        self._place("security_station", 11, 14)  # security cameras
        self._place("medbay_station", 16, 7)  # medbay scan
        self._place("cafeteria_vent", 30, 8)
        self._place("admin_vent", 34, 20)
        self._place("weapons_vent", 41, 5)
        self._place("reactor_vent", 4, 16)
        self._place("security_vent", 12, 15)
        self._place("upper_engine_vent", 6, 6)
        self._place("medbay_vent", 18, 8)
        self._place("electrical_vent", 16, 21)
        self._place("lower_engine_vent", 6, 25)
        self._place("navigation_vent", 46, 13)
        self._place("oxygen_vent", 37, 11)
        self._place("shields_vent", 41, 25)

        # Deterministic spawn placement with overflow fallback.
        spawn_count = self.config.spawn_count
        placed = 0
        for x, y in self._spawn_candidates():
            if placed >= spawn_count:
                break
            if self.grid[y, x] == "empty":
                self.grid[y, x] = "agent.agent"
                placed += 1

        if placed < spawn_count:
            for y in range(1, self.height - 1):
                for x in range(1, self.width - 1):
                    if placed >= spawn_count:
                        break
                    if self.grid[y, x] == "empty":
                        self.grid[y, x] = "agent.agent"
                        placed += 1
                if placed >= spawn_count:
                    break

        if placed < spawn_count:
            raise ValueError(f"AmongUsShipScene could only place {placed} spawn pads (requested {spawn_count}).")
