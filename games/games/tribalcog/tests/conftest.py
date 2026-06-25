"""Pytest configuration and fixtures for tribal_village tests."""

import pytest
from pathlib import Path

# Check if Nim library is available
def _nim_library_available() -> bool:
    """Check if the compiled Nim library exists."""
    import platform

    if platform.system() == "Darwin":
        lib_name = "libtribal_village.dylib"
    elif platform.system() == "Windows":
        lib_name = "libtribal_village.dll"
    else:
        lib_name = "libtribal_village.so"

    package_dir = Path(__file__).resolve().parent.parent / "tribal_village_env"
    candidate_paths = [
        package_dir.parent / lib_name,
        package_dir / lib_name,
    ]

    return any(path.exists() for path in candidate_paths)


NIM_LIBRARY_AVAILABLE = _nim_library_available()

# Skip marker for tests requiring the Nim library
requires_nim_library = pytest.mark.skipif(
    not NIM_LIBRARY_AVAILABLE,
    reason="Nim library not available"
)
