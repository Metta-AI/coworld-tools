"""Scenario test fixtures.

Scenario tests drive a real mettagrid rollout. We disable the LLM
worker in the default scenario run to keep tests hermetic (no
network calls, stable timing). An individual scenario that wants to
exercise the LLM path should clear these vars via monkeypatch.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("COGORA_ANTHROPIC_KEY", raising=False)
