from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

from .guide_index import GuideBundle


def _repo_coborg_framework_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src" / "players_lib" / "coborg"
        if (candidate / "__init__.py").is_file():
            return candidate
    raise RuntimeError("could not find src/players_lib/coborg from Cogbase")


DEFAULT_FRAMEWORK_DIR = _repo_coborg_framework_dir()
REQUIRED_CYBORG_SYMBOLS: tuple[str, ...] = (
    "ActionCommand",
    "ActionIntent",
    "AgentRuntime",
    "EmptyModeParams",
    "Mode",
    "ModeDirective",
    "ModeRegistry",
    "SynchronousStrategyRunner",
)


class FrameworkValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AgentFrameworkRef:
    name: str
    framework_dir: Path
    package: str
    package_source_root: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "path": str(self.framework_dir),
            "package": self.package,
            "package_source_root": str(self.package_source_root),
        }


def build_agent_framework_ref(
    value: Path | None = None,
    *,
    bundle: GuideBundle | None = None,
) -> AgentFrameworkRef:
    framework_dir = _resolve_framework_dir(value, bundle=bundle)
    name = framework_dir.name
    package, source_root = _derive_package_path(framework_dir)
    return AgentFrameworkRef(
        name=name,
        framework_dir=framework_dir,
        package=package,
        package_source_root=source_root,
    )


def _resolve_framework_dir(value: Path | None, *, bundle: GuideBundle | None) -> Path:
    del bundle
    if value is not None:
        return value.expanduser().resolve()
    return DEFAULT_FRAMEWORK_DIR.resolve()


def validate_agent_framework_ref(agent_framework: AgentFrameworkRef) -> None:
    if not agent_framework.framework_dir.is_dir():
        raise FrameworkValidationError(
            f"agent framework directory does not exist: {agent_framework.framework_dir}"
        )
    if not agent_framework.package_source_root.is_dir():
        raise FrameworkValidationError(
            "agent framework Python source root does not exist: "
            f"{agent_framework.package_source_root}"
        )

    package_dir = agent_framework.package_source_root.joinpath(*agent_framework.package.split("."))
    if not (package_dir / "__init__.py").is_file():
        raise FrameworkValidationError(
            f"agent framework package {agent_framework.package!r} is not present under "
            f"{agent_framework.package_source_root}"
        )

    module = _import_framework_package(agent_framework)
    missing = [symbol for symbol in REQUIRED_CYBORG_SYMBOLS if not hasattr(module, symbol)]
    if missing:
        raise FrameworkValidationError(
            f"agent framework package {agent_framework.package!r} is missing required API "
            f"symbol(s): {', '.join(missing)}"
        )


def _derive_package_path(framework_dir: Path) -> tuple[str, Path]:
    if (framework_dir / "__init__.py").is_file():
        parts = [framework_dir.name]
        current = framework_dir.parent
        while (current / "__init__.py").is_file():
            parts.append(current.name)
            current = current.parent
        parts.reverse()
        return ".".join(parts), current

    source_root = framework_dir.parent / "src"
    if source_root.is_dir():
        for child in source_root.iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                return child.name, source_root

    return framework_dir.name, framework_dir.parent


def _import_framework_package(agent_framework: AgentFrameworkRef):
    old_path = list(sys.path)
    module_names = _package_module_names(agent_framework.package)
    previous = {name: sys.modules.get(name) for name in module_names}
    for name in module_names:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(agent_framework.package_source_root))
    try:
        try:
            return importlib.import_module(agent_framework.package)
        except Exception as exc:
            raise FrameworkValidationError(
                f"could not import agent framework package {agent_framework.package!r} "
                f"from {agent_framework.package_source_root}: {exc}"
            ) from exc
    finally:
        sys.path[:] = old_path
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _package_module_names(package: str) -> tuple[str, ...]:
    parts = package.split(".")
    return tuple(".".join(parts[:index]) for index in range(1, len(parts) + 1))
