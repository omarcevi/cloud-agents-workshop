"""All workshop shell scripts pass shellcheck (shellcheck-py ships the binary)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = sorted((ROOT / "scripts").rglob("*.sh"))


def test_scripts_found() -> None:
    names = {p.name for p in SCRIPTS}
    assert {"setup.sh", "check.sh", "teardown.sh", "fallback_step4.sh", "fallback_step6.sh"} <= names


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_shellcheck(script: Path) -> None:
    shellcheck = shutil.which("shellcheck")
    assert shellcheck, "shellcheck not found: uv sync installs shellcheck-py"
    result = subprocess.run(
        [shellcheck, "--external-sources", "--source-path=SCRIPTDIR", "--severity=style", str(script)],
        capture_output=True,
        text=True,
        cwd=script.parent,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_executable(script: Path) -> None:
    if script.parent.name == "lib":
        pytest.skip("sourced, not executed")
    assert script.stat().st_mode & 0o111, f"chmod +x {script.relative_to(ROOT)}"
