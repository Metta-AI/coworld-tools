"""Training loop for the Tribal Village environment using PufferLib."""

from __future__ import annotations

import logging
import multiprocessing
import os
import platform
from typing import Any

import numpy as np
import psutil
from rich.console import Console

from cogames.policy.signal_handler import DeferSigintContextManager
from cogames.train import _resolve_vector_counts
from mettagrid.policy.loader import get_policy_class_shorthand, initialize_or_load_policy
from mettagrid.policy.policy import PolicySpec
from pufferlib import pufferl
from pufferlib import vector as pvector
from pufferlib.pufferlib import set_buffers
from tribal_village_env.cogames.policy import TribalPolicyEnvInfo
from tribal_village_env.config import (
    DEFAULT_ADAM_BETA1,
    DEFAULT_ADAM_BETA2,
    DEFAULT_ADAM_EPS,
    DEFAULT_BPTT_HORIZON,
    DEFAULT_CHECKPOINT_INTERVAL,
    DEFAULT_CLIP_COEF,
    DEFAULT_ENT_COEF,
    DEFAULT_GAE_LAMBDA,
    DEFAULT_GAMMA,
    DEFAULT_LEARNING_RATE,
    DEFAULT_MAX_GRAD_NORM,
    DEFAULT_MAX_MINIBATCH_SIZE,
    DEFAULT_NUM_ENVS,
    DEFAULT_PRIO_ALPHA,
    DEFAULT_PRIO_BETA0,
    DEFAULT_TRAIN_MAX_STEPS,
    DEFAULT_UPDATE_EPOCHS,
    DEFAULT_VF_CLIP_COEF,
    DEFAULT_VF_COEF,
    DEFAULT_VTRACE_C_CLIP,
    DEFAULT_VTRACE_RHO_CLIP,
)

logger = logging.getLogger("cogames.tribal_village.train")
_MISSING = object()


def _auto_adjust(name: str, current: int, desired: int, user_supplied: bool) -> int:
    """Log and return *desired* when it differs from *current*, else pass through."""
    if desired != current:
        log_fn = logger.warning if user_supplied else logger.info
        log_fn("Auto-adjusting %s from %s to %s", name, current, desired)
        return desired
    return current


def _getattr_fallback(obj: Any, *names: str, default: Any = None) -> Any:
    """Return the first present attribute from *names*, even if its value is None."""
    for name in names:
        value = getattr(obj, name, _MISSING)
        if value is not _MISSING:
            return value
    return default


class TribalEnvFactory:
    """Picklable factory for vectorized Tribal Village environments."""

    def __init__(self, base_config: dict[str, Any]):
        self._base_config = dict(base_config)

    def __call__(
        self,
        cfg: dict[str, Any] | None = None,
        buf: Any | None = None,
        seed: int | None = None,
    ) -> Any:
        from tribal_village_env.environment import TribalVillageEnv

        merged_cfg = dict(self._base_config)
        if cfg is not None:
            merged_cfg.update(cfg)
        if seed is not None and "seed" not in merged_cfg:
            merged_cfg["seed"] = seed

        env = TribalVillageEnv(config=merged_cfg)
        set_buffers(env, buf)
        return env


class FlattenVecEnv:
    """Adapter to present contiguous agents_per_batch to the trainer."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.driver_env = _getattr_fallback(inner, "driver_env")
        for attr in (
            "single_observation_space",
            "single_action_space",
            "action_space",
            "observation_space",
            "atn_batch_shape",
        ):
            setattr(self, attr, _getattr_fallback(inner, attr))

        self.agents_per_batch = _getattr_fallback(inner, "agents_per_batch", "num_agents", default=1)
        self.num_agents = self.agents_per_batch
        self.num_envs = _getattr_fallback(inner, "num_envs", "num_environments")

    def async_reset(self, seed: int = 0) -> None:
        self.inner.async_reset(seed)

    def reset(self, seed: int = 0):
        self.async_reset(seed)
        return self.recv()

    def send(self, actions):
        actions_arr = np.asarray(actions)
        self.inner.send(actions_arr)

    def recv(self):
        result = self.inner.recv()
        has_teacher_actions = False
        if len(result) == 8:
            o, r, d, t, ta, infos, env_ids, masks = result
            has_teacher_actions = True
        elif len(result) == 7:
            o, r, d, t, infos, env_ids, masks = result
            ta = None
        else:
            raise RuntimeError(
                f"Unexpected vecenv recv payload (expected 7 or 8 items, got {len(result)})."
            )

        o = np.asarray(o).reshape(
            self.agents_per_batch, *self.single_observation_space.shape
        )
        r = np.asarray(r).reshape(self.agents_per_batch)
        d = np.asarray(d).reshape(self.agents_per_batch)
        t = np.asarray(t).reshape(self.agents_per_batch)
        mask = (
            np.asarray(masks).reshape(self.agents_per_batch)
            if masks is not None
            else np.ones(self.agents_per_batch, dtype=bool)
        )
        env_ids = (
            np.asarray(env_ids).reshape(self.agents_per_batch)
            if env_ids is not None
            else np.arange(self.agents_per_batch, dtype=np.int32)
        )
        infos = infos if isinstance(infos, list) else []
        if has_teacher_actions:
            return o, r, d, t, ta, infos, env_ids, mask
        return o, r, d, t, infos, env_ids, mask

    def close(self):
        if hasattr(self.inner, "close"):
            self.inner.close()


def train(settings: dict[str, Any]) -> None:
    """Run PPO training for Tribal Village using the provided settings."""

    from tribal_village_env.build import ensure_nim_library_current

    ensure_nim_library_current()

    console = Console()

    backend_env = os.environ.get("TRIBAL_VECTOR_BACKEND", "").lower()
    backend = pvector.Serial if backend_env == "serial" else pvector.Multiprocessing
    if platform.system() == "Darwin":
        multiprocessing.set_start_method("spawn", force=True)

    vector_num_envs = settings.get("vector_num_envs")
    vector_num_workers = settings.get("vector_num_workers")
    cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True)
    desired_workers = vector_num_workers or cpu_cores or 4
    num_workers = min(desired_workers, max(1, cpu_cores or desired_workers))
    num_envs = vector_num_envs or DEFAULT_NUM_ENVS

    adjusted_envs, adjusted_workers = _resolve_vector_counts(
        num_envs,
        num_workers,
        envs_user_supplied=vector_num_envs is not None,
        workers_user_supplied=vector_num_workers is not None,
    )
    num_envs = _auto_adjust(
        "num_envs", num_envs, adjusted_envs, vector_num_envs is not None
    )
    num_workers = _auto_adjust(
        "num_workers", num_workers, adjusted_workers, vector_num_workers is not None
    )

    vector_batch_size = settings.get("vector_batch_size") or num_envs
    if num_envs % vector_batch_size != 0:
        logger.warning(
            "vector_batch_size=%s does not evenly divide num_envs=%s; resetting to %s",
            vector_batch_size,
            num_envs,
            num_envs,
        )
        vector_batch_size = num_envs

    base_config = {"render_mode": "ansi", "render_scale": 1}
    base_config.update(
        settings.get(
            "env_config",
            {
                "max_steps": DEFAULT_TRAIN_MAX_STEPS,
            },
        )
    )

    env_creator = TribalEnvFactory(base_config)

    vecenv = pvector.make(
        env_creator,
        num_envs=num_envs,
        num_workers=num_workers,
        batch_size=vector_batch_size,
        backend=backend,
        env_kwargs={"cfg": dict(base_config)},
    )
    agents_per_batch = _getattr_fallback(vecenv, "agents_per_batch")
    if agents_per_batch is not None:
        vecenv.num_agents = agents_per_batch
    vecenv = FlattenVecEnv(vecenv)

    driver_env = _getattr_fallback(vecenv, "driver_env")
    if driver_env is None:
        raise RuntimeError(
            "Vectorized environment did not expose driver_env for shape inference."
        )

    policy_env_info = TribalPolicyEnvInfo(
        observation_space=driver_env.single_observation_space,
        action_space=driver_env.single_action_space,
        num_agents=max(1, _getattr_fallback(driver_env, "num_agents", default=1)),
    )

    initial_weights_path = settings.get("initial_weights_path")
    resolved_initial_weights = (
        os.path.expanduser(initial_weights_path[7:])
        if initial_weights_path and initial_weights_path.startswith("file://")
        else initial_weights_path
    )

    policy_spec = PolicySpec(
        class_path=settings["policy_class_path"], data_path=resolved_initial_weights
    )
    policy = initialize_or_load_policy(policy_env_info, policy_spec)
    network = policy.network()
    assert network is not None, (
        f"Policy {settings['policy_class_path']} must be trainable (network() returned None)"
    )
    network.to(settings["device"])

    use_rnn = getattr(policy, "is_recurrent", lambda: False)()
    if not use_rnn and "lstm" in settings["policy_class_path"].lower():
        use_rnn = True

    env_name = "tribal_village"

    learning_rate = DEFAULT_LEARNING_RATE
    bptt_horizon = DEFAULT_BPTT_HORIZON if use_rnn else 1
    optimizer = "adam"
    adam_eps = DEFAULT_ADAM_EPS

    total_agents = max(
        1,
        _getattr_fallback(
            vecenv,
            "num_agents",
            default=_getattr_fallback(driver_env, "num_agents", default=1),
        ),
    )
    num_workers = max(1, _getattr_fallback(vecenv, "num_workers", default=num_workers))

    effective_agents_per_batch = agents_per_batch or total_agents
    amended_batch_size = effective_agents_per_batch
    batch_size = settings["batch_size"]
    if batch_size != amended_batch_size:
        logger.warning(
            "batch_size=%s overridden to %s to match agents_per_batch; larger batches not yet supported",
            batch_size,
            amended_batch_size,
        )

    minibatch_size = settings["minibatch_size"]
    amended_minibatch_size = min(minibatch_size, amended_batch_size)
    if amended_minibatch_size != minibatch_size:
        logger.info(
            "Reducing minibatch_size from %s to %s to keep it <= batch_size",
            minibatch_size,
            amended_minibatch_size,
        )

    steps = settings["steps"]
    effective_timesteps = max(steps, amended_batch_size)
    if effective_timesteps != steps:
        logger.info(
            "Raising total_timesteps from %s to %s to keep it >= batch_size",
            steps,
            effective_timesteps,
        )

    checkpoint_interval = DEFAULT_CHECKPOINT_INTERVAL
    train_args = dict(
        env=env_name,
        device=settings["device"].type,
        total_timesteps=effective_timesteps,
        minibatch_size=amended_minibatch_size,
        batch_size=amended_batch_size,
        data_dir=str(settings["checkpoints_path"]),
        checkpoint_interval=checkpoint_interval,
        bptt_horizon=bptt_horizon,
        seed=settings["seed"],
        use_rnn=use_rnn,
        torch_deterministic=True,
        cpu_offload=False,
        optimizer=optimizer,
        anneal_lr=True,
        precision="float32",
        learning_rate=learning_rate,
        gamma=DEFAULT_GAMMA,
        gae_lambda=DEFAULT_GAE_LAMBDA,
        update_epochs=DEFAULT_UPDATE_EPOCHS,
        clip_coef=DEFAULT_CLIP_COEF,
        vf_coef=DEFAULT_VF_COEF,
        vf_clip_coef=DEFAULT_VF_CLIP_COEF,
        max_grad_norm=DEFAULT_MAX_GRAD_NORM,
        ent_coef=DEFAULT_ENT_COEF,
        adam_beta1=DEFAULT_ADAM_BETA1,
        adam_beta2=DEFAULT_ADAM_BETA2,
        adam_eps=adam_eps,
        max_minibatch_size=DEFAULT_MAX_MINIBATCH_SIZE,
        compile=False,
        vtrace_rho_clip=DEFAULT_VTRACE_RHO_CLIP,
        vtrace_c_clip=DEFAULT_VTRACE_C_CLIP,
        prio_alpha=DEFAULT_PRIO_ALPHA,
        prio_beta0=DEFAULT_PRIO_BETA0,
    )

    trainer = pufferl.PuffeRL(train_args, vecenv, network)

    with DeferSigintContextManager():
        while trainer.global_step < effective_timesteps:
            trainer.evaluate()
            trainer.train()

    trainer.print_dashboard()
    final_checkpoint = trainer.close()
    vecenv.close()

    console.rule("[bold green]Training Summary")
    if final_checkpoint:
        console.print(f"Final checkpoint: [cyan]{final_checkpoint}[/cyan]")
        if trainer.epoch < checkpoint_interval:
            console.print(
                f"Training stopped before first scheduled checkpoint (epoch {checkpoint_interval}). "
                "Latest weights may be near-random.",
                style="yellow",
            )

        policy_shorthand = get_policy_class_shorthand(settings["policy_class_path"])
        policy_arg = policy_shorthand or settings["policy_class_path"]
        policy_with_checkpoint = f"class={policy_arg},data={final_checkpoint}"

        console.print()
        console.print("To continue training this policy:", style="bold")
        console.print(
            f"  [yellow]cogames train-tribal -p {policy_with_checkpoint}[/yellow]"
        )
    else:
        console.print()
        console.print(
            f"[yellow]No checkpoint file reported. Check {settings['checkpoints_path']} for saved models.[/yellow]"
        )

    console.rule("[bold green]End Training")
