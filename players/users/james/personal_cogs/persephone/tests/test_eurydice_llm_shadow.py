"""Tests for Eurydice offline LLM shadow evaluation."""

from __future__ import annotations

import json

from orpheus.belief_state import BeliefState, PlayerInfo
from orpheus.perception.types import Room, View

from agents.eurydice.llm_context import build_llm_context
from agents.eurydice.llm_provider import HeuristicProvider, HoldProvider
from agents.eurydice.llm_shadow import evaluate_contexts, load_contexts, summary_json
from agents.eurydice.pipeline import initialize_eurydice_state


def _context() -> dict:
    belief_state = BeliefState(
        tick=30,
        view=View.PLAYING,
        round=1,
        my_index=0,
        my_color=3,
        my_role="hades",
        my_team="shades",
        my_room=Room.UNDERWORLD,
        room=Room.UNDERWORLD,
        position=(10, 10),
        player_count=4,
    )
    initialize_eurydice_state(belief_state)
    belief_state.players[1] = PlayerInfo(
        position=(20, 10, belief_state.tick),
        room=Room.UNDERWORLD,
    )
    return build_llm_context(belief_state)


def test_shadow_evaluator_accepts_heuristic_probe_decision() -> None:
    summary = evaluate_contexts([_context()], HeuristicProvider())

    assert summary.contexts_total == 1
    assert summary.accepted == 1
    assert summary.rejected == 0
    assert summary.actions == {"probe_player": 1}
    assert summary.records[0].surface == "probe"
    json.loads(summary_json(summary))


def test_shadow_loader_reads_context_jsonl_and_event_wrapped_context(tmp_path) -> None:
    context = _context()
    path = tmp_path / "contexts.jsonl"
    path.write_text(
        json.dumps(context)
        + "\n"
        + json.dumps({"type": "llm_saved_context", "context": context})
        + "\n",
        encoding="utf-8",
    )

    contexts = load_contexts(path)

    assert len(contexts) == 2
    assert contexts[0]["schema_version"] == context["schema_version"]


def test_hold_provider_shadow_summary_is_valid() -> None:
    summary = evaluate_contexts([_context()], HoldProvider())

    assert summary.accepted == 1
    assert summary.actions == {"hold": 1}
