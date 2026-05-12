from __future__ import annotations

from types import SimpleNamespace

from agent_policies.policies.cyborg.cogsguard.cvc_debugger_robot.robot.perception import parse_observation


class _Feature:
  def __init__(self, name: str, normalization: int = 10) -> None:
    self.name = name
    self.normalization = normalization


class _Token:
  def __init__(self, name: str, value: int, location: tuple[int, int] | None = None) -> None:
    self.feature = _Feature(name)
    self.value = value
    self.location = location


def _obs(*tokens: _Token) -> SimpleNamespace:
  return SimpleNamespace(tokens=list(tokens), talk=[])


def test_parse_observation_reconstructs_territory_from_edge_tokens() -> None:
  scan = parse_observation(
    _obs(
      _Token("territory:here", 1),
      _Token("territory:east", 5, (1, 1)),
      _Token("territory:west", 7, (1, 2)),
    ),
    agent_pos=(10, 20),
    center=(1, 1),
    tag_names={},
  )

  assert scan.territory[(10, 19)] == 1
  assert scan.territory[(10, 20)] == 1
  assert scan.territory[(10, 21)] == 2


def test_parse_observation_uses_circular_obs_window() -> None:
  scan = parse_observation(
    _obs(_Token("territory:here", 1)),
    agent_pos=(10, 20),
    center=(1, 1),
    tag_names={},
  )

  assert (9, 19) not in scan.obs_window
  assert (9, 19) not in scan.territory
  assert (9, 20) in scan.obs_window
  assert (10, 19) in scan.obs_window
