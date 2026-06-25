from __future__ import annotations

# Moved to mettagrid. Kept here as re-exports for back-compat with existing
# cogsguard imports and job specs referencing this module path by FQCN.
from mettagrid.map_builder.choice_ascii import ChoiceAsciiMapBuilder, ChoiceAsciiMapBuilderConfig

__all__ = ["ChoiceAsciiMapBuilder", "ChoiceAsciiMapBuilderConfig"]
