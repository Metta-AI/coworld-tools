from __future__ import annotations

from types import SimpleNamespace

from players.cogsguard.buggy.obs_parser import ObsParser as BuggyObsParser
from players.cogsguard.cranky.obs_parser import ObsParser as CrankyObsParser
from players.cogsguard._shared.utils import add_inventory_token, split_power_suffix

from mettagrid.policy.policy_env_interface import PolicyEnvInterface


def _policy_env_info() -> PolicyEnvInterface:
    return PolicyEnvInterface(
        obs_features=[],
        tags=[],
        action_names=["noop"],
        vibe_action_names=[],
        num_agents=1,
        observation_shape=(1, 1),
        egocentric_shape=(3, 3),
    )


class _CrankyToken:
    def __init__(
        self,
        *,
        name: str,
        value: int,
        normalization: float = 256.0,
        is_global: bool = False,
        row: int = 1,
        col: int = 1,
    ) -> None:
        self.feature = SimpleNamespace(name=name, normalization=normalization)
        self.value = value
        self.is_global = is_global
        self._row = row
        self._col = col

    def row(self) -> int:
        return self._row

    def col(self) -> int:
        return self._col


def _buggy_token(
    *,
    name: str,
    value: int,
    normalization: float = 256.0,
    location: tuple[int, int] | None = None,
) -> object:
    loc = None
    if location is not None:
        loc = SimpleNamespace(row=location[0], col=location[1])
    return SimpleNamespace(
        feature=SimpleNamespace(name=name, normalization=normalization),
        value=value,
        location=loc,
    )


def test_split_power_suffix_requires_numeric_suffix() -> None:
    assert split_power_suffix("carbon:p2") == ("carbon", 2)
    assert split_power_suffix("own:policy") == ("own:policy", 0)


def test_add_inventory_token_reconstructs_and_keeps_non_power_names() -> None:
    inv: dict[str, int] = {}
    add_inventory_token(inv, "inv:energy", 34, token_value_base=100)
    add_inventory_token(inv, "inv:energy:p1", 12, token_value_base=100)
    add_inventory_token(inv, "inv:own:policy", 7, token_value_base=100)
    assert inv["energy"] == 1234
    assert inv["own:policy"] == 7


def test_cranky_obs_parser_uses_token_base_and_non_power_names() -> None:
    parser = CrankyObsParser(_policy_env_info())
    obs = SimpleNamespace(
        tokens=[
            _CrankyToken(name="inv:energy", value=34, normalization=100, is_global=True),
            _CrankyToken(name="inv:energy:p1", value=12, normalization=100, is_global=True),
            _CrankyToken(name="inv:own:policy", value=7, normalization=100, is_global=True),
            _CrankyToken(name="team:carbon", value=34, normalization=100, is_global=True),
            _CrankyToken(name="team:carbon:p1", value=12, normalization=100, is_global=True),
        ]
    )

    state, _ = parser.parse(obs, step=1, spawn_pos=(10, 20))  # type: ignore[arg-type]
    assert state.energy == 1234
    assert state.team_carbon == 1234


def test_buggy_obs_parser_uses_token_base_and_non_power_names() -> None:
    parser = BuggyObsParser(_policy_env_info())
    obs = SimpleNamespace(
        tokens=[
            _buggy_token(name="inv:energy", value=34, normalization=100, location=None),
            _buggy_token(name="inv:energy:p1", value=12, normalization=100, location=None),
            _buggy_token(name="inv:own:policy", value=7, normalization=100, location=None),
            _buggy_token(name="team:carbon", value=34, normalization=100, location=None),
            _buggy_token(name="team:carbon:p1", value=12, normalization=100, location=None),
        ]
    )

    state, _ = parser.parse(obs, step=1, spawn_pos=(10, 20))  # type: ignore[arg-type]
    assert state.energy == 1234
    assert state.team_carbon == 1234
