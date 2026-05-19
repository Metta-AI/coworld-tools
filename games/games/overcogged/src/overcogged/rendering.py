"""Render-mode defaults for Overcogged entrypoints."""

from __future__ import annotations

import sys

from mettagrid.renderer.renderer import RenderMode


def default_render_mode(*, display_available: bool, interactive: bool) -> RenderMode:
    if display_available:
        return "gui"
    if interactive:
        return "unicode"
    return "none"


def auto_render_mode() -> RenderMode:
    from cogames.display_detect import has_display

    return default_render_mode(display_available=has_display(), interactive=sys.stdout.isatty())
