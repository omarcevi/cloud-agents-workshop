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

# Gemini 3.x Flash models are served from the `global` (or `eu`) endpoint, not from
# europe-west1, so the model location is pinned here instead of following the region.
MODEL = os.environ.get("MODEL", "gemini-3.8-flash")
MODEL_LOCATION = os.environ.get("MODEL_LOCATION", "global")

# Employee the agent acts for when the caller's user id is not an email
# (agents-cli run uses "cli-user", agents-cli eval uses "eval-cli-user").
DEMO_USER_EMAIL = os.environ.get("DEMO_USER_EMAIL", "deniz.kaya@kuzeylabs.example")

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
