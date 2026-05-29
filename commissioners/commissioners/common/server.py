from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from commissioners.common.commissioners import (
    Commissioner,
    complete_round_for_round_start,
    describe_division_for_request,
    episode_completed_for_request,
    on_episode_completed_for_round_start,
    rank_division_for_request,
    round_completed_for_request,
    schedule_episodes_for_round_start,
    schedule_rounds_for_request,
)
from commissioners.common.protocol import (
    DescribeDivisionRequest,
    EpisodeCompletedRequest,
    EpisodeFailed,
    EpisodeResult,
    RankDivisionRequest,
    RoundAbort,
    RoundCompletedRequest,
    RoundStart,
    ScheduleEpisodes,
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
        failed_by_request_id: dict[str, EpisodeFailed] = {}

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

                if msg_type == "episode_completed_request":
                    request = EpisodeCompletedRequest.model_validate(
                        {key: value for key, value in data.items() if key != "type"}
                    )
                    await websocket.send_json(episode_completed_for_request(commissioner, request).to_json())
                    continue

                episode_result: EpisodeResult | None = None
                episode_failed: EpisodeFailed | None = None
                if msg_type == "episode_result":
                    if round_start is None:
                        await websocket.close(code=1008, reason="episode_result received before round_start")
                        return
                    episode_result = EpisodeResult.model_validate(
                        {key: value for key, value in data.items() if key != "type"}
                    )
                    results_by_request_id[episode_result.request_id] = episode_result
                elif msg_type == "episode_failed":
                    if round_start is None:
                        await websocket.close(code=1008, reason="episode_failed received before round_start")
                        return
                    episode_failed = EpisodeFailed.model_validate(
                        {key: value for key, value in data.items() if key != "type"}
                    )
                    failed_by_request_id[episode_failed.request_id] = episode_failed
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

                if round_start is not None and (episode_result is not None or episode_failed is not None):
                    hook_response = on_episode_completed_for_round_start(
                        commissioner,
                        round_start,
                        episode_result=episode_result,
                        episode_failed=episode_failed,
                        completed_episode_results=list(results_by_request_id.values()),
                        failed_episodes=list(failed_by_request_id.values()),
                    )
                    if hook_response.episodes:
                        new_request_ids = {episode.request_id for episode in hook_response.episodes}
                        duplicate_request_ids = new_request_ids & expected_request_ids
                        if duplicate_request_ids:
                            await websocket.close(
                                code=1008,
                                reason=f"commissioner scheduled duplicate request ids: {sorted(duplicate_request_ids)}",
                            )
                            return
                        expected_request_ids.update(new_request_ids)
                        await websocket.send_json(ScheduleEpisodes(episodes=hook_response.episodes).to_json())
                        continue

                completed_request_ids = set(results_by_request_id) | set(failed_by_request_id)
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
