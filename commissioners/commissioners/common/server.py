from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from commissioners.common.commissioners import (
    Commissioner,
    complete_round_for_round_start,
    describe_division_for_request,
    rank_division_for_request,
    round_completed_for_request,
    schedule_episodes_for_round_start,
    schedule_rounds_for_request,
)
from commissioners.common.protocol import (
    DescribeDivisionRequest,
    EpisodeFailed,
    EpisodeResult,
    RankDivisionRequest,
    RoundAbort,
    RoundCompletedRequest,
    RoundStart,
    ScheduleRoundsRequest,
)


def create_app(commissioner: Commissioner) -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/round")
    async def round_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        round_start: RoundStart | None = None
        expected_request_ids: set[str] = set()
        results_by_request_id: dict[str, EpisodeResult] = {}

        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "round_start":
                    round_start = RoundStart.model_validate(
                        {key: value for key, value in data.items() if key != "type"}
                    )
                    schedule = schedule_episodes_for_round_start(commissioner, round_start)
                    expected_request_ids = {episode.request_id for episode in schedule.episodes}
                    await websocket.send_json(schedule.to_json())
                    if not expected_request_ids:
                        await websocket.send_json(complete_round_for_round_start(commissioner, round_start, []).to_json())
                    continue

                if msg_type == "schedule_rounds_request":
                    request = ScheduleRoundsRequest.model_validate(
                        {key: value for key, value in data.items() if key != "type"}
                    )
                    await websocket.send_json(schedule_rounds_for_request(commissioner, request).to_json())
                    continue

                if msg_type == "rank_division_request":
                    request = RankDivisionRequest.model_validate(
                        {key: value for key, value in data.items() if key != "type"}
                    )
                    await websocket.send_json(rank_division_for_request(commissioner, request).to_json())
                    continue

                if msg_type == "describe_division_request":
                    request = DescribeDivisionRequest.model_validate(
                        {key: value for key, value in data.items() if key != "type"}
                    )
                    await websocket.send_json(describe_division_for_request(commissioner, request).to_json())
                    continue

                if msg_type == "round_completed_request":
                    request = RoundCompletedRequest.model_validate(
                        {key: value for key, value in data.items() if key != "type"}
                    )
                    await websocket.send_json(round_completed_for_request(commissioner, request).to_json())
                    continue

                if msg_type == "episode_result":
                    if round_start is None:
                        await websocket.close(code=1008, reason="episode_result received before round_start")
                        return
                    result = EpisodeResult.model_validate({key: value for key, value in data.items() if key != "type"})
                    results_by_request_id[result.request_id] = result
                elif msg_type == "episode_failed":
                    failed = EpisodeFailed.model_validate({key: value for key, value in data.items() if key != "type"})
                    if round_start is None:
                        await websocket.close(code=1008, reason="episode_failed received before round_start")
                        return
                    if expected_request_ids and failed.request_id not in expected_request_ids:
                        await websocket.close(code=1008, reason=f"unknown episode request id: {failed.request_id!r}")
                        return
                    await websocket.close(code=1011, reason=f"scheduled episode failed: {failed.request_id}")
                    return
                elif msg_type == "episodes_accepted":
                    continue
                elif msg_type == "episodes_rejected":
                    await websocket.close(code=1011, reason="platform rejected scheduled episodes")
                    return
                elif msg_type == "round_abort":
                    RoundAbort.model_validate({key: value for key, value in data.items() if key != "type"})
                    await websocket.close(code=1000)
                    return
                else:
                    await websocket.close(code=1008, reason=f"unknown message type: {msg_type!r}")
                    return

                completed_request_ids = set(results_by_request_id)
                if round_start is not None and expected_request_ids and expected_request_ids <= completed_request_ids:
                    ordered_results = [
                        results_by_request_id[request_id]
                        for request_id in sorted(
                            results_by_request_id,
                            key=lambda value: int(value) if value.isdigit() else value,
                        )
                    ]
                    await websocket.send_json(
                        complete_round_for_round_start(commissioner, round_start, ordered_results).to_json()
                    )
        except WebSocketDisconnect:
            return
        except (ValueError, ValidationError) as exc:
            await websocket.close(code=1008, reason=str(exc)[:120])

    return app
