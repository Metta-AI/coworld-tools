"""
Ultra-Fast Tribal Village Environment - Direct Buffer Interface.

Eliminates ALL conversion overhead by using direct numpy buffer communication.
"""

from __future__ import annotations

import ctypes
import platform
from pathlib import Path
from typing import Any

import numpy as np
from gymnasium import spaces

import pufferlib

from tribal_village_env.config import (
    EnvironmentConfig,
    OBS_MAX_VALUE,
    OBS_MIN_VALUE,
)

ACTION_VERB_COUNT = 11
ACTION_ARGUMENT_COUNT = 28
ACTION_SPACE_SIZE = ACTION_VERB_COUNT * ACTION_ARGUMENT_COUNT

_PLATFORM_LIB_NAMES = {
    "Darwin": "libtribal_village.dylib",
    "Windows": "libtribal_village.dll",
}
_DEFAULT_LIB_NAME = "libtribal_village.so"


def _find_library() -> Path:
    """Locate the Nim shared library for the current platform."""
    lib_name = _PLATFORM_LIB_NAMES.get(platform.system(), _DEFAULT_LIB_NAME)
    package_dir = Path(__file__).resolve().parent
    candidate_paths = [
        package_dir.parent / lib_name,
        package_dir / lib_name,
    ]
    lib_path = next((p for p in candidate_paths if p.exists()), None)
    if lib_path is None:
        searched = ", ".join(str(p) for p in candidate_paths)
        raise FileNotFoundError(f"Nim library not found. Searched: {searched}")
    return lib_path


class NimConfig(ctypes.Structure):
    """C-interop structure for passing configuration to Nim library."""

    _fields_ = [
        ("max_steps", ctypes.c_int32),
        ("victory_condition", ctypes.c_int32),
        ("tumor_spawn_rate", ctypes.c_float),
        ("heart_reward", ctypes.c_float),
        ("ore_reward", ctypes.c_float),
        ("bar_reward", ctypes.c_float),
        ("wood_reward", ctypes.c_float),
        ("water_reward", ctypes.c_float),
        ("wheat_reward", ctypes.c_float),
        ("spear_reward", ctypes.c_float),
        ("armor_reward", ctypes.c_float),
        ("food_reward", ctypes.c_float),
        ("cloth_reward", ctypes.c_float),
        ("tumor_kill_reward", ctypes.c_float),
        ("survival_penalty", ctypes.c_float),
        ("death_penalty", ctypes.c_float),
    ]

    @classmethod
    def from_config(cls, config: EnvironmentConfig) -> NimConfig:
        """Create NimConfig from typed EnvironmentConfig."""
        return cls(
            max_steps=config.max_steps,
            victory_condition=config.victory_condition,
            tumor_spawn_rate=float(config.tumor_spawn_rate),
            heart_reward=float(config.rewards.heart),
            ore_reward=float(config.rewards.ore),
            bar_reward=float(config.rewards.bar),
            wood_reward=float(config.rewards.wood),
            water_reward=float(config.rewards.water),
            wheat_reward=float(config.rewards.wheat),
            spear_reward=float(config.rewards.spear),
            armor_reward=float(config.rewards.armor),
            food_reward=float(config.rewards.food),
            cloth_reward=float(config.rewards.cloth),
            tumor_kill_reward=float(config.rewards.tumor_kill),
            survival_penalty=float(config.rewards.survival_penalty),
            death_penalty=float(config.rewards.death_penalty),
        )


class TribalVillageEnv(pufferlib.PufferEnv):
    """
    Ultra-fast tribal village environment using direct buffer interface.

    Eliminates conversion overhead by using pre-allocated numpy buffers
    that Nim reads/writes directly.

    Args:
        config: Environment configuration. Can be either:
            - EnvironmentConfig: Typed, validated configuration (recommended)
            - Dict[str, Any]: Legacy dictionary format (backward compatible)
            - None: Use default configuration
        buf: Optional buffer for PufferLib integration
    """

    def __init__(
        self,
        config: EnvironmentConfig | dict[str, Any] | None = None,
        buf: Any = None,
    ):
        # Convert config to typed EnvironmentConfig
        if config is None:
            self._typed_config = EnvironmentConfig()
        elif isinstance(config, EnvironmentConfig):
            self._typed_config = config
        else:
            # Legacy dict support
            self._typed_config = EnvironmentConfig.from_legacy_dict(config)

        # Legacy dict interface for backward compatibility
        self.config = self._typed_config.to_legacy_dict()
        self.max_steps = self._typed_config.max_steps
        self._render_mode = self._typed_config.render_mode

        # Load the optimized Nim library - cross-platform
        self.lib = ctypes.CDLL(str(_find_library()))
        self._setup_ctypes_interface()

        # Get environment dimensions
        self.total_agents = self.lib.tribal_village_get_num_agents()
        self.obs_layers = self.lib.tribal_village_get_obs_layers()
        self.obs_width = self.lib.tribal_village_get_obs_width()
        self.obs_height = self.lib.tribal_village_get_obs_height()

        # Map dims for full-map render
        try:
            self.map_width = int(self.lib.tribal_village_get_map_width())
            self.map_height = int(self.lib.tribal_village_get_map_height())
            self.render_scale = max(1, self._typed_config.render_scale)
            height = self.map_height * self.render_scale
            width = self.map_width * self.render_scale
            self._rgb_frame = np.zeros((height, width, 3), dtype=np.uint8)
        except (AttributeError, OSError, ValueError, TypeError):
            # FFI function may not exist (AttributeError), library call may fail (OSError),
            # or return value may not convert (ValueError/TypeError) — rendering is optional
            self.map_width = None
            self.map_height = None
            self.render_scale = 1
            self._rgb_frame = None

        # PufferLib controls all agents
        self.num_agents = self.total_agents
        self.agents = [f"agent_{i}" for i in range(self.total_agents)]
        self.possible_agents = self.agents.copy()

        # Define spaces - use direct observation shape (no sparse tokens!)
        self.single_observation_space = spaces.Box(
            low=OBS_MIN_VALUE,
            high=OBS_MAX_VALUE,
            shape=(self.obs_layers, self.obs_width, self.obs_height),
            dtype=np.uint8,
        )
        self.single_action_space = spaces.Discrete(ACTION_SPACE_SIZE)
        self.is_continuous = False

        super().__init__(buf)

        # Set up joint action space like metta does
        self.action_space = pufferlib.spaces.joint_space(
            self.single_action_space, self.num_agents
        )
        if hasattr(self, "actions"):
            self.actions = self.actions.astype(np.int32)

        # PufferLib will set these buffers - don't allocate our own!
        self.observations: np.ndarray
        self.terminals: np.ndarray
        self.truncations: np.ndarray
        self.rewards: np.ndarray

        # Only allocate actions buffer (input to environment)
        self.actions_buffer = np.zeros(self.total_agents, dtype=np.uint16)

        # Initialize environment
        self.env_ptr = self.lib.tribal_village_create()
        if not self.env_ptr:
            raise RuntimeError("Failed to create Nim environment")

        self._apply_ai_mode()
        self._apply_nim_config()

        self.step_count = 0

    @property
    def render_mode(self):
        return self._render_mode

    @render_mode.setter
    def render_mode(self, value):
        self._render_mode = value

    def render(self):
        """Render via Nim, avoiding duplication in Python.

        - 'rgb_array': calls Nim RGB export and returns an HxWx3 uint8 array
          of the full map (uses tile colors from the engine).
        - 'ansi': calls Nim ASCII renderer and returns a string.
        - otherwise: falls back to 'ansi'.
        """
        mode = getattr(self, "_render_mode", "ansi")

        # Prefer native RGB if requested and available
        if mode == "rgb_array" and getattr(self, "_rgb_frame", None) is not None:
            ptr = self._rgb_frame.ctypes.data_as(ctypes.c_void_p)
            width = int(self._rgb_frame.shape[1])
            height = int(self._rgb_frame.shape[0])
            try:
                ok = self.lib.tribal_village_render_rgb(
                    self.env_ptr, ptr, width, height
                )
            except AttributeError:
                ok = 0
            if ok:
                return self._rgb_frame
            # fall through to ansi if RGB export missing

        buf_size = self._typed_config.ansi_buffer_size
        cbuf = ctypes.create_string_buffer(buf_size)
        try:
            n_written = self.lib.tribal_village_render_ansi(
                self.env_ptr,
                ctypes.cast(cbuf, ctypes.c_void_p),
                ctypes.c_int32(buf_size),
            )
        except AttributeError:
            return "(render not available in Nim build)"

        if n_written <= 0:
            return ""
        return cbuf.value.decode("utf-8", errors="replace")

    def _setup_ctypes_interface(self):
        """Setup ctypes for direct buffer functions."""
        config_ptr = ctypes.POINTER(NimConfig)
        func_specs = [
            # required
            ("tribal_village_create", [], ctypes.c_void_p, False),
            ("tribal_village_set_config", [ctypes.c_void_p, config_ptr], ctypes.c_int32, False),
            (
                "tribal_village_reset_and_get_obs",
                [
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                ],
                ctypes.c_int32,
                False,
            ),
            (
                "tribal_village_step_with_pointers",
                [
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                ],
                ctypes.c_int32,
                False,
            ),
            ("tribal_village_destroy", [ctypes.c_void_p], None, False),
            ("tribal_village_get_num_agents", [], ctypes.c_int32, False),
            ("tribal_village_get_obs_layers", [], ctypes.c_int32, False),
            ("tribal_village_get_obs_width", [], ctypes.c_int32, False),
            ("tribal_village_get_obs_height", [], ctypes.c_int32, False),
            # AI mode control
            ("tribal_village_set_ai_mode", [ctypes.c_int32], ctypes.c_int32, True),
            # optional
            ("tribal_village_get_map_width", [], ctypes.c_int32, True),
            ("tribal_village_get_map_height", [], ctypes.c_int32, True),
            (
                "tribal_village_render_rgb",
                [
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    ctypes.c_int32,
                    ctypes.c_int32,
                ],
                ctypes.c_int32,
                True,
            ),
            (
                "tribal_village_render_ansi",
                [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32],
                ctypes.c_int32,
                True,
            ),
            # Market trading
            ("tribal_village_init_market_prices", [ctypes.c_void_p], None, True),
            ("tribal_village_get_market_price", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_set_market_price", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32], None, True),
            ("tribal_village_market_buy", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32)], ctypes.c_int32, True),
            ("tribal_village_market_sell", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32)], ctypes.c_int32, True),
            ("tribal_village_market_sell_inventory", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32)], ctypes.c_int32, True),
            ("tribal_village_market_buy_food", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32)], ctypes.c_int32, True),
            ("tribal_village_decay_market_prices", [ctypes.c_void_p], None, True),
            # Tech tree research actions
            ("tribal_village_research_blacksmith", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_research_university", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_research_castle", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_research_unit_upgrade", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            # Fog of war queries
            ("tribal_village_is_tile_revealed", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_get_revealed_tile_count", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_clear_revealed_map", [ctypes.c_void_p, ctypes.c_int32], None, True),
            # Tech tree state queries
            ("tribal_village_has_blacksmith_upgrade", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_has_university_tech", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_has_castle_tech", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_has_unit_upgrade", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            # Threat map queries
            ("tribal_village_has_known_threats", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_get_nearest_threat", [ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(ctypes.c_int32)], ctypes.c_int32, True),
            ("tribal_village_get_threats_in_range", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_get_threat_at", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32], ctypes.c_int32, True),
            # AI difficulty control
            ("tribal_village_get_difficulty_level", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_set_difficulty_level", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], None, True),
            ("tribal_village_get_difficulty", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_float, True),
            ("tribal_village_set_difficulty", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_float], None, True),
            ("tribal_village_set_adaptive_difficulty", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], None, True),
            ("tribal_village_get_decision_delay_chance", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_float, True),
            ("tribal_village_set_decision_delay_chance", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_float], None, True),
            ("tribal_village_enable_adaptive_difficulty", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_float], None, True),
            ("tribal_village_disable_adaptive_difficulty", [ctypes.c_void_p, ctypes.c_int32], None, True),
            ("tribal_village_is_adaptive_difficulty_enabled", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_get_adaptive_difficulty_target", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_float, True),
            ("tribal_village_get_threat_response_enabled", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_set_threat_response_enabled", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], None, True),
            ("tribal_village_get_advanced_targeting_enabled", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_set_advanced_targeting_enabled", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], None, True),
            ("tribal_village_get_coordination_enabled", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_set_coordination_enabled", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], None, True),
            ("tribal_village_get_optimal_build_order_enabled", [ctypes.c_void_p, ctypes.c_int32], ctypes.c_int32, True),
            ("tribal_village_set_optimal_build_order_enabled", [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32], None, True),
        ]

        for name, argtypes, restype, optional in func_specs:
            func = getattr(self.lib, name, None)
            if func is None and optional:
                continue
            if func is None:
                raise AttributeError(f"Required symbol missing: {name}")
            if argtypes is not None:
                func.argtypes = argtypes
            if restype is not None:
                func.restype = restype

    def _optional_ffi(self, name: str, *args, default=None):
        """Call an optional FFI function, returning default if it doesn't exist.

        argtypes/restype are already configured by _setup_ctypes_interface.
        """
        fn = getattr(self.lib, name, None)
        if fn is None:
            return default
        return fn(*args)

    @staticmethod
    def _c_int32(value: int) -> ctypes.c_int32:
        return ctypes.c_int32(value)

    def _optional_env_ffi(self, name: str, *args, default=None):
        return self._optional_ffi(name, self.env_ptr, *args, default=default)

    def _optional_env_i32(self, name: str, *args: int, default=None):
        return self._optional_env_ffi(
            name,
            *(self._c_int32(arg) for arg in args),
            default=default,
        )

    def _optional_env_bool(self, name: str, *args: int, default: bool = False) -> bool:
        return bool(self._optional_env_i32(name, *args, default=int(default)))

    def _research_at(self, name: str, agent_id: int, building_x: int, building_y: int) -> bool:
        return self._optional_env_bool(name, agent_id, building_x, building_y)

    def _get_team_flag(self, name: str, team_id: int) -> bool:
        return self._optional_env_bool(name, team_id)

    def _set_team_flag(self, name: str, team_id: int, enabled: bool) -> None:
        self._optional_env_i32(name, team_id, int(enabled))

    # --- Fog of war queries ---

    def is_tile_revealed(self, team_id: int, x: int, y: int) -> bool:
        """Check if a tile has been revealed by the specified team."""
        return self._optional_env_bool("tribal_village_is_tile_revealed", team_id, x, y)

    def get_revealed_tile_count(self, team_id: int) -> int:
        """Count how many tiles have been revealed by a team (exploration progress)."""
        return self._optional_env_i32("tribal_village_get_revealed_tile_count", team_id, default=0)

    def clear_revealed_map(self, team_id: int) -> None:
        """Clear the revealed map for a team."""
        self._optional_env_i32("tribal_village_clear_revealed_map", team_id)

    # --- Tech tree state queries ---

    def has_blacksmith_upgrade(self, team_id: int, upgrade_type: int) -> int:
        """Get current level (0-3) of a blacksmith upgrade for a team.

        upgrade_type: 0=MeleeAttack, 1=ArcherAttack, 2=InfantryArmor,
                      3=CavalryArmor, 4=ArcherArmor
        """
        return self._optional_env_i32(
            "tribal_village_has_blacksmith_upgrade",
            team_id,
            upgrade_type,
            default=0,
        )

    def has_university_tech(self, team_id: int, tech_type: int) -> bool:
        """Check if a university tech has been researched.

        tech_type: 0=Ballistics, 1=MurderHoles, 2=Masonry, 3=Architecture,
                   4=TreadmillCrane, 5=Arrowslits, 6=HeatedShot,
                   7=SiegeEngineers, 8=Chemistry
        """
        return self._optional_env_bool("tribal_village_has_university_tech", team_id, tech_type)

    def has_castle_tech(self, team_id: int, tech_type: int) -> bool:
        """Check if a castle unique tech has been researched.

        tech_type: 0-15, mapped as team*2=CastleAge, team*2+1=ImperialAge.
        """
        return self._optional_env_bool("tribal_village_has_castle_tech", team_id, tech_type)

    def has_unit_upgrade(self, team_id: int, upgrade_type: int) -> bool:
        """Check if a unit upgrade has been researched.

        upgrade_type: 0=LongSwordsman, 1=Champion, 2=LightCavalry,
                      3=Hussar, 4=Crossbowman, 5=Arbalester
        """
        return self._optional_env_bool("tribal_village_has_unit_upgrade", team_id, upgrade_type)

    # --- Tech tree research actions ---

    def research_blacksmith(self, agent_id: int, building_x: int, building_y: int) -> bool:
        """Research the next blacksmith upgrade. Returns True on success."""
        return self._research_at("tribal_village_research_blacksmith", agent_id, building_x, building_y)

    def research_university(self, agent_id: int, building_x: int, building_y: int) -> bool:
        """Research the next university tech. Returns True on success."""
        return self._research_at("tribal_village_research_university", agent_id, building_x, building_y)

    def research_castle(self, agent_id: int, building_x: int, building_y: int) -> bool:
        """Research the next castle unique tech. Returns True on success."""
        return self._research_at("tribal_village_research_castle", agent_id, building_x, building_y)

    def research_unit_upgrade(self, agent_id: int, building_x: int, building_y: int) -> bool:
        """Research the next unit upgrade at a military building. Returns True on success."""
        return self._research_at("tribal_village_research_unit_upgrade", agent_id, building_x, building_y)

    # --- Threat map queries ---

    def has_known_threats(self, team_id: int) -> bool:
        """Check if a team has any known (non-stale) threats.

        Returns True if there are active threats, False otherwise.
        """
        return self._get_team_flag("tribal_village_has_known_threats", team_id)

    def get_nearest_threat(self, agent_id: int) -> tuple[int, int, int]:
        """Get the nearest threat to an agent's current position.

        Returns (x, y, strength) of the nearest threat, or (-1, -1, 0) if none.
        """
        out_x, out_y, out_strength = ctypes.c_int32(), ctypes.c_int32(), ctypes.c_int32()
        found = self._optional_env_ffi(
            "tribal_village_get_nearest_threat",
            self._c_int32(agent_id),
            ctypes.byref(out_x), ctypes.byref(out_y), ctypes.byref(out_strength),
            default=0,
        )
        if found:
            return (out_x.value, out_y.value, out_strength.value)
        return (-1, -1, 0)

    def get_threats_in_range(self, agent_id: int, radius: int) -> int:
        """Get the number of threats within radius of an agent's position.

        Returns the count of non-stale threats in range.
        """
        return self._optional_env_i32("tribal_village_get_threats_in_range", agent_id, radius, default=0)

    def get_threat_at(self, team_id: int, x: int, y: int) -> int:
        """Get the threat strength at a specific map position for a team.

        Returns the strength value, or 0 if no threat at that position.
        """
        return self._optional_env_i32("tribal_village_get_threat_at", team_id, x, y, default=0)

    # --- AI Difficulty Control ---

    DIFFICULTY_LEVELS = ["Easy", "Normal", "Hard", "Brutal"]

    def get_difficulty_level(self, team_id: int) -> str:
        """Get the difficulty level for a team.

        Returns one of: "Easy", "Normal", "Hard", "Brutal"
        """
        level = self._optional_env_i32("tribal_village_get_difficulty_level", team_id, default=None)
        if level is None or not (0 <= level < len(self.DIFFICULTY_LEVELS)):
            return "Normal"
        return self.DIFFICULTY_LEVELS[level]

    def set_difficulty_level(self, team_id: int, level: str) -> None:
        """Set the difficulty level for a team.

        Args:
            team_id: The team ID
            level: One of "Easy", "Normal", "Hard", "Brutal"
        """
        level_idx = self.DIFFICULTY_LEVELS.index(level) if level in self.DIFFICULTY_LEVELS else 1
        self._optional_env_i32("tribal_village_set_difficulty_level", team_id, level_idx)

    def get_difficulty(self, team_id: int) -> float:
        """Get the difficulty for a team as a float.

        Returns: 0.0=Easy, 1.0=Normal, 2.0=Hard, 3.0=Brutal
        """
        return self._optional_env_ffi(
            "tribal_village_get_difficulty",
            self._c_int32(team_id),
            default=1.0,
        )

    def set_difficulty(self, team_id: int, difficulty: float) -> None:
        """Set the difficulty for a team using a float value.

        Args:
            team_id: The team ID
            difficulty: 0.0=Easy, 1.0=Normal, 2.0=Hard, 3.0=Brutal (rounded to nearest)
        """
        self._optional_env_ffi(
            "tribal_village_set_difficulty",
            self._c_int32(team_id),
            ctypes.c_float(difficulty),
        )

    def set_adaptive_difficulty(self, team_id: int, enabled: bool) -> None:
        """Enable or disable adaptive difficulty for a team.

        When enabled, uses a default target territory of 0.5 (balanced).
        Use enable_adaptive_difficulty() if you need a custom target.

        Args:
            team_id: The team ID
            enabled: True to enable, False to disable
        """
        self._set_team_flag("tribal_village_set_adaptive_difficulty", team_id, enabled)

    def get_decision_delay_chance(self, team_id: int) -> float:
        """Get the decision delay chance for a team (0.0-1.0).

        Higher values mean the AI is more likely to skip turns (easier AI).
        """
        return self._optional_env_ffi(
            "tribal_village_get_decision_delay_chance",
            self._c_int32(team_id),
            default=0.1,
        )

    def set_decision_delay_chance(self, team_id: int, chance: float) -> None:
        """Set a custom decision delay chance for a team (0.0-1.0).

        Args:
            team_id: The team ID
            chance: Probability of skipping a turn (0.0 = never, 1.0 = always)
        """
        self._optional_env_ffi(
            "tribal_village_set_decision_delay_chance",
            self._c_int32(team_id),
            ctypes.c_float(chance),
        )

    def enable_adaptive_difficulty(self, team_id: int, target_territory: float = 0.5) -> None:
        """Enable adaptive difficulty for a team.

        The AI will automatically adjust its difficulty level based on
        territory control compared to the target percentage.

        Args:
            team_id: The team ID
            target_territory: Target territory percentage (0.0-1.0, default 0.5 for balanced)
        """
        self._optional_env_ffi(
            "tribal_village_enable_adaptive_difficulty",
            self._c_int32(team_id),
            ctypes.c_float(target_territory),
        )

    def disable_adaptive_difficulty(self, team_id: int) -> None:
        """Disable adaptive difficulty for a team."""
        self._optional_env_i32("tribal_village_disable_adaptive_difficulty", team_id)

    def is_adaptive_difficulty_enabled(self, team_id: int) -> bool:
        """Check if adaptive difficulty is enabled for a team."""
        return self._get_team_flag("tribal_village_is_adaptive_difficulty_enabled", team_id)

    def get_adaptive_difficulty_target(self, team_id: int) -> float:
        """Get the target territory percentage for adaptive difficulty."""
        return self._optional_env_ffi(
            "tribal_village_get_adaptive_difficulty_target",
            self._c_int32(team_id),
            default=0.5,
        )

    def get_threat_response_enabled(self, team_id: int) -> bool:
        """Check if threat response intelligence is enabled for a team."""
        return self._get_team_flag("tribal_village_get_threat_response_enabled", team_id)

    def set_threat_response_enabled(self, team_id: int, enabled: bool) -> None:
        """Enable or disable threat response intelligence for a team."""
        self._set_team_flag("tribal_village_set_threat_response_enabled", team_id, enabled)

    def get_advanced_targeting_enabled(self, team_id: int) -> bool:
        """Check if advanced targeting is enabled for a team."""
        return self._get_team_flag("tribal_village_get_advanced_targeting_enabled", team_id)

    def set_advanced_targeting_enabled(self, team_id: int, enabled: bool) -> None:
        """Enable or disable advanced targeting for a team."""
        self._set_team_flag("tribal_village_set_advanced_targeting_enabled", team_id, enabled)

    def get_coordination_enabled(self, team_id: int) -> bool:
        """Check if inter-role coordination is enabled for a team."""
        return self._get_team_flag("tribal_village_get_coordination_enabled", team_id)

    def set_coordination_enabled(self, team_id: int, enabled: bool) -> None:
        """Enable or disable inter-role coordination for a team."""
        self._set_team_flag("tribal_village_set_coordination_enabled", team_id, enabled)

    def get_optimal_build_order_enabled(self, team_id: int) -> bool:
        """Check if optimal build order is enabled for a team."""
        return self._get_team_flag("tribal_village_get_optimal_build_order_enabled", team_id)

    def set_optimal_build_order_enabled(self, team_id: int, enabled: bool) -> None:
        """Enable or disable optimal build order for a team."""
        self._set_team_flag("tribal_village_set_optimal_build_order_enabled", team_id, enabled)

    AI_MODE_MAP = {"external": 0, "builtin": 1, "hybrid": 2}

    def _apply_ai_mode(self) -> None:
        """Set the AI controller mode in Nim based on config."""
        mode_int = self.AI_MODE_MAP.get(self._typed_config.ai_mode, 0)
        self._optional_ffi(
            "tribal_village_set_ai_mode",
            ctypes.c_int32(mode_int),
        )

    def _apply_nim_config(self) -> None:
        if not hasattr(self.lib, "tribal_village_set_config"):
            return
        cfg = NimConfig.from_config(self._typed_config)
        ok = self.lib.tribal_village_set_config(self.env_ptr, ctypes.byref(cfg))
        if ok != 1:
            raise RuntimeError("Failed to apply Nim environment config")

    def reset(
        self, seed: int | None = None, options: dict | None = None
    ) -> tuple[dict, dict]:
        """Ultra-fast reset using direct buffers."""
        self.step_count = 0
        self._apply_ai_mode()

        # Get PufferLib managed buffer pointers
        obs_ptr = self.observations.ctypes.data_as(ctypes.c_void_p)
        rewards_ptr = self.rewards.ctypes.data_as(ctypes.c_void_p)
        terminals_ptr = self.terminals.ctypes.data_as(ctypes.c_void_p)
        truncations_ptr = self.truncations.ctypes.data_as(ctypes.c_void_p)

        # Direct buffer reset - no conversions
        # Pass seed through FFI for deterministic world generation (0 = random)
        c_seed = ctypes.c_int32(seed if seed is not None else 0)
        success = self.lib.tribal_village_reset_and_get_obs(
            self.env_ptr, obs_ptr, rewards_ptr, terminals_ptr, truncations_ptr,
            c_seed
        )
        if not success:
            raise RuntimeError("Failed to reset Nim environment")

        # Return observations as views of PufferLib buffers (no copying!)
        observations = {
            f"agent_{i}": self.observations[i] for i in range(self.num_agents)
        }
        info = {f"agent_{i}": {} for i in range(self.num_agents)}

        return observations, info

    def step(
        self, actions: dict[str, np.ndarray]
    ) -> tuple[dict, dict, dict, dict, dict]:
        """Ultra-fast step using direct buffers."""
        self.step_count += 1

        # Clear actions buffer
        self.actions_buffer.fill(0)

        # Direct action setting (no dict overhead)
        for i in range(self.num_agents):
            agent_key = f"agent_{i}"
            if agent_key in actions:
                action_value = int(np.asarray(actions[agent_key]).reshape(()))
                if action_value < 0 or action_value >= self.single_action_space.n:
                    action_value = 0
                self.actions_buffer[i] = np.uint16(action_value)

        # Get PufferLib managed buffer pointers
        actions_ptr = self.actions_buffer.ctypes.data_as(ctypes.c_void_p)
        obs_ptr = self.observations.ctypes.data_as(ctypes.c_void_p)
        rewards_ptr = self.rewards.ctypes.data_as(ctypes.c_void_p)
        terminals_ptr = self.terminals.ctypes.data_as(ctypes.c_void_p)
        truncations_ptr = self.truncations.ctypes.data_as(ctypes.c_void_p)

        # Direct buffer step - no conversions
        success = self.lib.tribal_village_step_with_pointers(
            self.env_ptr,
            actions_ptr,
            obs_ptr,
            rewards_ptr,
            terminals_ptr,
            truncations_ptr,
        )
        if not success:
            raise RuntimeError("Failed to step Nim environment")

        # Return results as views of PufferLib buffers (no copying!)
        observations = {
            f"agent_{i}": self.observations[i] for i in range(self.num_agents)
        }
        rewards = {f"agent_{i}": float(self.rewards[i]) for i in range(self.num_agents)}
        terminated = {
            f"agent_{i}": bool(self.terminals[i]) for i in range(self.num_agents)
        }
        truncated = {
            f"agent_{i}": bool(self.truncations[i])
            or (self.step_count >= self.max_steps)
            for i in range(self.num_agents)
        }
        infos = {f"agent_{i}": {} for i in range(self.num_agents)}

        return observations, rewards, terminated, truncated, infos

    def close(self):
        """Clean up the environment."""
        if hasattr(self, "env_ptr") and self.env_ptr:
            self.lib.tribal_village_destroy(self.env_ptr)
            self.env_ptr = None


def make_tribal_village_env(
    config: dict[str, Any] | None = None, **kwargs
) -> TribalVillageEnv:
    """Factory function for ultra-fast tribal village environment."""
    if config is None:
        config = {}
    config.update(kwargs)
    return TribalVillageEnv(config=config)
