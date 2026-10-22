"""Helpers shared by the three workshop MCP servers (HRIS, ticketing, compensation).

The directory is called ``mcp_servers`` rather than ``mcp`` so it never shadows the
``mcp`` Python package that FastMCP and ADK import.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from starlette.requests import Request
from starlette.responses import JSONResponse

# The agent sets this header from the ADK session's user id. The model never sees it,
# so a prompt cannot make the agent act as someone else.
USER_HEADER = "x-user-email"

SEED_DIR = Path(
    os.environ.get("SEED_DIR", Path(__file__).resolve().parents[2] / "data" / "seed")
)

_log = logging.getLogger("mcp_servers")


def load_seed(name: str) -> dict[str, Any]:
    """Load one of the fictional seed files from data/seed."""
    data: dict[str, Any] = json.loads((SEED_DIR / name).read_text(encoding="utf-8"))
    return data


def caller_email() -> str:
    """Return the employee the agent is acting for.

    Read from the X-User-Email header. ``DEFAULT_USER_EMAIL`` is a fallback for
    in-memory tests and local runs without an agent in front.
    """
    email = get_http_headers().get(USER_HEADER) or os.environ.get(
        "DEFAULT_USER_EMAIL", ""
    )
    if not email:
        raise ToolError(
            "No X-User-Email header. The agent must say which employee it acts for."
        )
    return email.strip().lower()


def audit(server: str, tool: str, caller: str, outcome: str, **fields: Any) -> None:
    """Write one structured log line. Cloud Run turns JSON on stdout into jsonPayload."""
    entry = {
        "severity": "INFO" if outcome == "ok" else "WARNING",
        "message": f"{server}.{tool} {outcome}",
        "server": server,
        "tool": tool,
        "caller": caller,
        "outcome": outcome,
        **fields,
    }
    print(json.dumps(entry, ensure_ascii=False), file=sys.stdout, flush=True)


def create_server(name: str, instructions: str) -> FastMCP:
    """Create a FastMCP server with a /health route for Cloud Run checks.

    Cloud Run reserves some paths ending in ``z`` (such as /healthz), so the route is /health.
    """
    mcp = FastMCP(name, instructions=instructions)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": name})

    return mcp


def serve(mcp: FastMCP) -> None:
    """Serve over streamable HTTP at /mcp on $PORT (Cloud Run sets PORT)."""
    mcp.run(
        transport="http",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        stateless_http=True,
        show_banner=False,
    )
