from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _repo_coborg_framework_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src" / "agent_policies" / "frameworks" / "coborg"
        if (candidate / "__init__.py").is_file():
            return candidate
    raise RuntimeError("could not find src/agent_policies/frameworks/coborg from Cogbase")


DEFAULT_FRAMEWORK_DIR = _repo_coborg_framework_dir()


@dataclass(frozen=True, slots=True)
class AgentFrameworkRef:
    name: str
    framework_dir: Path
    package: str
    package_source_root: Path

    def as_contract(self) -> dict[str, str]:
        return {
            "name": self.name,
            "path": str(self.framework_dir),
            "package": self.package,
            "package_source_root": str(self.package_source_root),
        }


def resolve_agent_framework_dir(value: Path | None = None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    return DEFAULT_FRAMEWORK_DIR.resolve()


def build_agent_framework_ref(value: Path | None = None) -> AgentFrameworkRef:
    framework_dir = resolve_agent_framework_dir(value)
    name = framework_dir.name
    package, source_root = _derive_package_path(framework_dir)
    return AgentFrameworkRef(
        name=name,
        framework_dir=framework_dir,
        package=package,
        package_source_root=source_root,
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
