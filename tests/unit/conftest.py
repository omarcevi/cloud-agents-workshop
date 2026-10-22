"""Unit-test fixtures. No external network: MCP servers run on 127.0.0.1 in threads.

The env vars are set at import time, before any test module imports app.agent, so the
agent's MCP toolsets point at the local servers instead of Cloud Run.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


PORTS = {
    name: _free_port() for name in ("hris", "ticketing", "compensation", "forbidden")
}

os.environ.update(
    {
        "HRIS_MCP_URL": f"http://127.0.0.1:{PORTS['hris']}",
        "TICKETING_MCP_URL": f"http://127.0.0.1:{PORTS['ticketing']}",
        "COMPENSATION_MCP_URL": f"http://127.0.0.1:{PORTS['compensation']}",
        "DEMO_USER_EMAIL": "deniz.kaya@kuzeylabs.example",
        "HRIS_TODAY": "2026-10-22",
        "CALENDAR_AUTH_PROVIDER": "",
        "GOOGLE_CLOUD_PROJECT": "unit-test-project",
    }
)
os.environ.pop("GOOGLE_CLOUD_AGENT_ENGINE_ID", None)


async def _forbidden(request: Request) -> PlainTextResponse:
    # What Agent Gateway or Cloud Run IAM sends back when the agent may not call a server.
    return PlainTextResponse(
        "403 Forbidden. {'message': 'Egress request is not authorized.', 'status': 'Forbidden'}",
        status_code=403,
    )


def _serve(app, port: int) -> uvicorn.Server:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError(f"server on port {port} did not start")
        time.sleep(0.05)
    return server


@pytest.fixture(scope="session")
def mcp_servers() -> Iterator[dict[str, int]]:
    from mcp_servers.compensation import server as compensation
    from mcp_servers.hris import server as hris
    from mcp_servers.ticketing import server as ticketing

    servers = [
        _serve(hris.mcp.http_app(stateless_http=True), PORTS["hris"]),
        _serve(ticketing.mcp.http_app(stateless_http=True), PORTS["ticketing"]),
        _serve(compensation.mcp.http_app(stateless_http=True), PORTS["compensation"]),
        _serve(
            Starlette(
                routes=[
                    Route("/{path:path}", _forbidden, methods=["GET", "POST", "DELETE"])
                ]
            ),
            PORTS["forbidden"],
        ),
    ]
    yield PORTS
    for server in servers:
        server.should_exit = True
