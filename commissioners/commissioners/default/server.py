"""FastAPI server implementing the Coworld commissioner WebSocket contract.

This is a *reference* commissioner: it speaks the same `/healthz` + `/round`
protocol the platform drives, schedules a single round-robin batch per division,
ranks policies by mean episode score, and optionally applies percentile
graduation. It is intentionally dependency-light (FastAPI + uvicorn only) and
exchanges raw JSON that matches the authoritative protocol models.

Authoritative contract (read these first):
- Role contract & lifecycle:
  https://github.com/Metta-AI/coworld/blob/main/src/coworld/docs/roles/COMMISSIONER.md
- Protocol message models:
  https://github.com/Metta-AI/coworld/blob/main/src/coworld/commissioner/protocol.py

Schema note: the number of player slots for a variant is the length of the
`tokens` array in the variant's `game_config` (see COMMISSIONER.md "variants").
We deliberately follow that current schema rather than any not-yet-merged
`num_agents` field.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, cast

from fastapi import FastAPI, WebSocket
from fastapi.responses import PlainTextResponse

from graduation import percentile_graduation
from strategies import round_robin_matchups

StrategyFn = Callable[..., list[dict[str, Any]]]

_STRATEGIES: dict[str, StrategyFn] = {
    "round_robin": round_robin_matchups,
}


def variant_num_agents(variant: dict[str, Any]) -> int:
    """Player-slot count for a variant: the length of its `game_config.tokens`.

    This mirrors how the platform derives agent count from the Coworld's
    `game.config_schema`. Raises if `tokens` is absent so misconfigured
    variants fail loudly instead of scheduling zero-slot episodes.
    """
    tokens = variant.get("game_config", {}).get("tokens")
    if not isinstance(tokens, list) or not tokens:
        raise ValueError(f"variant {variant.get('id')!r} has no non-empty game_config.tokens; cannot derive agent count")
    return len(tokens)


def _compute_division_rankings(
    episodes: list[dict[str, Any]],
    results_by_request: dict[str, dict[str, Any]],
    memberships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Average each policy's per-episode scores and rank them best-first."""
    player_id_by_policy = {m["policy_version_id"]: m.get("player_id") for m in memberships}

    scores: dict[str, list[float]] = defaultdict(list)
    for episode in episodes:
        result = results_by_request.get(episode["request_id"])
        if result is None:
            continue
        for score_entry in result["scores"]:
            scores[score_entry["policy_version_id"]].append(score_entry["score"])

    rankings = sorted(
        (
            {
                "policy_version_id": policy_id,
                "player_id": player_id_by_policy.get(policy_id),
                "score": sum(values) / len(values) if values else 0.0,
                "rank": 0,
            }
            for policy_id, values in scores.items()
        ),
        key=lambda entry: -cast(float, entry["score"]),
    )
    for rank, entry in enumerate(rankings, start=1):
        entry["rank"] = rank
    return rankings


def create_app(
    *,
    strategy: str = "round_robin",
    episodes_per_pair: int = 1,
    graduation: str = "none",
    promote_top_pct: int = 0,
    relegate_bottom_pct: int = 0,
) -> FastAPI:
    """Build the commissioner FastAPI app for the given configuration."""
    if strategy not in _STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}; supported: {sorted(_STRATEGIES)}")
    if graduation not in ("none", "percentile"):
        raise ValueError(f"unknown graduation {graduation!r}; supported: 'none', 'percentile'")

    strategy_fn = _STRATEGIES[strategy]
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.websocket("/round")
    async def round_handler(websocket: WebSocket) -> None:
        await websocket.accept()

        start = await websocket.receive_json()
        assert start["type"] == "round_start", f"expected round_start, got {start.get('type')!r}"

        divisions = start["divisions"]
        memberships = start["memberships"]
        variants = start["variants"]
        state = start.get("state")

        if not variants:
            await _send_round_complete(websocket, results=[], graduation_changes=[], state=state)
            return

        # Reference behavior: schedule every division on the first declared
        # variant. A custom commissioner can pick variants per division.
        variant = variants[0]
        num_agents = variant_num_agents(variant)

        episodes_by_division: dict[str, list[dict[str, Any]]] = {}
        all_episodes: list[dict[str, Any]] = []
        for division in divisions:
            division_id = division["id"]
            policy_version_ids = [m["policy_version_id"] for m in memberships if m["division_id"] == division_id]
            episodes = strategy_fn(
                policy_version_ids,
                variant_id=variant["id"],
                num_agents=num_agents,
                episodes_per_pair=episodes_per_pair,
            )
            if episodes:
                episodes_by_division[division_id] = episodes
                all_episodes.extend(episodes)

        if not all_episodes:
            await _send_round_complete(websocket, results=[], graduation_changes=[], state=state)
            return

        await websocket.send_json({"type": "schedule_episodes", "episodes": all_episodes})

        results_by_request = await _collect_results(websocket, {e["request_id"] for e in all_episodes})
        if results_by_request is None:  # round_abort
            return

        division_results: list[dict[str, Any]] = []
        graduation_changes: list[dict[str, Any]] = []
        for division_id, episodes in episodes_by_division.items():
            rankings = _compute_division_rankings(episodes, results_by_request, memberships)
            division_results.append({"division_id": division_id, "rankings": rankings})
            if graduation == "percentile":
                graduation_changes.extend(
                    percentile_graduation(
                        rankings,
                        memberships=memberships,
                        divisions=divisions,
                        current_division_id=division_id,
                        promote_top_pct=promote_top_pct,
                        relegate_bottom_pct=relegate_bottom_pct,
                    )
                )

        await _send_round_complete(
            websocket,
            results=division_results,
            graduation_changes=graduation_changes,
            state=state,
        )

    return app


async def _collect_results(
    websocket: WebSocket,
    pending: set[str],
) -> dict[str, dict[str, Any]] | None:
    """Drain platform messages until every scheduled episode resolves.

    Returns the map of request_id -> episode_result message, or None if the
    platform aborted the round (in which case we exit without round_complete).
    """
    results: dict[str, dict[str, Any]] = {}
    while pending:
        msg = await websocket.receive_json()
        msg_type = msg["type"]
        if msg_type == "episodes_accepted":
            continue
        if msg_type == "episodes_rejected":
            # Rejected requests will never produce a result; stop waiting on them.
            pending.difference_update(msg["request_ids"])
        elif msg_type == "episode_result":
            results[msg["request_id"]] = msg
            pending.discard(msg["request_id"])
        elif msg_type == "episode_failed":
            pending.discard(msg["request_id"])
        elif msg_type == "round_abort":
            return None
    return results


async def _send_round_complete(
    websocket: WebSocket,
    *,
    results: list[dict[str, Any]],
    graduation_changes: list[dict[str, Any]],
    state: Any,
) -> None:
    await websocket.send_json(
        {
            "type": "round_complete",
            "results": results,
            "graduation_changes": graduation_changes,
            "state": state,
        }
    )
