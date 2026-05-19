from __future__ import annotations

from mettagrid.config.obs_config import ObsConfig

_MISSING_FIELD_MESSAGE = (
    "Werecog requires unreleased mettagrid observation fields. "
    "Install Werecog with its branch-pinned mettagrid/cogames deps or against metta@relh/werewolf-single-pr until the upstream mettagrid release adds: {fields}."
)


def require_obs_fields(*fields: str) -> None:
    missing = [field for field in fields if field not in ObsConfig.model_fields]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(_MISSING_FIELD_MESSAGE.format(fields=joined))
