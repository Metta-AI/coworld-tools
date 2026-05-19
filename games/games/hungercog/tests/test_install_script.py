from __future__ import annotations

from pathlib import Path


def test_install_script_defaults_to_metta_main_branch() -> None:
    install_script = Path(__file__).resolve().parents[1] / "install.sh"

    assert 'METTA_REF="${METTA_REF:-main}"' in install_script.read_text()
