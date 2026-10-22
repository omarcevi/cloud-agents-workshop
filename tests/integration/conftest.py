"""Integration tests: the real agent with real Gemini, against local MCP servers.

Opt in with RUN_INTEGRATION=1 (needs Google Cloud credentials for Gemini):
  RUN_INTEGRATION=1 uv run pytest tests/integration -v
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

if os.environ.get("RUN_INTEGRATION") != "1":
    pytest.skip("set RUN_INTEGRATION=1 to run integration tests", allow_module_level=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


PORTS = {name: _free_port() for name in ("hris", "ticketing", "compensation")}
# Point the agent at local servers before app.agent is imported.
for _name, _port in PORTS.items():
    os.environ[f"{_name.upper()}_MCP_URL"] = f"http://127.0.0.1:{_port}"
os.environ.setdefault("DEMO_USER_EMAIL", "deniz.kaya@kuzeylabs.example")
os.environ.pop("GOOGLE_CLOUD_AGENT_ENGINE_ID", None)


@pytest.fixture(scope="session", autouse=True)
def local_mcp_servers() -> Iterator[dict[str, int]]:
    processes = []
    for name, port in PORTS.items():
        env = {**os.environ, "HOST": "127.0.0.1", "PORT": str(port)}
        processes.append(
            subprocess.Popen(
                [sys.executable, "-m", f"mcp_servers.{name}.server"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
    deadline = time.monotonic() + 30
    for port in PORTS.values():
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"MCP server on {port} did not start") from None
                time.sleep(0.2)
    yield PORTS
    for process in processes:
        process.terminate()
