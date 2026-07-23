"""Shared fixtures over the synthetic episode in crewrift_analysis.testing."""

from __future__ import annotations

import pytest

from crewrift_analysis.events import Episode, parse_episode
from crewrift_analysis.testing import synthetic_lines


@pytest.fixture
def lines() -> list[str]:
    return synthetic_lines()


@pytest.fixture
def episode() -> Episode:
    return parse_episode(synthetic_lines(), episode_id="synthetic")
