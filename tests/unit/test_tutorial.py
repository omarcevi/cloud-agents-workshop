"""tutorial.md (the Cloud Shell walkthrough) only references things that exist."""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TUTORIAL = (ROOT / "tutorial.md").read_text()


def test_one_title_and_a_step_per_lab_step() -> None:
    assert len(re.findall(r"(?m)^# ", TUTORIAL)) == 1
    steps = re.findall(r"(?m)^## (.+)$", TUTORIAL)
    for n in range(1, 7):
        assert any(s.startswith(f"Step {n} ") for s in steps), n
    assert "<walkthrough-project-setup" in TUTORIAL


def test_scripts_and_files_it_names_exist() -> None:
    for script in set(re.findall(r"\./scripts/[\w./-]+\.sh", TUTORIAL)):
        path = ROOT / script
        assert path.is_file() and os.access(path, os.X_OK), script
    for script in set(
        re.findall(r"uv run python (scripts/\S+\.py|evals/\S+\.py)", TUTORIAL)
    ):
        assert (ROOT / script).is_file(), script
    for path in set(
        re.findall(r'walkthrough-editor-open-file filePath="([^"]+)"', TUTORIAL)
    ):
        assert (ROOT / path).is_file(), path


def test_checkpoint_branches_it_names_are_generated() -> None:
    generator = (ROOT / "scripts" / "dev" / "make_checkpoints.sh").read_text()
    for branch in set(re.findall(r"git checkout (step-\d-[a-z]+)", TUTORIAL)):
        assert branch in generator, branch
