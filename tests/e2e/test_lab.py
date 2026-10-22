"""The whole lab against a real project: setup, steps 1-6 with their checks, teardown.

Opt in with RUN_E2E=1 (and a project with billing where you are Owner):
  RUN_E2E=1 uv run pytest tests/e2e -v -s --maxfail=1
Tests run in file order and depend on each other. Timings go to artifacts/e2e-timings.json.
Set E2E_KEEP=1 to skip the teardown.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TIMINGS = ROOT / "artifacts" / "e2e-timings.json"

if os.environ.get("RUN_E2E") != "1":
    pytest.skip("set RUN_E2E=1 to run the end-to-end lab", allow_module_level=True)

_timings: dict[str, float] = {}


def run(
    cmd: str, timeout: int = 900, check: bool = True
) -> subprocess.CompletedProcess[str]:
    print(f"\n$ {cmd}", flush=True)
    result = subprocess.run(
        ["bash", "-c", cmd], cwd=ROOT, text=True, capture_output=True, timeout=timeout
    )
    print(result.stdout[-4000:], result.stderr[-2000:], sep="\n", flush=True)
    if check and result.returncode != 0:
        raise AssertionError(f"{cmd} exited {result.returncode}")
    return result


def eventually(cmd: str, attempts: int, wait: int, timeout: int = 900) -> None:
    """Run a check until it passes: IAM, policies, memories and traces all settle with delay."""
    for attempt in range(1, attempts + 1):
        if run(cmd, timeout=timeout, check=False).returncode == 0:
            return
        if attempt < attempts:
            time.sleep(wait)
    raise AssertionError(f"{cmd} still failing after {attempts} attempts")


def timed(name: str):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                return fn(*args, **kwargs)
            finally:
                _timings[name] = round(time.monotonic() - start, 1)
                TIMINGS.parent.mkdir(exist_ok=True)
                TIMINGS.write_text(json.dumps(_timings, indent=2))

        wrapper.__name__ = fn.__name__
        return wrapper

    return decorator


AGENT_URL = '"$(./scripts/agent_url.sh)"'


@timed("step0_preflight")
def test_step0_preflight() -> None:
    run("./scripts/check.sh 0")


@timed("step1_setup")
def test_step1_setup() -> None:
    run("./scripts/setup.sh", timeout=1200)
    eventually("./scripts/check.sh 1", attempts=3, wait=30)


@timed("eval_gate_before_deploy")
def test_eval_gate_before_deploy() -> None:
    """The gate a deploy pipeline runs: no deploy unless the behaviour suite passes."""
    eventually("./scripts/eval.sh behaviour", attempts=2, wait=10, timeout=1200)


@timed("step2_deploy")
def test_step2_deploy() -> None:
    run(
        "source .workshop.env && agents-cli deploy --project $PROJECT_ID --agent-identity --no-confirm-project",
        timeout=1800,
    )
    run("./scripts/grant_agent_access.sh")
    eventually("./scripts/check.sh 2", attempts=5, wait=45)


@timed("step3_remember")
def test_step3_remember() -> None:
    run(
        f"agents-cli run --url {AGENT_URL} --mode adk "
        '"Hi! I\'m on the platform team in the Istanbul office, and I prefer to take Fridays off."'
    )
    eventually("./scripts/check.sh 3", attempts=12, wait=20)


@timed("step4_secure")
def test_step4_secure() -> None:
    for _ in range(40):  # setup started the gateway in the background
        log = (
            (ROOT / ".setup-gateway.log").read_text()
            if (ROOT / ".setup-gateway.log").exists()
            else ""
        )
        if "GATEWAY READY" in log or "GATEWAY FAILED" in log:
            break
        time.sleep(30)
    if "GATEWAY READY" not in log:
        pytest.fail(f"Agent Gateway was not ready:\n{log[-2000:]}")
    run("./scripts/secure.sh --deploy", timeout=1800)
    eventually("./scripts/check.sh 4", attempts=6, wait=60)


@timed("step5_observe")
def test_step5_observe() -> None:
    run(
        f'agents-cli run --url {AGENT_URL} --mode adk "Book next Monday off as a half day and tell me how many leave days I have left."'
    )
    run("./scripts/observe.sh", check=False)
    eventually("./scripts/check.sh 5", attempts=3, wait=60)


@timed("step6_evaluate")
def test_step6_evaluate() -> None:
    eventually("./scripts/eval.sh", attempts=2, wait=10, timeout=1800)
    eventually("./scripts/score_live.sh", attempts=2, wait=30, timeout=900)
    run("./scripts/monitor.sh")
    eventually("./scripts/check.sh 6", attempts=3, wait=30)


@timed("teardown")
def test_teardown_leaves_nothing() -> None:
    if os.environ.get("E2E_KEEP") == "1":
        pytest.skip("E2E_KEEP=1")
    run("./scripts/teardown.sh --yes", timeout=1800, check=False)
    eventually("./scripts/teardown.sh --verify-only", attempts=4, wait=60)
