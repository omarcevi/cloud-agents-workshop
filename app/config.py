"""Settings read from the environment.

Locally they come from .env. `agents-cli deploy` copies .env into the Agent Runtime
container's environment, so the deployed agent sees the same values.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]

# app/__init__.py imports the agent, so any `import app...` reaches this module before
# fast_api_app.py calls load_dotenv(). Load it here; existing env vars win.
load_dotenv(REPO_ROOT / ".env")

# Gemini 3.x Flash is served from the `global` and `eu` endpoints, not from europe-west1,
# so the model location is set here instead of following the agent's region.
# Use `global` on Agent Runtime: with Agent Identity the SDK switches to mTLS hostnames,
# and the `eu` endpoint has none (aiplatform.eu.rep.mtls.googleapis.com does not
# resolve). `eu` works for local runs. Details: docs/VERIFIED.md.
# gemini-3.5-flash, not 3.8: during testing (October 2026) gemini-3.8-flash on `global`
# answered in 3 s to 130 s from one call to the next, while 3.5 stayed around 3 s.
# A room full of participants needs the steady one; set MODEL to try another.
MODEL = os.environ.get("MODEL", "gemini-3.5-flash")
MODEL_LOCATION = os.environ.get("MODEL_LOCATION", "global")
# A model call that takes longer than this is abandoned and retried (3 attempts).
MODEL_TIMEOUT_SECONDS = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "45"))
# LOW thinking answers these routing and tool-calling turns faster than the default
# with the same results in the eval set.
THINKING_LEVEL = os.environ.get("THINKING_LEVEL", "LOW")

# Demo mode: the employee the agent acts for when the caller's user id is not an email
# (agents-cli run always sends "cli-user", agents-cli eval sends "eval-cli-user").
# setup.sh sets it for the workshop. Unset means no fallback: such calls carry no
# employee and the MCP servers refuse them.
DEMO_USER_EMAIL = os.environ.get("DEMO_USER_EMAIL", "")

HANDBOOK_DIR = Path(os.environ.get("HANDBOOK_DIR", REPO_ROOT / "data" / "handbook"))

TIMEZONE = os.environ.get("WORKSHOP_TIMEZONE", "Europe/Istanbul")

# Optional, lab step 4: Agent Identity Auth Manager provider for Google Calendar
# (projects/P/locations/L/authProviders/NAME). Unset = no calendar tool.
CALENDAR_AUTH_PROVIDER = os.environ.get("CALENDAR_AUTH_PROVIDER", "")

_LOCAL_MCP_PORTS = {"hris": 8081, "ticketing": 8082, "compensation": 8083}


def mcp_base_url(server: str) -> str:
    """Base URL of an MCP server: Cloud Run from .env, or a local server for tests."""
    value = os.environ.get(f"{server.upper()}_MCP_URL", "")
    return (value or f"http://127.0.0.1:{_LOCAL_MCP_PORTS[server]}").rstrip("/")
