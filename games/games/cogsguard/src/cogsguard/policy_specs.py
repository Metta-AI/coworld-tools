from __future__ import annotations

from pathlib import Path

from pydantic import Field

from mettagrid.policy.loader import resolve_policy_class_path
from mettagrid.policy.policy import PolicySpec
from mettagrid.util.uri_resolvers.schemes import parse_uri, policy_spec_from_uri


class PolicySpecWithProportion(PolicySpec):
    proportion: float = Field(default=1.0, description="Proportion of total agents to assign to this policy")

    def to_policy_spec(self) -> PolicySpec:
        return PolicySpec.model_validate(self.model_dump(exclude={"proportion"}))


def parse_policy_spec(spec: str, device: str | None = None) -> PolicySpecWithProportion:
    def parse_key_value(entry: str) -> tuple[str, str]:
        if "=" not in entry:
            raise ValueError(
                "Policy entries must be key=value pairs (e.g., class=stateless,data=train_dir/model.pt,proportion=0.5)."
            )
        key, value = (part.strip() for part in entry.split("=", 1))
        if not key:
            raise ValueError("Policy field name cannot be empty.")
        return key, value

    def parse_proportion(value: str) -> float:
        fraction = float(value)
        if fraction <= 0:
            raise ValueError("Policy proportion must be a positive number.")
        return fraction

    def is_path_like(value: str) -> bool:
        if value.startswith((".", "/", "~")):
            return True
        return len(value) >= 3 and value[0].isalpha() and value[1] == ":" and value[2] in ("/", "\\")

    def is_uri(value: str) -> bool:
        if value.startswith("metta://"):
            return True
        return parse_uri(value, allow_none=True, default_scheme=None) is not None

    device_kwargs = {"device": device} if device is not None else {}

    if spec.startswith("metta://"):
        proportion_marker = ",proportion="
        if proportion_marker in spec:
            uri_part, proportion_value = spec.split(proportion_marker, 1)
            fraction = parse_proportion(proportion_value.strip())
        else:
            uri_part = spec
            fraction = 1.0

        policy = policy_spec_from_uri(uri_part.strip(), device=device or "cpu")
        return PolicySpecWithProportion(
            class_path=policy.class_path,
            data_path=policy.data_path,
            proportion=fraction,
            init_kwargs={**policy.init_kwargs, **device_kwargs},
        )

    entries = [part.strip() for part in spec.split(",") if part.strip()]
    if not entries:
        raise ValueError("Policy specification cannot be empty.")

    fraction = 1.0
    first = entries[0]
    if is_uri(first) or ("=" not in first and is_path_like(first)):
        policy = policy_spec_from_uri(first, device=device or "cpu")
        for entry in entries[1:]:
            key, value = parse_key_value(entry)
            if key != "proportion":
                raise ValueError("Only proportion is supported after a checkpoint URI.")
            fraction = parse_proportion(value)

        return PolicySpecWithProportion(
            class_path=policy.class_path,
            data_path=policy.data_path,
            proportion=fraction,
            init_kwargs={**policy.init_kwargs, **device_kwargs},
        )

    if "=" not in first:
        if ":" in first:
            name, suffix = first.rsplit(":", 1)
            if suffix.isdigit() and int(suffix) > 0:
                entries[0] = f"class={name}"
                entries.append(f"proportion={suffix}")
            else:
                dotted = first.replace(":", ".")
                raise ValueError(
                    f"Policy shorthand cannot include ':'. Did you mean 'class={dotted}'? "
                    "Use '.' as the module separator."
                )
        else:
            entries[0] = f"class={first}"

    class_path: str | None = None
    data_path: str | None = None
    init_kwargs: dict[str, str] = {}

    for entry in entries:
        key, value = parse_key_value(entry)

        if key == "class":
            if not value:
                raise ValueError("Policy class cannot be empty.")
            if "?" in value:
                class_part, query = value.split("?", 1)
                pairs = query.split("&") if query else []
                hint_parts = [f"kw.{pair}" for pair in pairs if "=" in pair]
                hint = ",".join([f"class={class_part}"] + hint_parts)
                raise ValueError(
                    f"Query string syntax (?key=val) is not supported in policy specs. "
                    f"Use comma-separated kw. prefix instead: '{hint}'."
                )
            class_path = resolve_policy_class_path(value)
            continue

        if key == "data":
            if not value:
                raise ValueError("Policy data path cannot be empty.")
            data_path = str(Path(value).expanduser().resolve())
            continue

        if key == "proportion":
            fraction = parse_proportion(value)
            continue

        if key.startswith("kw."):
            kw_key = key[3:]
            if not kw_key:
                raise ValueError("Policy kw field name cannot be empty.")
            init_kwargs[kw_key.replace("-", "_")] = value
            continue

        raise ValueError(
            f"Unsupported policy field '{key}'. To pass '{key}' as a policy init kwarg, use 'kw.{key}={value}'."
        )

    if class_path is None:
        raise ValueError("Policy specification must include class= for key=value format.")

    return PolicySpecWithProportion(
        class_path=class_path,
        data_path=data_path,
        proportion=fraction,
        init_kwargs={**init_kwargs, **device_kwargs},
    )
