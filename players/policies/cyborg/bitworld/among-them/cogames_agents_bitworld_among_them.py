"""Screen-space scripted policies for BitWorld Among Them."""

from __future__ import annotations

import ctypes
import importlib
import os
import platform
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from pydantic import BaseModel, Field, field_validator

from mettagrid.bitworld import (
    BITWORLD_ACTION_COUNT,
    BITWORLD_ACTION_NAMES,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    bitworld_action_index,
    bitworld_action_name,
    encode_buttons,
)
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, AgentObservation

TASK_RADAR_COLOR = 8
CENTER_X = SCREEN_WIDTH // 2
CENTER_Y = SCREEN_HEIGHT // 2
TASK_ICON_TEMPLATE = np.asarray(
    [
        [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
        [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
        [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
        [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
        [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
        [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
        [-1, -1, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12],
        [12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12],
        [12, 12, 12, 5, 5, 13, 13, 13, 1, 1, 1, 1],
        [5, 13, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 13, 13, 13],
        [1, 1, 1, 1, 1, 13, 13, 13, 13, 13, 13, 13],
    ],
    dtype=np.int16,
)
TASK_ICON_MIN_MATCHES = int(np.count_nonzero(TASK_ICON_TEMPLATE >= 0))
TASK_ICON_TARGET_X_OFFSET = 6
TASK_ICON_TARGET_Y_OFFSET = 22
TASK_READY_DEADBAND = 8
TASK_SIGNAL_MEMORY_TICKS = 48
RADAR_MARGIN = 2
STEER_DEADBAND = 5
ACTION_PERIOD = 24
ACTION_WINDOW = 3
SCOUT_PATTERN_TICKS = 36
SCOUT_TASK_HOLD_TICKS = 88
SIGNAL_RUNNER_RADAR_MARGIN = 4
SIGNAL_RUNNER_STEER_DEADBAND = 6
SIGNAL_RUNNER_ACTION_PERIOD = 18
SIGNAL_RUNNER_ACTION_WINDOW = 4
SIGNAL_RUNNER_SWEEP_TICKS = 28
BEACON_SIGNAL_MEMORY_TICKS = 72
BEACON_TASK_HOLD_TICKS = 116
BEACON_ACTION_PERIOD = 10
BEACON_ACTION_WINDOW = 3
BEACON_SWEEP_TICKS = 22
BEACON_VOTE_LISTEN_TICKS = 8

STATE_HEADER_FEATURES = 22
STATE_GRID_SIZE = 32
STATE_PLAYER_FEATURES = 8
STATE_BODY_FEATURES = 8
STATE_TASK_FEATURES = 8
STATE_TASK_COUNT = 15
STATE_PLAYER_FEATURE_OFFSET = STATE_HEADER_FEATURES + STATE_GRID_SIZE * STATE_GRID_SIZE
STATE_BODY_FEATURE_OFFSET = STATE_PLAYER_FEATURE_OFFSET + STATE_PLAYER_FEATURES * 16
STATE_TASK_FEATURE_OFFSET = STATE_BODY_FEATURE_OFFSET + STATE_BODY_FEATURES * 16
STATE_FEATURES = STATE_TASK_FEATURE_OFFSET + STATE_TASK_FEATURES * STATE_TASK_COUNT

PHASE_PLAYING = 1
PHASE_VOTING = 2
PHASE_ROLE_REVEAL = 5
ROLE_IMPOSTER = 1
NOTTOODUMB_ROLE_IMPOSTER = 2
HEADER_SELF_ROLE = 4
HEADER_KILL_COOLDOWN = 9
HEADER_TASK_PROGRESS = 10
HEADER_VOTE_CURSOR = 16

KIND_PLAYER = 1
KIND_BODY = 2
KIND_TASK = 3
PLAYER_SELF = 2
PLAYER_ALIVE = 4
PLAYER_ROLE_IMPOSTER = 8
PLAYER_SELECTED = 64
TASK_INCOMPLETE = 2
TASK_ACTIVE = 4
TASK_ICON_VISIBLE = 8
TASK_ARROW_VISIBLE = 16
TASK_COMPLETED = 32

KILL_READY_BYTE = 255
TASK_HOLD_TICKS = 84
VOTE_SKIP_LISTEN_TICKS = 36
PIXEL_SKIP_RIGHT_PRESSES = 10
CHAT_COOLDOWN_TICKS = 72
NOTTOODUMB_DEBUG_STAT_NAMES = (
    "frame_tick",
    "localized",
    "interstitial",
    "role",
    "x",
    "y",
    "camera_lock",
    "camera_score",
    "mandatory_tasks",
    "radar_tasks",
    "checkout_tasks",
    "completed_tasks",
    "task_hold_ticks",
    "goal_index",
    "goal_x",
    "goal_y",
    "path_len",
    "visible_task_icons",
    "visible_crewmates",
    "last_mask",
    "velocity_x",
    "velocity_y",
    "has_goal",
)
BODY_REPORT_DISTANCE = 18
IMPOSTER_KILL_DISTANCE = 18
SUSPECT_NEAR_BODY_DISTANCE = 30
STATE_CLOSE_DISTANCE = 12
INTERSTITIAL_BLACK_PERCENT = 98
KILL_ICON_X = 1
KILL_ICON_Y = SCREEN_HEIGHT - 13
NOTTOODUMB_WARMUP_TICKS = 240
NOTTOODUMB_START_ACTION_TICKS = 30
NATIVE_ACE_SCOUT_SEED = 29
NATIVE_ACE_TASK_HOLD_TICKS = 132
NATIVE_ACE_ICON_RELEASE_GRACE_TICKS = 18
CHAMPION_ACTION_PERIOD = 4
PATHFINDER_SEED = 47
PATHFINDER_TASK_HOLD_TICKS = 132
PATHFINDER_ACTION_PERIOD = 12
PATHFINDER_ACTION_WINDOW = 4
PATHFINDER_ISOLATION_DISTANCE = 38
PATHFINDER_CROWD_DISTANCE = 58
SLEUTH_SEED = 47
SLEUTH_VOTE_LISTEN_TICKS = 24
SLEUTH_WITNESS_DISTANCE = 24
SLEUTH_HUNT_DISTANCE = 72
CIRCUIT_SENTINEL_SEED = 23
CIRCUIT_SENTINEL_ACTION_PERIOD = 6
CIRCUIT_SENTINEL_ACTION_WINDOW = 2
CIRCUIT_SENTINEL_TASK_HOLD_TICKS = 112
CIRCUIT_SENTINEL_VOTE_LISTEN_TICKS = 8
CIRCUIT_SENTINEL_CHAT_COOLDOWN_TICKS = 48
DEFAULT_OPENAI_MODEL = "gpt-4.1"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_BEDROCK_MODEL = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
AMONGTHEM_LLM_SYSTEM_PROMPT = (
    "You are the meeting chat brain for an Among Us-like BitWorld game. "
    "Return JSON only with key talk. talk must be printable ASCII, 75 characters or fewer. "
    "Crewmates should report facts, task progress, and body locations. "
    "If accusation_color is set, include the exact '<accusation_color> sus' phrase. "
    "Imposters should sound plausible, avoid confessing, and steer the lobby toward skip or weak suspicion. "
    "Use short in-game speech, no markdown."
)
PLAYER_COLOR_NAMES = (
    "red",
    "orange",
    "yellow",
    "light blue",
    "pink",
    "lime",
    "blue",
    "pale blue",
    "gray",
    "white",
    "dark brown",
    "brown",
    "dark teal",
    "green",
    "dark navy",
    "black",
)


def _action_index(*buttons: str) -> int:
    return bitworld_action_index(encode_buttons(buttons))


NOOP_ACTION = _action_index()
A_ACTION = _action_index("a")
LEFT_ACTION = _action_index("left")
RIGHT_ACTION = _action_index("right")
UP_ACTION = _action_index("up")
DOWN_ACTION = _action_index("down")
LEFT_A_ACTION = _action_index("left", "a")
RIGHT_A_ACTION = _action_index("right", "a")
UP_A_ACTION = _action_index("up", "a")
DOWN_A_ACTION = _action_index("down", "a")
UP_LEFT_ACTION = _action_index("up", "left")
UP_RIGHT_ACTION = _action_index("up", "right")
DOWN_LEFT_ACTION = _action_index("down", "left")
DOWN_RIGHT_ACTION = _action_index("down", "right")
UP_LEFT_A_ACTION = _action_index("up", "left", "a")
UP_RIGHT_A_ACTION = _action_index("up", "right", "a")
DOWN_LEFT_A_ACTION = _action_index("down", "left", "a")
DOWN_RIGHT_A_ACTION = _action_index("down", "right", "a")
ACTION_WITH_BUTTON = {
    NOOP_ACTION: A_ACTION,
    LEFT_ACTION: LEFT_A_ACTION,
    RIGHT_ACTION: RIGHT_A_ACTION,
    UP_ACTION: UP_A_ACTION,
    DOWN_ACTION: DOWN_A_ACTION,
    UP_LEFT_ACTION: UP_LEFT_A_ACTION,
    UP_RIGHT_ACTION: UP_RIGHT_A_ACTION,
    DOWN_LEFT_ACTION: DOWN_LEFT_A_ACTION,
    DOWN_RIGHT_ACTION: DOWN_RIGHT_A_ACTION,
}
CARDINAL_PATROL_ACTIONS = (RIGHT_ACTION, DOWN_ACTION, LEFT_ACTION, UP_ACTION)
DIAGONAL_PATROL_ACTIONS = (
    RIGHT_ACTION,
    DOWN_RIGHT_ACTION,
    DOWN_ACTION,
    DOWN_LEFT_ACTION,
    LEFT_ACTION,
    UP_LEFT_ACTION,
    UP_ACTION,
    UP_RIGHT_ACTION,
)


def _with_action_button(action: int) -> int:
    return ACTION_WITH_BUTTON.get(action, action)


def _visible_task_target(frame: np.ndarray) -> tuple[int, int] | None:
    windows = sliding_window_view(frame.astype(np.int16, copy=False), TASK_ICON_TEMPLATE.shape)
    scores = np.zeros(windows.shape[:2], dtype=np.int16)
    for color in (1, 5, 12, 13):
        scores += np.count_nonzero(windows[..., TASK_ICON_TEMPLATE == color] == color, axis=-1)
    best_score = int(scores.max())
    if best_score < TASK_ICON_MIN_MATCHES:
        return None

    ys, xs = np.nonzero(scores == best_score)
    targets_x = xs + TASK_ICON_TARGET_X_OFFSET
    targets_y = ys + TASK_ICON_TARGET_Y_OFFSET
    distances = np.abs(targets_x - CENTER_X) + np.abs(targets_y - CENTER_Y)
    best = int(np.argmin(distances))
    return int(targets_x[best]), int(targets_y[best])


def _visible_task_action(target_x: int, target_y: int) -> int:
    dx = target_x - CENTER_X
    dy = target_y - CENTER_Y
    if abs(dx) <= TASK_READY_DEADBAND and abs(dy) <= TASK_READY_DEADBAND:
        return A_ACTION
    if abs(dx) >= abs(dy):
        return LEFT_ACTION if dx < 0 else RIGHT_ACTION
    return UP_ACTION if dy < 0 else DOWN_ACTION


def _scout_radar_action(frame: np.ndarray) -> int:
    task_pixels = frame == TASK_RADAR_COLOR
    periphery = np.zeros_like(task_pixels)
    periphery[:RADAR_MARGIN, :] = True
    periphery[-RADAR_MARGIN:, :] = True
    periphery[:, :RADAR_MARGIN] = True
    periphery[:, -RADAR_MARGIN:] = True
    ys, xs = np.nonzero(task_pixels & periphery)
    if xs.size == 0:
        return NOOP_ACTION

    target_x = int(np.mean(xs))
    target_y = int(np.mean(ys))
    dx = target_x - CENTER_X
    dy = target_y - CENTER_Y
    if abs(dx) >= abs(dy):
        if dx < -STEER_DEADBAND:
            return LEFT_ACTION
        if dx > STEER_DEADBAND:
            return RIGHT_ACTION
    if dy < -STEER_DEADBAND:
        return UP_ACTION
    if dy > STEER_DEADBAND:
        return DOWN_ACTION
    return A_ACTION


def _scout_patrol_action(seed: int, tick: int, row: int) -> int:
    phase = ((tick + seed + row * 7) // SCOUT_PATTERN_TICKS) % 4
    return CARDINAL_PATROL_ACTIONS[phase]


def _scout_should_press_action(frame: np.ndarray, tick: int) -> bool:
    if tick % ACTION_PERIOD < ACTION_WINDOW:
        return True
    center = frame[CENTER_Y - 8 : CENTER_Y + 9, CENTER_X - 8 : CENTER_X + 9]
    return int(np.count_nonzero(center == TASK_RADAR_COLOR)) >= 4


def _resize_int_state(values: np.ndarray, batch_size: int, fill_value: int = 0) -> np.ndarray:
    if values.shape[0] == batch_size:
        return values
    resized = np.full(batch_size, fill_value, dtype=np.int64)
    preserved = min(batch_size, values.shape[0])
    resized[:preserved] = values[:preserved]
    return resized


def _declared_role_to_imposter(declared_role: str) -> bool | None:
    role = declared_role.strip().lower()
    if role == "auto":
        return None
    if role in {"imposter", "impostor"}:
        return True
    if role in {"crew", "crewmate"}:
        return False
    raise ValueError("declared_role must be one of: auto, imposter, impostor, crew, crewmate")


@dataclass
class _CyborgAgentState:
    tick: int = 0
    inferred_imposter: bool = False
    hold_ticks: int = 0
    vote_start_tick: int = -1
    vote_committed: bool = False
    talk_ready_tick: int = 0
    queued_chat: str = ""
    accusation_target_player: int = -1
    accusation_target_color: str = ""
    fake_patrol_offset: int = 0
    task_signal_ticks: int = 0
    pursuit_action: int = NOOP_ACTION


class AmongThemMeetingDirective(BaseModel):
    talk: str = Field(min_length=1, max_length=75)

    @field_validator("talk", mode="before")
    @classmethod
    def _normalize_talk(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = "".join(ch for ch in value.strip() if 0x20 <= ord(ch) < 0x7F)
        if len(normalized) <= 75:
            return normalized
        clipped = normalized[:75].rstrip()
        space_index = clipped.rfind(" ")
        if space_index >= 50:
            return clipped[:space_index]
        return clipped


def _resolve_api_key(*, direct_value: str | None, file_path: str | Path | None, env_var: str) -> str | None:
    if direct_value:
        stripped = direct_value.strip()
        if stripped:
            return stripped

    if file_path:
        path = Path(file_path)
        if path.is_file():
            return path.read_text().strip()

    value = os.getenv(env_var)
    if value:
        return value.strip()

    return None


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").lower() in {"1", "true", "yes", "on"}


def _get_default_openai_model() -> str:
    for env_var in ("AMONGTHEM_OPENAI_MODEL", "OPENAI_MODEL"):
        value = os.getenv(env_var)
        if value:
            stripped = value.strip()
            if stripped:
                return stripped
    return DEFAULT_OPENAI_MODEL


def _should_use_anthropic_bedrock(api_key: str | None) -> bool:
    return _env_flag_enabled("CLAUDE_CODE_USE_BEDROCK") or api_key is None


def _get_default_anthropic_model(*, api_key: str | None) -> str:
    model = os.getenv("ANTHROPIC_MODEL")
    if model:
        stripped = model.strip()
        if stripped:
            return stripped
    if _should_use_anthropic_bedrock(api_key):
        return DEFAULT_BEDROCK_MODEL
    return DEFAULT_ANTHROPIC_MODEL


def _build_openai_client(*, api_key: str | None) -> object:
    if api_key is None:
        raise ValueError("OpenAI API key is required for AmongThem LLM talk")

    OpenAI = importlib.import_module("openai").OpenAI
    return OpenAI(api_key=api_key)


def _build_anthropic_client(*, api_key: str | None) -> object:
    anthropic = importlib.import_module("anthropic")

    if _should_use_anthropic_bedrock(api_key):
        return anthropic.AnthropicBedrock(
            aws_profile=os.getenv("AWS_PROFILE"),
            aws_region=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION")),
        )

    if api_key is None:
        raise ValueError("Anthropic API key is required when Bedrock is disabled")

    return anthropic.Anthropic(api_key=api_key)


def _resolve_llm_provider(
    provider: str,
    *,
    client: object | None,
    api_key: str | None,
    api_key_file: str | None,
) -> str:
    provider = provider.lower()
    if provider != "auto":
        if provider not in {"openai", "anthropic"}:
            raise ValueError(f"Unsupported AmongThem LLM provider: {provider}")
        return provider
    if client is not None:
        return _infer_llm_provider_from_client(client)
    if _resolve_api_key(direct_value=api_key, file_path=api_key_file, env_var="OPENAI_API_KEY") is not None:
        return "openai"
    if _resolve_api_key(direct_value=api_key, file_path=api_key_file, env_var="ANTHROPIC_API_KEY") is not None:
        return "anthropic"
    if _should_use_anthropic_bedrock(None):
        return "anthropic"
    raise ValueError("AmongThem LLM talk requires OPENAI_API_KEY, ANTHROPIC_API_KEY, or Bedrock configuration")


def _infer_llm_provider_from_client(client: object) -> str:
    if hasattr(client, "messages"):
        return "anthropic"
    if hasattr(client, "chat"):
        return "openai"
    raise ValueError("AmongThem LLM auto provider could not infer provider from llm_client")


def _strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = stripped.removeprefix("```")
    if stripped.startswith("json"):
        stripped = stripped[4:]
    stripped = stripped.strip()
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


def _player_name(player_index: int) -> str:
    if player_index < 0:
        return ""
    return f"player_{player_index}"


def _player_color_name(color_index: int) -> str:
    if 0 <= color_index < len(PLAYER_COLOR_NAMES):
        return PLAYER_COLOR_NAMES[color_index]
    return _player_name(color_index)


def _accusation_color_from_chat(message: str) -> str:
    padded = f" {message.lower()} "
    for color in sorted(PLAYER_COLOR_NAMES, key=len, reverse=True):
        if f" sus {color} " in padded or f" {color} sus " in padded:
            return color
    return ""


def _render_meeting_prompt(
    *,
    agent_id: int,
    role: str,
    tick: int,
    queued_chat: str,
    vote_committed: bool,
    accusation_target: str,
    accusation_color: str,
) -> str:
    event = queued_chat.strip() if queued_chat.strip() else "no specific accusation"
    target = accusation_target.strip() if accusation_target.strip() else "none"
    color = accusation_color.strip() if accusation_color.strip() else "none"
    return "\n".join(
        [
            f"agent_id: {agent_id}",
            f"role: {role}",
            f"policy_tick: {tick}",
            f"vote_committed: {vote_committed}",
            f"known_event: {event}",
            f"accusation_target: {target}",
            f"accusation_color: {color}",
            "default_vote_plan: skip unless there is strong evidence",
        ]
    )


class AmongThemOpenAITalkController:
    def __init__(
        self,
        *,
        client: object | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_key_file: str | None = None,
        max_tokens: int = 80,
        temperature: float = 0.4,
    ) -> None:
        resolved_api_key = _resolve_api_key(
            direct_value=api_key,
            file_path=api_key_file,
            env_var="OPENAI_API_KEY",
        )
        self._client: Any = client if client is not None else _build_openai_client(api_key=resolved_api_key)
        self._model = model or _get_default_openai_model()
        self._max_tokens = int(max_tokens)
        self._temperature = float(temperature)

    def meeting_talk(self, *, agent_id: int, state: _CyborgAgentState) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": AMONGTHEM_LLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _render_meeting_prompt(
                        agent_id=agent_id,
                        role="imposter" if state.inferred_imposter else "crewmate",
                        tick=state.tick,
                        queued_chat=state.queued_chat,
                        vote_committed=state.vote_committed,
                        accusation_target=_player_name(state.accusation_target_player),
                        accusation_color=state.accusation_target_color,
                    ),
                },
            ],
        )
        content = str(response.choices[0].message.content or "")
        return AmongThemMeetingDirective.model_validate_json(_strip_markdown_code_fence(content)).talk


class AmongThemAnthropicTalkController:
    def __init__(
        self,
        *,
        client: object | None = None,
        model: str | None = None,
        api_key: str | None = None,
        api_key_file: str | None = None,
        max_tokens: int = 80,
        temperature: float = 0.4,
    ) -> None:
        resolved_api_key = _resolve_api_key(
            direct_value=api_key,
            file_path=api_key_file,
            env_var="ANTHROPIC_API_KEY",
        )
        self._client: Any = client if client is not None else _build_anthropic_client(api_key=resolved_api_key)
        self._model = model or _get_default_anthropic_model(api_key=resolved_api_key)
        self._max_tokens = int(max_tokens)
        self._temperature = float(temperature)

    def meeting_talk(self, *, agent_id: int, state: _CyborgAgentState) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=AMONGTHEM_LLM_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": _render_meeting_prompt(
                        agent_id=agent_id,
                        role="imposter" if state.inferred_imposter else "crewmate",
                        tick=state.tick,
                        queued_chat=state.queued_chat,
                        vote_committed=state.vote_committed,
                        accusation_target=_player_name(state.accusation_target_player),
                        accusation_color=state.accusation_target_color,
                    ),
                }
            ],
        )
        content = "".join(
            str(getattr(block, "text", ""))
            for block in getattr(response, "content", [])
            if isinstance(getattr(block, "text", None), str)
        )
        return AmongThemMeetingDirective.model_validate_json(_strip_markdown_code_fence(content)).talk


class _NotTooDumbCore:
    def __init__(self, policy_env_info: PolicyEnvInterface, library_path: Path):
        self._lib = ctypes.CDLL(str(library_path))
        self._lib.nottoodumb_new_policy.argtypes = [ctypes.c_int]
        self._lib.nottoodumb_new_policy.restype = ctypes.c_int
        self._lib.nottoodumb_step_batch.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._lib.nottoodumb_step_batch.restype = None
        self._lib.nottoodumb_take_chat.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._lib.nottoodumb_take_chat.restype = ctypes.c_int
        self._lib.nottoodumb_role.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.nottoodumb_role.restype = ctypes.c_int
        self._lib.nottoodumb_debug_stats.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._lib.nottoodumb_debug_stats.restype = ctypes.c_int
        self._num_agents = max(1, int(policy_env_info.num_agents))
        self._handle = int(self._lib.nottoodumb_new_policy(self._num_agents))

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        observations = self._normalize_observations(raw_observations)
        agent_id_array = np.arange(observations.shape[0], dtype=np.int32)
        frame_advance_array = np.ones(agent_id_array.shape[0], dtype=np.int32)
        actions = np.zeros(agent_id_array.shape[0], dtype=np.int32)
        self._num_agents = max(self._num_agents, int(agent_id_array.max(initial=-1)) + 1)
        self._lib.nottoodumb_step_batch(
            self._handle,
            agent_id_array.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
            ctypes.c_int(agent_id_array.shape[0]),
            ctypes.c_int(self._num_agents),
            ctypes.c_int(observations.shape[1]),
            ctypes.c_int(observations.shape[2]),
            ctypes.c_int(observations.shape[3]),
            ctypes.c_void_p(frame_advance_array.ctypes.data),
            ctypes.c_void_p(observations.ctypes.data),
            ctypes.c_void_p(actions.ctypes.data),
        )
        raw_actions[:] = actions.astype(raw_actions.dtype, copy=False)

    def take_chat(self, agent_id: int) -> str:
        buffer = ctypes.create_string_buffer(128)
        length = int(
            self._lib.nottoodumb_take_chat(
                self._handle,
                ctypes.c_int(agent_id),
                ctypes.c_void_p(ctypes.addressof(buffer)),
                ctypes.c_int(len(buffer)),
            )
        )
        if length <= 0:
            return ""
        return bytes(buffer.raw[:length]).decode("ascii")

    def role(self, agent_id: int) -> int:
        return int(self._lib.nottoodumb_role(self._handle, ctypes.c_int(agent_id)))

    def debug_stats(self, agent_id: int) -> dict[str, float]:
        values = np.zeros(len(NOTTOODUMB_DEBUG_STAT_NAMES), dtype=np.int32)
        count = int(
            self._lib.nottoodumb_debug_stats(
                self._handle,
                ctypes.c_int(agent_id),
                ctypes.c_void_p(values.ctypes.data),
                ctypes.c_int(values.shape[0]),
            )
        )
        return {name: float(values[index]) for index, name in enumerate(NOTTOODUMB_DEBUG_STAT_NAMES[:count])}

    def _normalize_observations(self, observations: np.ndarray) -> np.ndarray:
        if observations.ndim == 4:
            normalized = observations
        elif observations.ndim == 3:
            normalized = observations[:, np.newaxis, :, :]
        elif observations.ndim == 2:
            normalized = self._unpack_packed_frames(observations)[:, np.newaxis, :, :]
        else:
            raise ValueError(f"Expected BitWorld observations with 2, 3, or 4 dimensions, got {observations.ndim}.")
        if normalized.shape[2:] != (SCREEN_HEIGHT, SCREEN_WIDTH):
            raise ValueError(f"Expected {SCREEN_HEIGHT}x{SCREEN_WIDTH} BitWorld frames.")
        return np.ascontiguousarray(normalized, dtype=np.uint8)

    def _unpack_packed_frames(self, observations: np.ndarray) -> np.ndarray:
        packed = np.ascontiguousarray(observations, dtype=np.uint8)
        pixels = np.empty((packed.shape[0], packed.shape[1] * 2), dtype=np.uint8)
        pixels[:, 0::2] = packed & 0x0F
        pixels[:, 1::2] = packed >> 4
        return pixels.reshape(packed.shape[0], SCREEN_HEIGHT, SCREEN_WIDTH)


def _state_frames(observations: np.ndarray) -> np.ndarray:
    if observations.ndim == 2 and observations.shape[1] % STATE_FEATURES == 0:
        frame_stack = observations.shape[1] // STATE_FEATURES
        return observations.reshape(observations.shape[0], frame_stack, STATE_FEATURES)[:, -1, :]
    if observations.ndim == 3 and observations.shape[2] == STATE_FEATURES:
        return observations[:, -1, :]
    raise ValueError(f"Expected BitWorld state observations, got shape {observations.shape}")


def _is_state_observation(observations: np.ndarray) -> bool:
    return (observations.ndim == 2 and observations.shape[1] % STATE_FEATURES == 0) or (
        observations.ndim == 3 and observations.shape[2] == STATE_FEATURES
    )


def _screen_move_toward(target_x: int, target_y: int, *, deadband: int = STATE_CLOSE_DISTANCE) -> int:
    dx = target_x - CENTER_X
    dy = target_y - CENTER_Y
    if abs(dx) <= deadband and abs(dy) <= deadband:
        return A_ACTION
    if abs(dx) >= abs(dy):
        return RIGHT_ACTION if dx > 0 else LEFT_ACTION
    return DOWN_ACTION if dy > 0 else UP_ACTION


def _nottoodumb_library_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "libnottoodumb.dylib"
    if system == "Windows":
        return "nottoodumb.dll"
    return "libnottoodumb.so"


def _nottoodumb_library_path() -> Path | None:
    library_name = _nottoodumb_library_name()
    configured = os.environ.get("BITWORLD_NOTTOODUMB_LIBRARY")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    repo_path = os.environ.get("BITWORLD_REPO_PATH")
    if repo_path:
        candidates.append(Path(repo_path) / "among_them" / "players" / library_name)
    candidates.extend(
        [
            Path("/opt/bitworld") / "among_them" / "players" / library_name,
            Path.home() / "bitworld" / "among_them" / "players" / library_name,
            Path.home() / "Code" / "bitworld" / "among_them" / "players" / library_name,
            Path.home() / "Code" / "work" / "bitworld" / "among_them" / "players" / library_name,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


class _BitWorldAmongThemScoutAgentPolicy(AgentPolicy):
    def __init__(self, policy_env_info: PolicyEnvInterface, parent: "BitWorldAmongThemScoutPolicy"):
        super().__init__(policy_env_info)
        self._parent = parent

    def step(self, obs: AgentObservation) -> Action:
        del obs
        return Action(name=self._policy_env_info.action_names[A_ACTION])


class BitWorldAmongThemScoutPolicy(MultiAgentPolicy):
    """A lightweight Among Them pixel bot inspired by ``nottoodumb.nim``.

    The Nim reference keeps a full map lock and A* path. This policy keeps the
    same submit-friendly contract but uses only the live pixel frame: chase the
    yellow task radar on the screen edge, periodically press action near goals,
    and fall back to a deterministic patrol when no task signal is visible.
    """

    short_names = ["bitworld_among_them_scout"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", *, seed: int = 0):
        super().__init__(policy_env_info, device=device)
        if tuple(policy_env_info.action_names) != BITWORLD_ACTION_NAMES:
            raise ValueError(
                f"BitWorld Among Them scout requires the {BITWORLD_ACTION_COUNT}-action BitWorld action space"
            )
        self._seed = int(seed)
        self._ticks = np.zeros(0, dtype=np.int64)
        self._task_hold_ticks = np.zeros(0, dtype=np.int64)
        self._task_signal_ticks = np.zeros(0, dtype=np.int64)

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        del agent_id
        return _BitWorldAmongThemScoutAgentPolicy(self._policy_env_info, self)

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        frames = self._latest_frames(raw_observations)
        self._resize_state(frames.shape[0])
        for row, frame in enumerate(frames):
            tick = int(self._ticks[row])
            raw_actions[row] = self._choose_action(frame, tick, row)
        self._ticks += 1

    def _resize_state(self, batch_size: int) -> None:
        if self._ticks.shape[0] == batch_size:
            return
        resized_ticks = np.zeros(batch_size, dtype=np.int64)
        resized_holds = np.zeros(batch_size, dtype=np.int64)
        resized_signals = np.zeros(batch_size, dtype=np.int64)
        preserved = min(batch_size, self._ticks.shape[0])
        resized_ticks[:preserved] = self._ticks[:preserved]
        resized_holds[:preserved] = self._task_hold_ticks[:preserved]
        resized_signals[:preserved] = self._task_signal_ticks[:preserved]
        self._ticks = resized_ticks
        self._task_hold_ticks = resized_holds
        self._task_signal_ticks = resized_signals

    def _latest_frames(self, observations: np.ndarray) -> np.ndarray:
        if observations.ndim == 4:
            return observations[:, -1, :, :]
        if observations.ndim == 3:
            return observations
        if observations.ndim == 2:
            return self._unpack_packed_frames(observations)
        raise ValueError(f"Expected BitWorld observations with 2, 3, or 4 dimensions, got {observations.ndim}")

    def _unpack_packed_frames(self, observations: np.ndarray) -> np.ndarray:
        flat = observations.astype(np.uint8, copy=False)
        pixels = np.empty((flat.shape[0], flat.shape[1] * 2), dtype=np.uint8)
        pixels[:, 0::2] = flat & 0x0F
        pixels[:, 1::2] = flat >> 4
        return pixels.reshape(flat.shape[0], SCREEN_HEIGHT, SCREEN_WIDTH)

    def _choose_action(self, frame: np.ndarray, tick: int, row: int) -> int:
        if self._task_hold_ticks[row] > 0:
            self._task_hold_ticks[row] -= 1
            return A_ACTION

        radar_action = self._radar_action(frame)
        if radar_action == NOOP_ACTION and self._task_signal_ticks[row] > 0:
            self._task_signal_ticks[row] -= 1
        elif radar_action != NOOP_ACTION:
            self._task_signal_ticks[row] = TASK_SIGNAL_MEMORY_TICKS

        task_target = _visible_task_target(frame) if self._task_signal_ticks[row] > 0 else None
        if task_target is not None:
            action = _visible_task_action(*task_target)
            if action == A_ACTION:
                self._task_hold_ticks[row] = SCOUT_TASK_HOLD_TICKS - 1
                return A_ACTION
            return _with_action_button(action)

        action = radar_action
        if action == NOOP_ACTION:
            action = self._patrol_action(tick, row)
        if self._should_press_action(frame, tick):
            return _with_action_button(action)
        return action

    def _radar_action(self, frame: np.ndarray) -> int:
        return _scout_radar_action(frame)

    def _patrol_action(self, tick: int, row: int) -> int:
        return _scout_patrol_action(self._seed, tick, row)

    def _should_press_action(self, frame: np.ndarray, tick: int) -> bool:
        return _scout_should_press_action(frame, tick)


class BitWorldAmongThemSignalRunnerPolicy(BitWorldAmongThemScoutPolicy):
    """Task-radar follower with diagonal steering and an eight-way sweep fallback."""

    short_names = ["amongthem_signal_runner"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", *, seed: int | str = 11):
        super().__init__(policy_env_info, device=device, seed=int(seed))

    def _radar_action(self, frame: np.ndarray) -> int:
        task_pixels = frame == TASK_RADAR_COLOR
        periphery = np.zeros_like(task_pixels)
        periphery[:SIGNAL_RUNNER_RADAR_MARGIN, :] = True
        periphery[-SIGNAL_RUNNER_RADAR_MARGIN:, :] = True
        periphery[:, :SIGNAL_RUNNER_RADAR_MARGIN] = True
        periphery[:, -SIGNAL_RUNNER_RADAR_MARGIN:] = True
        ys, xs = np.nonzero(task_pixels & periphery)
        if xs.size == 0:
            return NOOP_ACTION

        dx = int(np.mean(xs)) - CENTER_X
        dy = int(np.mean(ys)) - CENTER_Y
        horizontal = abs(dx) > SIGNAL_RUNNER_STEER_DEADBAND
        vertical = abs(dy) > SIGNAL_RUNNER_STEER_DEADBAND
        if horizontal and vertical:
            if dx < 0 and dy < 0:
                return UP_LEFT_ACTION
            if dx > 0 and dy < 0:
                return UP_RIGHT_ACTION
            if dx < 0 and dy > 0:
                return DOWN_LEFT_ACTION
            return DOWN_RIGHT_ACTION
        if horizontal:
            return LEFT_ACTION if dx < 0 else RIGHT_ACTION
        if vertical:
            return UP_ACTION if dy < 0 else DOWN_ACTION
        return A_ACTION

    def _patrol_action(self, tick: int, row: int) -> int:
        phase = ((tick + self._seed + row * 5) // SIGNAL_RUNNER_SWEEP_TICKS) % 8
        return (
            RIGHT_ACTION,
            DOWN_RIGHT_ACTION,
            DOWN_ACTION,
            DOWN_LEFT_ACTION,
            LEFT_ACTION,
            UP_LEFT_ACTION,
            UP_ACTION,
            UP_RIGHT_ACTION,
        )[phase]

    def _should_press_action(self, frame: np.ndarray, tick: int) -> bool:
        if tick % SIGNAL_RUNNER_ACTION_PERIOD < SIGNAL_RUNNER_ACTION_WINDOW:
            return True
        center = frame[CENTER_Y - 10 : CENTER_Y + 11, CENTER_X - 10 : CENTER_X + 11]
        return int(np.count_nonzero(center == TASK_RADAR_COLOR)) >= 3


class _BitWorldAmongThemCyborgAgentPolicy(AgentPolicy):
    def __init__(self, policy_env_info: PolicyEnvInterface, parent: "BitWorldAmongThemCyborgPolicy", agent_id: int):
        super().__init__(policy_env_info)
        self._parent = parent
        self._agent_id = agent_id

    def step(self, obs: AgentObservation) -> Action:
        del obs
        return Action(
            name=bitworld_action_name(self._parent.next_action(self._agent_id)),
            talk=self._parent.next_chat(self._agent_id),
        )


class BitWorldAmongThemCyborgPolicy(MultiAgentPolicy):
    """AmongThem starter with task play, imposter play, voting, and meeting chat.

    This uses the local ``nottoodumb`` Nim core for live pixel frames when it is
    available, and falls back to Python state/pixel heuristics that fit the
    CoGames policy bundle contract.
    """

    short_names = ["bitworld_among_them_cyborg", "amongthem_cyborg"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        *,
        seed: int = 0,
        vote_listen_ticks: int = VOTE_SKIP_LISTEN_TICKS,
        chat_cooldown_ticks: int = CHAT_COOLDOWN_TICKS,
        use_nim_core: bool = True,
        llm_talk: bool | None = None,
        llm_provider: str = "auto",
        llm_client: object | None = None,
        llm_model: str | None = None,
        llm_api_key: str | None = None,
        llm_api_key_file: str | None = None,
        llm_max_tokens: int = 80,
        llm_temperature: float = 0.4,
        declared_role: str = "auto",
    ):
        super().__init__(policy_env_info, device=device)
        if tuple(policy_env_info.action_names) != BITWORLD_ACTION_NAMES:
            raise ValueError(
                f"BitWorld Among Them cyborg requires the {BITWORLD_ACTION_COUNT}-action BitWorld action space"
            )
        self._seed = int(seed)
        self._vote_listen_ticks = int(vote_listen_ticks)
        self._chat_cooldown_ticks = int(chat_cooldown_ticks)
        self._declared_imposter = _declared_role_to_imposter(declared_role)
        self._states: dict[int, _CyborgAgentState] = {}
        self._last_actions: dict[int, int] = {}
        self._last_chats: dict[int, str] = {}
        library_path = _nottoodumb_library_path() if use_nim_core and self._declared_imposter is None else None
        self._nim_core = _NotTooDumbCore(policy_env_info, library_path) if library_path is not None else None
        self._llm_talk = _env_flag_enabled("AMONGTHEM_LLM_TALK") if llm_talk is None else bool(llm_talk)
        self._llm_talk_controller = None
        if self._llm_talk:
            provider = _resolve_llm_provider(
                llm_provider,
                client=llm_client,
                api_key=llm_api_key,
                api_key_file=llm_api_key_file,
            )
            controller_class = (
                AmongThemOpenAITalkController if provider == "openai" else AmongThemAnthropicTalkController
            )
            self._llm_talk_controller = controller_class(
                client=llm_client,
                model=llm_model,
                api_key=llm_api_key,
                api_key_file=llm_api_key_file,
                max_tokens=llm_max_tokens,
                temperature=llm_temperature,
            )

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        return _BitWorldAmongThemCyborgAgentPolicy(self._policy_env_info, self, agent_id)

    def next_action(self, agent_id: int) -> int:
        if agent_id not in self._last_actions:
            state = self._state(agent_id)
            self._last_actions[agent_id] = self._patrol_action(state, agent_id)
        return self._last_actions[agent_id]

    def next_chat(self, agent_id: int) -> str | None:
        if agent_id in self._last_chats:
            return self._last_chats[agent_id]
        return None

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        agent_ids = range(raw_observations.shape[0])
        self._last_chats = {}
        if _is_state_observation(raw_observations):
            frames = _state_frames(raw_observations)
            for row, agent_id in enumerate(agent_ids):
                state = self._state(int(agent_id))
                raw_actions[row] = self._choose_state_action(frames[row], state, int(agent_id))
                self._after_step(state, int(agent_id), int(raw_actions[row]), 1)
            return

        frames = self._latest_pixel_frames(raw_observations)
        if self._nim_core is not None and self._declared_imposter is None:
            self._nim_core.step_batch(raw_observations, raw_actions)
            for row, agent_id in enumerate(agent_ids):
                state = self._state(int(agent_id))
                self._sync_nim_core_state(state, int(agent_id))
                if self._nim_core.debug_stats(int(agent_id)).get("interstitial", 0.0) > 0.0:
                    self._meeting_talk(state, int(agent_id))
                else:
                    state.vote_start_tick = -1
                    state.vote_committed = False
                self._after_step(state, int(agent_id), int(raw_actions[row]), 1)
            return

        for row, agent_id in enumerate(agent_ids):
            state = self._state(int(agent_id))
            raw_actions[row] = self._choose_pixel_action(frames[row], state, int(agent_id))
            self._after_step(state, int(agent_id), int(raw_actions[row]), 1)

    def bitworld_chat_messages(self, agent_ids: Sequence[int]) -> list[str | None]:
        return [self._last_chats[agent_id] if agent_id in self._last_chats else None for agent_id in agent_ids]

    def bitworld_debug_stats(self, agent_ids: Sequence[int]) -> list[dict[str, float]]:
        if self._nim_core is None:
            return [{} for _agent_id in agent_ids]
        return [self._nim_core.debug_stats(int(agent_id)) for agent_id in agent_ids]

    def _state(self, agent_id: int) -> _CyborgAgentState:
        if agent_id not in self._states:
            self._states[agent_id] = _CyborgAgentState(
                inferred_imposter=self._declared_imposter is True,
                fake_patrol_offset=(self._seed + agent_id * 11) % 4,
            )
        return self._states[agent_id]

    def _mark_imposter_if_auto(self, state: _CyborgAgentState) -> None:
        if self._declared_imposter is None:
            state.inferred_imposter = True

    def _after_step(self, state: _CyborgAgentState, agent_id: int, action: int, frame_advance: int) -> None:
        self._last_actions[agent_id] = action
        state.tick += max(1, int(frame_advance))

    def _sync_nim_core_state(self, state: _CyborgAgentState, agent_id: int) -> None:
        assert self._nim_core is not None
        if self._declared_imposter is None:
            state.inferred_imposter = self._nim_core.role(agent_id) == NOTTOODUMB_ROLE_IMPOSTER
        pending_chat = self._nim_core.take_chat(agent_id)
        if not pending_chat:
            return
        state.queued_chat = pending_chat
        accusation_color = _accusation_color_from_chat(pending_chat)
        if accusation_color:
            state.accusation_target_color = accusation_color

    def _latest_pixel_frames(self, observations: np.ndarray) -> np.ndarray:
        if observations.ndim == 4:
            return observations[:, -1, :, :]
        if observations.ndim == 3:
            return observations
        if observations.ndim == 2:
            return self._unpack_packed_frames(observations)
        raise ValueError(f"Expected BitWorld pixel observations with 2, 3, or 4 dimensions, got {observations.ndim}")

    def _unpack_packed_frames(self, observations: np.ndarray) -> np.ndarray:
        flat = observations.astype(np.uint8, copy=False)
        pixels = np.empty((flat.shape[0], flat.shape[1] * 2), dtype=np.uint8)
        pixels[:, 0::2] = flat & 0x0F
        pixels[:, 1::2] = flat >> 4
        return pixels.reshape(flat.shape[0], SCREEN_HEIGHT, SCREEN_WIDTH)

    def _choose_state_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        phase = int(frame[0])
        if phase == PHASE_ROLE_REVEAL:
            if self._declared_imposter is None:
                state.inferred_imposter = int(frame[HEADER_SELF_ROLE]) == ROLE_IMPOSTER
            return NOOP_ACTION
        if phase == PHASE_VOTING:
            return self._state_vote_action(frame, state, agent_id)

        state.vote_start_tick = -1
        state.vote_committed = False
        if phase != PHASE_PLAYING:
            return NOOP_ACTION

        if int(frame[HEADER_SELF_ROLE]) == ROLE_IMPOSTER or int(frame[HEADER_KILL_COOLDOWN]) > 0:
            self._mark_imposter_if_auto(state)

        players = self._state_players(frame)
        bodies = self._state_bodies(frame)
        if state.inferred_imposter:
            return self._state_imposter_action(frame, state, agent_id, players, bodies)
        return self._state_crewmate_action(frame, state, agent_id, players, bodies)

    def _state_players(self, frame: np.ndarray) -> np.ndarray:
        return frame[STATE_PLAYER_FEATURE_OFFSET:STATE_BODY_FEATURE_OFFSET].reshape(16, STATE_PLAYER_FEATURES)

    def _state_bodies(self, frame: np.ndarray) -> np.ndarray:
        return frame[STATE_BODY_FEATURE_OFFSET:STATE_TASK_FEATURE_OFFSET].reshape(16, STATE_BODY_FEATURES)

    def _state_tasks(self, frame: np.ndarray) -> np.ndarray:
        return frame[STATE_TASK_FEATURE_OFFSET:STATE_FEATURES].reshape(STATE_TASK_COUNT, STATE_TASK_FEATURES)

    def _state_crewmate_action(
        self,
        frame: np.ndarray,
        state: _CyborgAgentState,
        agent_id: int,
        players: np.ndarray,
        bodies: np.ndarray,
    ) -> int:
        body = self._nearest_state_body(bodies)
        if body is not None:
            self._queue_body_evidence(state, body, players)
            if self._distance_from_center(int(body[1]), int(body[2])) <= BODY_REPORT_DISTANCE:
                state.hold_ticks = 0
                return A_ACTION
            return _screen_move_toward(int(body[1]), int(body[2]), deadband=BODY_REPORT_DISTANCE)

        if state.hold_ticks > 0 or int(frame[HEADER_TASK_PROGRESS]) > 0:
            state.hold_ticks = max(0, state.hold_ticks - 1)
            return A_ACTION

        task = self._best_state_task(frame)
        if task is None:
            return self._patrol_action(state, agent_id)

        flags = int(task[3])
        if flags & TASK_ACTIVE:
            state.hold_ticks = TASK_HOLD_TICKS
            return A_ACTION
        if flags & TASK_ICON_VISIBLE:
            target_x = int(task[1]) + 6
            target_y = int(task[2]) + 18
            if self._distance_from_center(target_x, target_y) <= STATE_CLOSE_DISTANCE:
                state.hold_ticks = TASK_HOLD_TICKS
                return A_ACTION
            return self._with_periodic_action(_screen_move_toward(target_x, target_y), state)
        if flags & TASK_ARROW_VISIBLE:
            return self._with_periodic_action(_screen_move_toward(int(task[5]), int(task[6])), state)
        return self._patrol_action(state, agent_id)

    def _state_imposter_action(
        self,
        frame: np.ndarray,
        state: _CyborgAgentState,
        agent_id: int,
        players: np.ndarray,
        bodies: np.ndarray,
    ) -> int:
        body = self._nearest_state_body(bodies)
        if body is not None:
            return self._away_from(int(body[1]), int(body[2]), state, agent_id)

        visible_targets = self._visible_living_targets(players)
        kill_ready = int(frame[HEADER_KILL_COOLDOWN]) == KILL_READY_BYTE
        if kill_ready and len(visible_targets) == 1:
            target = visible_targets[0]
            target_x = int(target[1])
            target_y = int(target[2])
            if self._distance_from_center(target_x, target_y) <= IMPOSTER_KILL_DISTANCE:
                state.queued_chat = ""
                return A_ACTION
            return _screen_move_toward(target_x, target_y, deadband=IMPOSTER_KILL_DISTANCE)

        if state.tick % 96 < 24:
            return self._with_periodic_action(self._patrol_action(state, agent_id), state)
        return self._patrol_action(state, agent_id)

    def _state_vote_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        if state.vote_start_tick < 0:
            state.vote_start_tick = state.tick
            state.vote_committed = False
        self._meeting_talk(state, agent_id)
        if state.vote_committed:
            return NOOP_ACTION

        players = self._state_players(frame)
        player_count = int(np.count_nonzero(players[:, 0] == KIND_PLAYER))
        skip_cursor = player_count + 1
        target_cursor = self._vote_target_cursor(players, state, skip_cursor)
        cursor = int(frame[HEADER_VOTE_CURSOR])
        elapsed = state.tick - state.vote_start_tick
        if cursor != target_cursor:
            return RIGHT_ACTION if elapsed % 2 == 0 else NOOP_ACTION
        if elapsed < self._vote_listen_ticks:
            return NOOP_ACTION
        state.vote_committed = True
        return A_ACTION

    def _choose_pixel_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        if self._looks_like_interstitial(frame):
            return self._pixel_vote_action(state, agent_id)

        if self._looks_like_kill_icon(frame):
            self._mark_imposter_if_auto(state)
        if state.inferred_imposter:
            return self._pixel_imposter_action(frame, state, agent_id)

        action = self._radar_action(frame)
        if action == NOOP_ACTION:
            if self._task_signal_near_center(frame):
                return A_ACTION
            return self._patrol_action(state, agent_id)
        if action == A_ACTION or self._task_signal_near_center(frame):
            return A_ACTION
        return action

    def _pixel_vote_action(self, state: _CyborgAgentState, agent_id: int) -> int:
        if state.vote_start_tick < 0:
            state.vote_start_tick = state.tick
            state.vote_committed = False
        self._meeting_talk(state, agent_id)
        if state.vote_committed:
            return NOOP_ACTION

        elapsed = state.tick - state.vote_start_tick
        skip_walk_ticks = PIXEL_SKIP_RIGHT_PRESSES * 2
        if elapsed < skip_walk_ticks:
            return RIGHT_ACTION if elapsed % 2 == 0 else NOOP_ACTION
        if elapsed < skip_walk_ticks + self._vote_listen_ticks:
            return NOOP_ACTION
        state.vote_committed = True
        return A_ACTION

    def _pixel_imposter_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        if self._looks_like_kill_icon(frame) and state.tick % 80 < 4:
            return A_ACTION
        return self._patrol_action(state, agent_id)

    def _radar_action(self, frame: np.ndarray) -> int:
        task_pixels = frame == TASK_RADAR_COLOR
        periphery = np.zeros_like(task_pixels)
        periphery[:RADAR_MARGIN, :] = True
        periphery[-RADAR_MARGIN:, :] = True
        periphery[:, :RADAR_MARGIN] = True
        periphery[:, -RADAR_MARGIN:] = True
        ys, xs = np.nonzero(task_pixels & periphery)
        if xs.size == 0:
            return NOOP_ACTION

        target_x = int(np.mean(xs))
        target_y = int(np.mean(ys))
        return _screen_move_toward(target_x, target_y, deadband=STEER_DEADBAND)

    def _best_state_task(self, frame: np.ndarray) -> np.ndarray | None:
        tasks = self._state_tasks(frame)
        candidates = []
        for task in tasks:
            if int(task[0]) != KIND_TASK:
                continue
            flags = int(task[3])
            if flags & TASK_COMPLETED or not flags & TASK_INCOMPLETE:
                continue
            if flags & TASK_ACTIVE:
                return task
            if flags & TASK_ICON_VISIBLE:
                candidates.append((0, self._distance_from_center(int(task[1]) + 6, int(task[2]) + 18), task))
            elif flags & TASK_ARROW_VISIBLE:
                candidates.append((1, self._distance_from_center(int(task[5]), int(task[6])), task))
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
        return candidates[0][2]

    def _nearest_state_body(self, bodies: np.ndarray) -> np.ndarray | None:
        candidates = [body for body in bodies if int(body[0]) == KIND_BODY]
        if not candidates:
            return None
        candidates.sort(key=lambda body: self._distance_from_center(int(body[1]), int(body[2])))
        return candidates[0]

    def _queue_body_evidence(self, state: _CyborgAgentState, body: np.ndarray, players: np.ndarray) -> None:
        state.queued_chat = "body reported"
        state.accusation_target_player = -1
        state.accusation_target_color = ""
        suspect = self._sole_suspect_near_body(body, players)
        if suspect is None:
            return
        suspect_index, suspect_color = suspect
        state.accusation_target_player = suspect_index
        state.accusation_target_color = suspect_color
        state.queued_chat = f"body reported; {suspect_color} sus"

    def _sole_suspect_near_body(self, body: np.ndarray, players: np.ndarray) -> tuple[int, str] | None:
        body_x = int(body[1])
        body_y = int(body[2])
        body_color = int(body[3])
        candidates = []
        for player_index, player in enumerate(players):
            if int(player[0]) != KIND_PLAYER:
                continue
            flags = int(player[4])
            if flags & PLAYER_SELF or not flags & PLAYER_ALIVE:
                continue
            color = int(player[3])
            if color == body_color:
                continue
            distance = abs(int(player[1]) - body_x) + abs(int(player[2]) - body_y)
            if distance <= SUSPECT_NEAR_BODY_DISTANCE:
                candidates.append((player_index, _player_color_name(color)))
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _vote_target_cursor(self, players: np.ndarray, state: _CyborgAgentState, skip_cursor: int) -> int:
        target = state.accusation_target_player
        if not 0 <= target < players.shape[0]:
            return skip_cursor
        player = players[target]
        if int(player[0]) != KIND_PLAYER:
            return skip_cursor
        flags = int(player[4])
        if flags & PLAYER_SELF or not flags & PLAYER_ALIVE:
            return skip_cursor
        return target + 1

    def _visible_living_targets(self, players: np.ndarray) -> list[np.ndarray]:
        targets = []
        for player in players:
            if int(player[0]) != KIND_PLAYER:
                continue
            flags = int(player[4])
            if flags & PLAYER_SELF or not flags & PLAYER_ALIVE:
                continue
            targets.append(player)
        return targets

    def _meeting_talk(self, state: _CyborgAgentState, agent_id: int) -> None:
        if state.tick < state.talk_ready_tick:
            return
        if self._llm_talk_controller is not None and state.queued_chat.strip():
            message = self._llm_talk_controller.meeting_talk(agent_id=agent_id, state=state)
        else:
            message = state.queued_chat.strip() if state.queued_chat else "skip unless sus"
        self._last_chats[agent_id] = message[:75]
        state.queued_chat = ""
        state.talk_ready_tick = state.tick + self._chat_cooldown_ticks

    def _patrol_action(self, state: _CyborgAgentState, agent_id: int) -> int:
        phase = ((state.tick + self._seed + state.fake_patrol_offset + agent_id * 3) // SCOUT_PATTERN_TICKS) % 4
        return CARDINAL_PATROL_ACTIONS[phase]

    def _with_periodic_action(self, action: int, state: _CyborgAgentState) -> int:
        if state.tick % ACTION_PERIOD >= ACTION_WINDOW:
            return action
        return self._with_action_button(action)

    def _with_action_button(self, action: int) -> int:
        if action == NOOP_ACTION:
            return A_ACTION
        if action == LEFT_ACTION:
            return LEFT_A_ACTION
        if action == RIGHT_ACTION:
            return RIGHT_A_ACTION
        if action == UP_ACTION:
            return UP_A_ACTION
        if action == DOWN_ACTION:
            return DOWN_A_ACTION
        return action

    def _away_from(self, x: int, y: int, state: _CyborgAgentState, agent_id: int) -> int:
        dx = CENTER_X - x
        dy = CENTER_Y - y
        if abs(dx) <= STATE_CLOSE_DISTANCE and abs(dy) <= STATE_CLOSE_DISTANCE:
            return self._patrol_action(state, agent_id)
        if abs(dx) >= abs(dy):
            return RIGHT_ACTION if dx > 0 else LEFT_ACTION
        return DOWN_ACTION if dy > 0 else UP_ACTION

    def _distance_from_center(self, x: int, y: int) -> int:
        return abs(x - CENTER_X) + abs(y - CENTER_Y)

    def _looks_like_interstitial(self, frame: np.ndarray) -> bool:
        return int(np.count_nonzero(frame == 0)) * 100 >= INTERSTITIAL_BLACK_PERCENT * frame.size

    def _looks_like_kill_icon(self, frame: np.ndarray) -> bool:
        icon = frame[KILL_ICON_Y : KILL_ICON_Y + 12, KILL_ICON_X : KILL_ICON_X + 12]
        return int(np.count_nonzero((icon == 8) | (icon == 2) | (icon == 4))) >= 10

    def _task_signal_near_center(self, frame: np.ndarray) -> bool:
        center = frame[CENTER_Y - 8 : CENTER_Y + 9, CENTER_X - 8 : CENTER_X + 9]
        return int(np.count_nonzero(center == TASK_RADAR_COLOR)) >= 4


class BitWorldAmongThemBeaconPolicy(BitWorldAmongThemCyborgPolicy):
    """Bundle-clean pixel policy that follows task beacons and skips meetings."""

    short_names = ["bitworld_among_them_beacon"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        *,
        seed: int | str = 23,
        vote_listen_ticks: int | str = BEACON_VOTE_LISTEN_TICKS,
        declared_role: str = "auto",
    ):
        super().__init__(
            policy_env_info,
            device=device,
            seed=int(seed),
            vote_listen_ticks=int(vote_listen_ticks),
            declared_role=declared_role,
            use_nim_core=False,
            llm_talk=False,
        )

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        if _is_state_observation(raw_observations):
            super().step_batch(raw_observations, raw_actions)
            return

        self._last_chats = {}
        frames = self._latest_pixel_frames(raw_observations)
        for row, frame in enumerate(frames):
            state = self._state(row)
            raw_actions[row] = self._choose_beacon_pixel_action(frame, state, row)
            self._after_step(state, row, int(raw_actions[row]), 1)

    def _choose_beacon_pixel_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        if int(np.count_nonzero(frame == 0)) * 100 >= INTERSTITIAL_BLACK_PERCENT * frame.size:
            state.hold_ticks = 0
            state.task_signal_ticks = 0
            return self._beacon_vote_action(state, agent_id)

        state.vote_start_tick = -1
        state.vote_committed = False
        if self._looks_like_kill_icon(frame):
            self._mark_imposter_if_auto(state)
        if state.inferred_imposter:
            if self._looks_like_kill_icon(frame) and state.tick % BEACON_ACTION_PERIOD < BEACON_ACTION_WINDOW:
                return A_ACTION
            return self._beacon_patrol_action(state, agent_id)

        if state.hold_ticks > 0:
            state.hold_ticks -= 1
            return A_ACTION

        radar_action = self._beacon_radar_action(frame)
        if radar_action == NOOP_ACTION and state.task_signal_ticks > 0:
            state.task_signal_ticks -= 1
        elif radar_action != NOOP_ACTION:
            state.task_signal_ticks = BEACON_SIGNAL_MEMORY_TICKS
            state.pursuit_action = radar_action

        task_target = _visible_task_target(frame) if state.task_signal_ticks > 0 else None
        if task_target is not None:
            action = _visible_task_action(*task_target)
            if action == A_ACTION:
                state.hold_ticks = BEACON_TASK_HOLD_TICKS - 1
                return A_ACTION
            state.pursuit_action = action
            if self._beacon_should_press_action(frame, state.tick):
                return _with_action_button(action)
            return action

        if radar_action != NOOP_ACTION:
            action = radar_action
        elif state.task_signal_ticks > 0:
            action = state.pursuit_action
        else:
            action = self._beacon_patrol_action(state, agent_id)
        if self._beacon_should_press_action(frame, state.tick):
            return _with_action_button(action)
        return action

    def _beacon_radar_action(self, frame: np.ndarray) -> int:
        task_pixels = frame == TASK_RADAR_COLOR
        periphery = np.zeros_like(task_pixels)
        periphery[:SIGNAL_RUNNER_RADAR_MARGIN, :] = True
        periphery[-SIGNAL_RUNNER_RADAR_MARGIN:, :] = True
        periphery[:, :SIGNAL_RUNNER_RADAR_MARGIN] = True
        periphery[:, -SIGNAL_RUNNER_RADAR_MARGIN:] = True
        ys, xs = np.nonzero(task_pixels & periphery)
        if xs.size == 0:
            return NOOP_ACTION

        dx = int(np.mean(xs)) - CENTER_X
        dy = int(np.mean(ys)) - CENTER_Y
        horizontal = abs(dx) > SIGNAL_RUNNER_STEER_DEADBAND
        vertical = abs(dy) > SIGNAL_RUNNER_STEER_DEADBAND
        if horizontal and vertical:
            if dx < 0 and dy < 0:
                return UP_LEFT_ACTION
            if dx > 0 and dy < 0:
                return UP_RIGHT_ACTION
            if dx < 0 and dy > 0:
                return DOWN_LEFT_ACTION
            return DOWN_RIGHT_ACTION
        if horizontal:
            return LEFT_ACTION if dx < 0 else RIGHT_ACTION
        if vertical:
            return UP_ACTION if dy < 0 else DOWN_ACTION
        return A_ACTION

    def _beacon_patrol_action(self, state: _CyborgAgentState, agent_id: int) -> int:
        phase = ((state.tick + self._seed + state.fake_patrol_offset + agent_id * 5) // BEACON_SWEEP_TICKS) % 8
        return DIAGONAL_PATROL_ACTIONS[phase]

    def _beacon_should_press_action(self, frame: np.ndarray, tick: int) -> bool:
        if tick % BEACON_ACTION_PERIOD < BEACON_ACTION_WINDOW:
            return True
        center = frame[CENTER_Y - 10 : CENTER_Y + 11, CENTER_X - 10 : CENTER_X + 11]
        return int(np.count_nonzero(center == TASK_RADAR_COLOR)) >= 3

    def _beacon_vote_action(self, state: _CyborgAgentState, agent_id: int) -> int:
        if state.vote_start_tick < 0:
            state.vote_start_tick = state.tick
            state.vote_committed = False
            state.queued_chat = "doing tasks; skip unless sus"
        self._meeting_talk(state, agent_id)
        if state.vote_committed:
            return NOOP_ACTION

        elapsed = state.tick - state.vote_start_tick
        skip_walk_ticks = PIXEL_SKIP_RIGHT_PRESSES * 2
        if elapsed < skip_walk_ticks:
            return RIGHT_ACTION if elapsed % 2 == 0 else NOOP_ACTION
        if elapsed < skip_walk_ticks + self._vote_listen_ticks:
            return NOOP_ACTION
        state.vote_committed = True
        return A_ACTION


class BitWorldAmongThemCircuitSentinelPolicy(BitWorldAmongThemCyborgPolicy):
    """Portable task runner with state play and pixel visible-task fallback."""

    short_names = ["amongthem_circuit_sentinel"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        *,
        seed: int | str = CIRCUIT_SENTINEL_SEED,
        vote_listen_ticks: int | str = CIRCUIT_SENTINEL_VOTE_LISTEN_TICKS,
        chat_cooldown_ticks: int | str = CIRCUIT_SENTINEL_CHAT_COOLDOWN_TICKS,
        declared_role: str = "auto",
    ):
        super().__init__(
            policy_env_info,
            device=device,
            seed=int(seed),
            vote_listen_ticks=int(vote_listen_ticks),
            chat_cooldown_ticks=int(chat_cooldown_ticks),
            declared_role=declared_role,
            use_nim_core=False,
            llm_talk=False,
        )

    def _choose_pixel_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        if state.hold_ticks > 0:
            state.hold_ticks -= 1
            return A_ACTION

        task_target = _visible_task_target(frame)
        has_task_signal = task_target is not None or bool(np.any(frame == TASK_RADAR_COLOR))
        has_kill_icon = self._looks_like_kill_icon(frame)
        if self._looks_like_interstitial(frame) and not has_task_signal and not has_kill_icon:
            state.hold_ticks = 0
            return self._pixel_vote_action(state, agent_id)

        if has_kill_icon:
            self._mark_imposter_if_auto(state)
        if state.inferred_imposter:
            return self._pixel_imposter_action(frame, state, agent_id)

        if task_target is not None:
            action = _visible_task_action(*task_target)
            if action == A_ACTION:
                state.hold_ticks = CIRCUIT_SENTINEL_TASK_HOLD_TICKS - 1
                return A_ACTION
            return _with_action_button(action)

        action = self._radar_action(frame)
        if action == NOOP_ACTION:
            if self._task_signal_near_center(frame):
                state.hold_ticks = CIRCUIT_SENTINEL_TASK_HOLD_TICKS - 1
                return A_ACTION
            return self._patrol_action(state, agent_id)
        if action == A_ACTION or self._task_signal_near_center(frame):
            state.hold_ticks = CIRCUIT_SENTINEL_TASK_HOLD_TICKS - 1
            return A_ACTION
        return self._with_periodic_action(action, state)

    def _pixel_imposter_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        if self._looks_like_kill_icon(frame) and state.tick % 32 < 8:
            return A_ACTION
        return self._with_periodic_action(self._patrol_action(state, agent_id), state)

    def _patrol_action(self, state: _CyborgAgentState, agent_id: int) -> int:
        phase = ((state.tick + self._seed + state.fake_patrol_offset + agent_id * 5) // SIGNAL_RUNNER_SWEEP_TICKS) % 8
        return DIAGONAL_PATROL_ACTIONS[phase]

    def _with_periodic_action(self, action: int, state: _CyborgAgentState) -> int:
        if state.tick % CIRCUIT_SENTINEL_ACTION_PERIOD < CIRCUIT_SENTINEL_ACTION_WINDOW:
            return _with_action_button(action)
        return action


class _BitWorldAmongThemNotTooDumbAgentPolicy(AgentPolicy):
    def __init__(self, policy_env_info: PolicyEnvInterface, parent: "BitWorldAmongThemNotTooDumbPolicy", agent_id: int):
        super().__init__(policy_env_info)
        self._parent = parent
        self._agent_id = agent_id

    def step(self, obs: AgentObservation) -> Action:
        del obs
        action_index = self._parent.step_agent(self._agent_id)
        return Action(name=self._policy_env_info.action_names[action_index])


class BitWorldAmongThemNotTooDumbPolicy(MultiAgentPolicy):
    """Cogames wrapper around BitWorld's native NotTooDumb Among Them bot."""

    short_names = ["bitworld_among_them_nottoodumb"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu"):
        super().__init__(policy_env_info, device=device)
        if tuple(policy_env_info.action_names) != BITWORLD_ACTION_NAMES:
            raise ValueError(
                f"BitWorld Among Them NotTooDumb requires the {BITWORLD_ACTION_COUNT}-action BitWorld action space"
            )
        library_path = _nottoodumb_library_path()
        if library_path is None:
            raise FileNotFoundError("BitWorld NotTooDumb shared library was not found")
        self._core = _NotTooDumbCore(policy_env_info, library_path)
        self._last_actions = np.zeros(int(policy_env_info.num_agents), dtype=np.int32)
        self._ticks = np.zeros(int(policy_env_info.num_agents), dtype=np.int64)

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        return _BitWorldAmongThemNotTooDumbAgentPolicy(self._policy_env_info, self, agent_id)

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        if raw_observations.shape[0] == 0:
            return
        agent_ids = range(raw_observations.shape[0])
        self._ensure_agent_count(raw_observations.shape[0])
        observations = self._core._normalize_observations(raw_observations)
        self._core.step_batch(raw_observations, raw_actions)
        self._postprocess_native_actions(observations, raw_actions, agent_ids)
        for row, agent_id in enumerate(agent_ids):
            self._ticks[agent_id] += 1
            self._last_actions[agent_id] = raw_actions[row]

    def step_agent(self, agent_id: int) -> int:
        return int(self._last_actions[agent_id])

    def _ensure_agent_count(self, count: int) -> None:
        if count <= self._last_actions.shape[0]:
            return
        self._last_actions = _resize_int_state(self._last_actions, count).astype(np.int32, copy=False)
        self._ticks = _resize_int_state(self._ticks, count)

    def _warmup_action(self, agent_id: int) -> int:
        tick = int(self._ticks[agent_id])
        if tick < NOTTOODUMB_START_ACTION_TICKS:
            return A_ACTION
        phase = ((tick - NOTTOODUMB_START_ACTION_TICKS) // SCOUT_PATTERN_TICKS + agent_id) % 4
        return CARDINAL_PATROL_ACTIONS[phase]

    def _is_native_interstitial(self, agent_id: int) -> bool:
        return self._core.debug_stats(agent_id).get("interstitial", 0.0) > 0.0

    def _postprocess_native_actions(
        self, observations: np.ndarray, actions: np.ndarray, agent_ids: Sequence[int]
    ) -> None:
        del observations
        for row, agent_id in enumerate(agent_ids):
            if actions[row] == NOOP_ACTION and self._ticks[agent_id] < NOTTOODUMB_WARMUP_TICKS:
                actions[row] = self._warmup_action(agent_id)


class BitWorldAmongThemNativeAcePolicy(BitWorldAmongThemNotTooDumbPolicy):
    """Native NotTooDumb play with deterministic visible-task completion."""

    short_names = ["bitworld_among_them_native_ace"]

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu"):
        super().__init__(policy_env_info, device=device)
        self._seed = NATIVE_ACE_SCOUT_SEED
        self._task_hold_remaining = np.zeros(self._last_actions.shape[0], dtype=np.int64)
        self._task_hold_started_at = np.zeros(self._last_actions.shape[0], dtype=np.int64)

    def _postprocess_native_actions(
        self, observations: np.ndarray, actions: np.ndarray, agent_ids: Sequence[int]
    ) -> None:
        self._resize_native_ace_state(max(agent_ids) + 1)
        for row, agent_id in enumerate(agent_ids):
            frame = observations[row, -1]
            tick = int(self._ticks[agent_id])
            if self._is_native_interstitial(agent_id):
                self._task_hold_remaining[agent_id] = 0
                continue

            task_target = _visible_task_target(frame)
            if self._task_hold_remaining[agent_id] > 0:
                if (
                    task_target is None
                    and tick - int(self._task_hold_started_at[agent_id]) >= NATIVE_ACE_ICON_RELEASE_GRACE_TICKS
                ):
                    self._task_hold_remaining[agent_id] = 0
                else:
                    self._task_hold_remaining[agent_id] -= 1
                    actions[row] = A_ACTION
                    continue

            if task_target is not None:
                action = _visible_task_action(*task_target)
                if action == A_ACTION:
                    self._task_hold_started_at[agent_id] = tick
                    self._task_hold_remaining[agent_id] = NATIVE_ACE_TASK_HOLD_TICKS - 1
                    actions[row] = A_ACTION
                    continue
                actions[row] = action
                continue

            if actions[row] == NOOP_ACTION and tick < NOTTOODUMB_WARMUP_TICKS:
                actions[row] = self._warmup_action(agent_id)
                continue
            if actions[row] == NOOP_ACTION:
                actions[row] = self._scout_action(frame, tick, agent_id)
            elif _scout_should_press_action(frame, tick):
                actions[row] = _with_action_button(int(actions[row]))

    def _resize_native_ace_state(self, size: int) -> None:
        if self._task_hold_remaining.shape[0] == size:
            return
        self._task_hold_remaining = _resize_int_state(self._task_hold_remaining, size)
        self._task_hold_started_at = _resize_int_state(self._task_hold_started_at, size)

    def _scout_action(self, frame: np.ndarray, tick: int, agent_id: int) -> int:
        action = _scout_radar_action(frame)
        if action == NOOP_ACTION:
            action = _scout_patrol_action(self._seed, tick, agent_id)
        if _scout_should_press_action(frame, tick):
            return _with_action_button(action)
        return action


class BitWorldAmongThemChampionPolicy(BitWorldAmongThemNativeAcePolicy):
    """Native task play with frequent action pulses for tournament scoring."""

    short_names = ["bitworld_among_them_champion"]

    def _postprocess_native_actions(
        self, observations: np.ndarray, actions: np.ndarray, agent_ids: Sequence[int]
    ) -> None:
        super()._postprocess_native_actions(observations, actions, agent_ids)
        for row, agent_id in enumerate(agent_ids):
            tick = int(self._ticks[agent_id])
            if not self._is_native_interstitial(agent_id) and tick % CHAMPION_ACTION_PERIOD == 0:
                actions[row] = _with_action_button(int(actions[row]))


class BitWorldAmongThemPathfinderPolicy(BitWorldAmongThemCyborgPolicy):
    """Pure-Python state policy tuned for clean tournament bundles."""

    short_names = ["amongthem_pathfinder"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        *,
        seed: int = PATHFINDER_SEED,
        vote_listen_ticks: int = 0,
        chat_cooldown_ticks: int = CHAT_COOLDOWN_TICKS,
        declared_role: str = "auto",
    ):
        super().__init__(
            policy_env_info,
            device=device,
            seed=seed,
            vote_listen_ticks=vote_listen_ticks,
            chat_cooldown_ticks=chat_cooldown_ticks,
            declared_role=declared_role,
            use_nim_core=False,
            llm_talk=False,
        )

    def _choose_pixel_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        if self._looks_like_interstitial(frame):
            state.hold_ticks = 0
            return self._pixel_vote_action(state, agent_id)

        if self._looks_like_kill_icon(frame):
            self._mark_imposter_if_auto(state)
        if state.inferred_imposter:
            return self._pixel_imposter_action(frame, state, agent_id)

        if state.hold_ticks > 0:
            state.hold_ticks -= 1
            return A_ACTION

        task_target = _visible_task_target(frame)
        if task_target is not None:
            return self._pathfinder_visible_task_action(task_target, state)

        action = self._radar_action(frame)
        if action == NOOP_ACTION:
            if self._task_signal_near_center(frame):
                state.hold_ticks = PATHFINDER_TASK_HOLD_TICKS - 1
                return A_ACTION
            return self._with_pathfinder_action_pulse(self._patrol_action(state, agent_id), state)
        if action == A_ACTION or self._task_signal_near_center(frame):
            state.hold_ticks = PATHFINDER_TASK_HOLD_TICKS - 1
            return A_ACTION
        return self._with_pathfinder_action_pulse(action, state)

    def _pixel_imposter_action(self, frame: np.ndarray, state: _CyborgAgentState, agent_id: int) -> int:
        if self._looks_like_kill_icon(frame) and state.tick % PATHFINDER_ACTION_PERIOD < PATHFINDER_ACTION_WINDOW:
            return A_ACTION

        task_target = _visible_task_target(frame)
        if task_target is not None:
            return self._pathfinder_visible_task_action(task_target, state)

        action = self._radar_action(frame)
        if action == NOOP_ACTION:
            action = self._patrol_action(state, agent_id)
        return self._with_pathfinder_action_pulse(action, state)

    def _pathfinder_visible_task_action(self, task_target: tuple[int, int], state: _CyborgAgentState) -> int:
        action = _visible_task_action(*task_target)
        if action == A_ACTION:
            state.hold_ticks = PATHFINDER_TASK_HOLD_TICKS - 1
            return A_ACTION
        return self._with_pathfinder_action_pulse(action, state)

    def _state_crewmate_action(
        self,
        frame: np.ndarray,
        state: _CyborgAgentState,
        agent_id: int,
        players: np.ndarray,
        bodies: np.ndarray,
    ) -> int:
        body = self._nearest_state_body(bodies)
        if body is not None:
            self._queue_body_evidence(state, body, players)
            if self._distance_from_center(int(body[1]), int(body[2])) <= BODY_REPORT_DISTANCE:
                state.hold_ticks = 0
                return A_ACTION
            return _screen_move_toward(int(body[1]), int(body[2]), deadband=BODY_REPORT_DISTANCE)

        if state.hold_ticks > 0 or int(frame[HEADER_TASK_PROGRESS]) > 0:
            state.hold_ticks = max(0, state.hold_ticks - 1)
            return A_ACTION

        task = self._best_state_task(frame)
        if task is None:
            return self._with_pathfinder_action_pulse(self._patrol_action(state, agent_id), state)

        flags = int(task[3])
        if flags & TASK_ACTIVE:
            state.hold_ticks = PATHFINDER_TASK_HOLD_TICKS
            return A_ACTION
        if flags & TASK_ICON_VISIBLE:
            target_x = int(task[1]) + 6
            target_y = int(task[2]) + 18
            if self._distance_from_center(target_x, target_y) <= STATE_CLOSE_DISTANCE:
                state.hold_ticks = PATHFINDER_TASK_HOLD_TICKS
                return A_ACTION
            return self._with_pathfinder_action_pulse(_screen_move_toward(target_x, target_y), state)
        if flags & TASK_ARROW_VISIBLE:
            return self._with_pathfinder_action_pulse(_screen_move_toward(int(task[5]), int(task[6])), state)
        return self._with_pathfinder_action_pulse(self._patrol_action(state, agent_id), state)

    def _state_imposter_action(
        self,
        frame: np.ndarray,
        state: _CyborgAgentState,
        agent_id: int,
        players: np.ndarray,
        bodies: np.ndarray,
    ) -> int:
        body = self._nearest_state_body(bodies)
        if body is not None:
            return self._away_from(int(body[1]), int(body[2]), state, agent_id)

        kill_ready = int(frame[HEADER_KILL_COOLDOWN]) == KILL_READY_BYTE
        target = self._isolated_imposter_target(players)
        if kill_ready and target is not None:
            target_x = int(target[1])
            target_y = int(target[2])
            if self._distance_from_center(target_x, target_y) <= IMPOSTER_KILL_DISTANCE:
                state.queued_chat = ""
                return A_ACTION
            return _screen_move_toward(target_x, target_y, deadband=IMPOSTER_KILL_DISTANCE)

        task = self._best_state_task(frame)
        if task is not None:
            flags = int(task[3])
            if flags & TASK_ICON_VISIBLE:
                task_action = _screen_move_toward(int(task[1]) + 6, int(task[2]) + 18)
                return self._with_pathfinder_action_pulse(task_action, state)
            if flags & TASK_ARROW_VISIBLE:
                return self._with_pathfinder_action_pulse(_screen_move_toward(int(task[5]), int(task[6])), state)
        return self._with_pathfinder_action_pulse(self._patrol_action(state, agent_id), state)

    def _isolated_imposter_target(self, players: np.ndarray) -> np.ndarray | None:
        targets = self._visible_living_targets(players)
        if not targets:
            return None
        targets.sort(key=lambda player: self._distance_from_center(int(player[1]), int(player[2])))
        for target in targets:
            if self._distance_from_center(int(target[1]), int(target[2])) > PATHFINDER_CROWD_DISTANCE:
                continue
            nearby = 0
            target_x = int(target[1])
            target_y = int(target[2])
            for other in targets:
                if other is target:
                    continue
                distance = abs(int(other[1]) - target_x) + abs(int(other[2]) - target_y)
                if distance <= PATHFINDER_ISOLATION_DISTANCE:
                    nearby += 1
            if nearby == 0:
                return target
        return None

    def _with_pathfinder_action_pulse(self, action: int, state: _CyborgAgentState) -> int:
        if state.tick % PATHFINDER_ACTION_PERIOD >= PATHFINDER_ACTION_WINDOW:
            return action
        return _with_action_button(action)


class BitWorldAmongThemSleuthPolicy(BitWorldAmongThemCyborgPolicy):
    """Pure Python AmongThem policy with stronger suspicion and imposter isolation logic."""

    short_names = ["amongthem_sleuth", "bitworld_among_them_sleuth"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        *,
        seed: int = SLEUTH_SEED,
        vote_listen_ticks: int = SLEUTH_VOTE_LISTEN_TICKS,
        use_nim_core: bool = False,
        llm_talk: bool | None = False,
        **kwargs: Any,
    ):
        super().__init__(
            policy_env_info,
            device=device,
            seed=seed,
            vote_listen_ticks=vote_listen_ticks,
            use_nim_core=use_nim_core,
            llm_talk=llm_talk,
            **kwargs,
        )

    def _vote_target_cursor(self, players: np.ndarray, state: _CyborgAgentState, skip_cursor: int) -> int:
        cursor = super()._vote_target_cursor(players, state, skip_cursor)
        if cursor != skip_cursor or not state.accusation_target_color:
            return cursor

        for player_index, player in enumerate(players):
            if int(player[0]) != KIND_PLAYER:
                continue
            flags = int(player[4])
            if flags & PLAYER_SELF or not flags & PLAYER_ALIVE:
                continue
            if _player_color_name(int(player[3])) == state.accusation_target_color:
                return player_index + 1
        return skip_cursor

    def _state_imposter_action(
        self,
        frame: np.ndarray,
        state: _CyborgAgentState,
        agent_id: int,
        players: np.ndarray,
        bodies: np.ndarray,
    ) -> int:
        body = self._nearest_state_body(bodies)
        if body is not None:
            return self._away_from(int(body[1]), int(body[2]), state, agent_id)

        visible_targets = self._visible_living_targets(players)
        kill_ready = int(frame[HEADER_KILL_COOLDOWN]) == KILL_READY_BYTE
        if kill_ready:
            target = self._isolated_kill_target(visible_targets)
            if target is not None:
                target_x = int(target[1])
                target_y = int(target[2])
                if self._distance_from_center(target_x, target_y) <= IMPOSTER_KILL_DISTANCE:
                    state.queued_chat = ""
                    return A_ACTION
                if self._distance_from_center(target_x, target_y) <= SLEUTH_HUNT_DISTANCE:
                    return _screen_move_toward(target_x, target_y, deadband=IMPOSTER_KILL_DISTANCE)

        task = self._best_state_task(frame)
        if task is not None and state.tick % 144 < 96:
            return self._fake_task_action(task, state)
        return self._patrol_action(state, agent_id)

    def _isolated_kill_target(self, targets: Sequence[np.ndarray]) -> np.ndarray | None:
        candidates = []
        for target_index, target in enumerate(targets):
            target_x = int(target[1])
            target_y = int(target[2])
            witnessed = False
            for other_index, other in enumerate(targets):
                if other_index == target_index:
                    continue
                distance = abs(int(other[1]) - target_x) + abs(int(other[2]) - target_y)
                if distance <= SLEUTH_WITNESS_DISTANCE:
                    witnessed = True
                    break
            if not witnessed:
                candidates.append((self._distance_from_center(target_x, target_y), target))
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: candidate[0])
        return candidates[0][1]

    def _fake_task_action(self, task: np.ndarray, state: _CyborgAgentState) -> int:
        flags = int(task[3])
        if flags & TASK_ICON_VISIBLE:
            target_x = int(task[1]) + 6
            target_y = int(task[2]) + 18
        elif flags & TASK_ARROW_VISIBLE:
            target_x = int(task[5])
            target_y = int(task[6])
        else:
            return self._with_periodic_action(NOOP_ACTION, state)

        action = _screen_move_toward(target_x, target_y)
        if action == A_ACTION:
            return A_ACTION if state.tick % ACTION_PERIOD < ACTION_WINDOW else NOOP_ACTION
        return self._with_periodic_action(action, state)


class BitWorldAmongThemTaskMarshalPolicy(BitWorldAmongThemCyborgPolicy):
    """Native task play with deterministic local meeting handling for tournament runs."""

    short_names = ["amongthem_task_marshal"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        *,
        seed: int = 31,
        declared_role: str = "auto",
    ):
        super().__init__(
            policy_env_info,
            device=device,
            seed=seed,
            declared_role=declared_role,
            use_nim_core=True,
            llm_talk=False,
            vote_listen_ticks=0,
        )


__all__ = [
    "BitWorldAmongThemBeaconPolicy",
    "BitWorldAmongThemChampionPolicy",
    "BitWorldAmongThemCircuitSentinelPolicy",
    "BitWorldAmongThemNativeAcePolicy",
    "BitWorldAmongThemNotTooDumbPolicy",
    "BitWorldAmongThemPathfinderPolicy",
    "BitWorldAmongThemScoutPolicy",
    "BitWorldAmongThemSleuthPolicy",
    "BitWorldAmongThemSignalRunnerPolicy",
    "BitWorldAmongThemTaskMarshalPolicy",
    "BitWorldAmongThemCyborgPolicy",
]
