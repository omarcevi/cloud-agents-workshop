"""tutorial.md (the Cloud Shell walkthrough) only references things that exist."""

from __future__ import annotations

import importlib.util
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


def test_console_links_open_the_participants_project() -> None:
    links = re.findall(r"\((https://console\.cloud\.google\.com/[^)\s]+)\)", TUTORIAL)
    assert len(links) >= 10
    for link in links:
        assert link.endswith("?project=<walkthrough-project-id/>"), link


def test_participant_text_follows_simplified_technical_english() -> None:
    spec = importlib.util.spec_from_file_location(
        "ste_check", ROOT / "scripts" / "dev" / "ste_check.py"
    )
    assert spec and spec.loader
    ste = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ste)
    for name in ("tutorial.md", "README.md"):
        assert ste.check_file(ROOT / name) == [], name
