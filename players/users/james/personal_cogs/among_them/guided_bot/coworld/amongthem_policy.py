"""Coworld policy wrapper around the guided_bot Nim library.

The public Among Them image imports this as ``amongthem_policy.AmongThemPolicy``.
It locates the guided_bot source tree, builds/loads ``libguidedbot``, and routes
Coworld player observations through the Nim FFI.
"""

from __future__ import annotations

import ctypes
import importlib.util
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import numpy as np

try:
    from mettagrid.bitworld import (
        BITWORLD_ACTION_COUNT,
        BITWORLD_ACTION_NAMES,
        SCREEN_HEIGHT,
        SCREEN_WIDTH,
    )
except ImportError:
    SCREEN_WIDTH = 128
    SCREEN_HEIGHT = 128
    BITWORLD_ACTION_NAMES = (
        "noop",
        "a",
        "b",
        "up",
        "up+a",
        "up+b",
        "down",
        "down+a",
        "down+b",
        "left",
        "left+a",
        "left+b",
        "right",
        "right+a",
        "right+b",
        "up+left",
        "up+left+a",
        "up+left+b",
        "up+right",
        "up+right+a",
        "up+right+b",
        "down+left",
        "down+left+a",
        "down+left+b",
        "down+right",
        "down+right+a",
        "down+right+b",
    )
    BITWORLD_ACTION_COUNT = len(BITWORLD_ACTION_NAMES)

from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, AgentObservation


def _find_guided_bot_dir() -> Path:
    """Return the directory containing ``build_guided_bot.py``."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent,
        here / "among_them" / "guided_bot",
        here.parent / "among_them" / "guided_bot",
    ]
    for candidate in candidates:
        if (candidate / "build_guided_bot.py").is_file():
            return candidate
    searched = "\n  ".join(str(c) for c in candidates)
    raise RuntimeError(
        "Could not locate guided_bot source directory. Searched:\n  " + searched
    )


def _import_build(guided_bot_dir: Path) -> ModuleType:
    module_name = "_guided_bot_build_guided_bot"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(
        module_name, guided_bot_dir / "build_guided_bot.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load build_guided_bot.py from {guided_bot_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _GuidedBotAgentPolicy(AgentPolicy):
    """Single-agent shim around the batched Nim policy."""

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        parent: "AmongThemPolicy",
        agent_id: int,
    ):
        super().__init__(policy_env_info)
        self._parent = parent
        self._agent_id = agent_id

    def step(self, obs: AgentObservation) -> Action:
        del obs
        action_index = self._parent.step_agent(self._agent_id)
        return Action(name=self._policy_env_info.action_names[action_index])


class AmongThemPolicy(MultiAgentPolicy):
    """Runs guided_bot through the compiled shared library."""

    short_names = ["amongthem_guided_bot"]

    def __init__(
        self,
        policy_env_info: PolicyEnvInterface,
        device: str = "cpu",
        **kwargs,
    ):
        super().__init__(policy_env_info, device=device)
        if tuple(policy_env_info.action_names) != BITWORLD_ACTION_NAMES:
            raise ValueError(
                "AmongThemPolicy requires the "
                f"{BITWORLD_ACTION_COUNT}-action BitWorld action space."
            )
        self._guided_bot_dir = _find_guided_bot_dir()
        self._build = _import_build(self._guided_bot_dir)
        self._lib = self._load_library()
        self._lib.guidedbot_new_policy.argtypes = [ctypes.c_int]
        self._lib.guidedbot_new_policy.restype = ctypes.c_int
        self._lib.guidedbot_step_batch.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int32),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._lib.guidedbot_step_batch.restype = None
        self._lib.guidedbot_take_chat.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        self._lib.guidedbot_take_chat.restype = ctypes.c_int
        self._destroy_fn = getattr(self._lib, "guidedbot_destroy_policy", None)
        if self._destroy_fn is not None:
            self._destroy_fn.argtypes = [ctypes.c_int]
            self._destroy_fn.restype = None
        self._set_trace_dir_fn = getattr(self._lib, "guidedbot_set_trace_dir", None)
        if self._set_trace_dir_fn is not None:
            self._set_trace_dir_fn.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_char_p,
            ]
            self._set_trace_dir_fn.restype = None
        self._num_agents = max(1, int(policy_env_info.num_agents))
        self._handle = int(self._lib.guidedbot_new_policy(self._num_agents))
        self._closed = False
        self._last_actions = np.zeros(self._num_agents, dtype=np.int32)
        self._pending_chat: dict[int, str] = {}
        self._chat_buf = ctypes.create_string_buffer(256)

        trace_dir = kwargs.get("trace_dir")
        trace_level = kwargs.get("trace_level", "decisions")
        if trace_dir:
            self._set_trace_dir(trace_dir, trace_level)

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        return _GuidedBotAgentPolicy(self._policy_env_info, self, agent_id)

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        batch_size = raw_observations.shape[0]
        actions = self.step_agent_observations(range(batch_size), raw_observations)
        raw_actions[:batch_size] = actions.astype(raw_actions.dtype, copy=False)

    def step_agent_observations(
        self,
        agent_ids: Sequence[int],
        raw_observations: np.ndarray,
    ) -> np.ndarray:
        """Step a subset of slots with raw BitWorld pixel observations."""
        observations = self._normalize_observations(raw_observations)
        batch_size = observations.shape[0]
        agent_ids_array = np.asarray(list(agent_ids), dtype=np.int32)
        if agent_ids_array.shape != (batch_size,):
            raise ValueError(
                "agent_ids and raw_observations must have matching batch size."
            )
        if batch_size == 0:
            return np.zeros((0,), dtype=np.int32)

        highest_agent_id = int(agent_ids_array.max())
        if highest_agent_id < 0:
            raise ValueError("agent_ids must be non-negative.")
        self._ensure_agent_count(highest_agent_id + 1)
        actions = np.zeros(batch_size, dtype=np.int32)
        self._lib.guidedbot_step_batch(
            self._handle,
            agent_ids_array.ctypes.data_as(ctypes.POINTER(ctypes.c_int32)),
            ctypes.c_int(batch_size),
            ctypes.c_int(self._num_agents),
            ctypes.c_int(observations.shape[1]),
            ctypes.c_int(observations.shape[2]),
            ctypes.c_int(observations.shape[3]),
            ctypes.c_void_p(observations.ctypes.data),
            ctypes.c_void_p(actions.ctypes.data),
        )
        for row, agent_id in enumerate(agent_ids_array):
            self._last_actions[int(agent_id)] = actions[row]
            self._drain_chat(int(agent_id))
        return actions

    def step_agent(self, agent_id: int) -> int:
        if 0 <= agent_id < self._last_actions.shape[0]:
            return int(self._last_actions[agent_id])
        return 0

    def take_chat(self, agent_id: int) -> str:
        """Pop one pending chat line for Coworld protocol responses."""
        return self._pending_chat.pop(agent_id, "")

    def bitworld_chat_messages(self, agent_ids) -> list[str | None]:
        """Batched chat hook used by mettagrid BitWorld runners."""
        messages: list[str | None] = []
        for agent_id in agent_ids:
            text = self._pending_chat.pop(int(agent_id), "")
            messages.append(text if text else None)
        return messages

    def _set_trace_dir(self, trace_dir: str, trace_level: str = "decisions") -> None:
        if self._set_trace_dir_fn is None:
            return
        self._set_trace_dir_fn(
            self._handle,
            trace_dir.encode("utf-8"),
            trace_level.encode("utf-8"),
        )

    def _drain_chat(self, agent_id: int) -> None:
        written = int(
            self._lib.guidedbot_take_chat(
                self._handle,
                ctypes.c_int(agent_id),
                ctypes.c_void_p(ctypes.addressof(self._chat_buf)),
                ctypes.c_int(len(self._chat_buf)),
            )
        )
        if written <= 0:
            return
        try:
            text = self._chat_buf.raw[:written].decode("ascii").strip()
        except UnicodeDecodeError:
            return
        if text:
            self._pending_chat[agent_id] = text

    def close(self, *, reason: str = "session_end") -> None:
        """Tear down the Nim policy: stops guidance worker, flushes traces."""
        del reason
        if self._closed:
            return
        self._closed = True
        if self._destroy_fn is not None:
            self._destroy_fn(self._handle)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _ensure_agent_count(self, count: int) -> None:
        if count <= self._num_agents:
            return
        old_actions = self._last_actions
        self._num_agents = count
        self._last_actions = np.zeros(count, dtype=np.int32)
        self._last_actions[: old_actions.shape[0]] = old_actions

    def _normalize_observations(self, observations: np.ndarray) -> np.ndarray:
        if observations.ndim == 4:
            normalized = observations
        elif observations.ndim == 3:
            normalized = observations[:, np.newaxis, :, :]
        elif observations.ndim == 2:
            normalized = self._unpack_frames(observations)[:, np.newaxis, :, :]
        else:
            raise ValueError(
                "Expected BitWorld observations with 2, 3, or 4 dimensions, "
                f"got {observations.ndim}."
            )
        if normalized.shape[2:] != (SCREEN_HEIGHT, SCREEN_WIDTH):
            raise ValueError(f"Expected {SCREEN_HEIGHT}x{SCREEN_WIDTH} BitWorld frames.")
        return np.ascontiguousarray(normalized, dtype=np.uint8)

    def _unpack_frames(self, observations: np.ndarray) -> np.ndarray:
        packed = np.ascontiguousarray(observations, dtype=np.uint8)
        pixels = np.empty((packed.shape[0], packed.shape[1] * 2), dtype=np.uint8)
        pixels[:, 0::2] = packed & 0x0F
        pixels[:, 1::2] = packed >> 4
        return pixels.reshape(packed.shape[0], SCREEN_HEIGHT, SCREEN_WIDTH)

    def _load_library(self) -> ctypes.CDLL:
        lib_path = self._guided_bot_dir / _library_name()
        if self._library_needs_rebuild(lib_path):
            lib_path = Path(self._build.build_guided_bot())
        lib = ctypes.CDLL(str(lib_path))
        self._verify_library_abi(lib, lib_path)
        return lib

    def _library_needs_rebuild(self, lib_path: Path) -> bool:
        if not lib_path.exists():
            return True
        try:
            stamp = int(self._build._abi_stamp_path(lib_path).read_text().strip())
        except (OSError, ValueError):
            return True
        if stamp != self._build.GUIDED_BOT_ABI_VERSION:
            return True
        return self._source_tree_newer_than(lib_path)

    def _source_tree_newer_than(self, lib_path: Path) -> bool:
        try:
            lib_mtime = lib_path.stat().st_mtime
        except OSError:
            return True

        skip_dirs = {"nimcache", "__pycache__", ".git"}
        suffixes = {".nim", ".py", ".cfg", ".bin", ".json"}
        for path in self._guided_bot_dir.rglob("*"):
            if any(part in skip_dirs for part in path.parts):
                continue
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if path.name.startswith("libguidedbot."):
                continue
            try:
                if path.stat().st_mtime > lib_mtime:
                    return True
            except OSError:
                return True
        return False

    def _verify_library_abi(self, lib: ctypes.CDLL, lib_path: Path) -> None:
        try:
            abi_version = lib.guidedbot_abi_version
        except AttributeError as exc:
            raise RuntimeError(
                f"guided_bot library {lib_path} does not export an ABI version."
            ) from exc
        abi_version.argtypes = []
        abi_version.restype = ctypes.c_int
        actual = int(abi_version())
        expected = self._build.GUIDED_BOT_ABI_VERSION
        if actual != expected:
            raise RuntimeError(
                f"guided_bot library {lib_path} has ABI version {actual}, "
                f"expected {expected}."
            )


def _library_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "libguidedbot.dylib"
    if system == "Windows":
        return "guidedbot.dll"
    return "libguidedbot.so"
