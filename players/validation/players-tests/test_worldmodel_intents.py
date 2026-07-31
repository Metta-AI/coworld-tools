"""Tests for players.player_sdk.worldmodel.intents (near-verbatim port of
``mas_memory.AgentIntent``/``IntentBoard`` from the sm-policies stack)."""

from __future__ import annotations

from players.player_sdk.worldmodel.intents import AgentIntent, IntentBoard


def intent(agent_id: int, role: str, goal: str, tick: int) -> AgentIntent:
    return AgentIntent(
        agent_id=agent_id,
        role=role,
        goal_type=goal,
        target_shared=(agent_id, agent_id),
        last_updated_tick=tick,
    )


def test_publish_get_and_republish() -> None:
    board = IntentBoard(stale_after=60)
    board.publish(intent(1, "miner", "mine", 10))
    assert board.get(1) is not None and board.get(1).goal_type == "mine"
    board.publish(intent(1, "miner", "deposit", 20))  # republish replaces
    assert board.get(1).goal_type == "deposit"
    assert board.get(9) is None


def test_fresh_prunes_stale_intents() -> None:
    board = IntentBoard(stale_after=60)
    board.publish(intent(1, "miner", "mine", 10))
    board.publish(intent(2, "scout", "scout", 100))
    fresh = board.fresh(current_tick=100)
    assert [i.agent_id for i in fresh] == [2]  # agent 1 aged out (10 < 40)
    # Boundary: last_updated_tick == cutoff is still fresh (>=).
    board.publish(intent(3, "miner", "mine", 40))
    assert {i.agent_id for i in board.fresh(100)} == {2, 3}


def test_role_counts_and_goal_queries() -> None:
    board = IntentBoard(stale_after=60)
    board.publish(intent(1, "miner", "mine", 100))
    board.publish(intent(2, "miner", "deposit", 100))
    board.publish(intent(3, "scout", "scout", 100))
    assert board.role_counts(100) == {"miner": 2, "scout": 1}
    miners_mining = board.agents_with_goal("mine", 100)
    assert [i.agent_id for i in miners_mining] == [1]
    assert board.agents_with_goal("mine", 100, exclude=1) == []
    board.clear()
    assert board.fresh(100) == []
