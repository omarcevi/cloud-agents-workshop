"""MCP toolsets for the three Cloud Run MCP servers.

Each request carries two headers:
- X-User-Email: the employee, from the ADK session's user id (never from the model).
- Authorization: an ID token for the agent's own identity, because the Cloud Run
  services accept only IAM-authorized callers.

`GuardedMcpToolset` keeps a turn alive when a server refuses `tools/list` (for example
when Agent Gateway or Cloud Run IAM denies the whole server). ADK would otherwise
raise and end the turn. Instead the model sees placeholder tools that return the
denial, so it can tell the user what happened, and the audit callback logs it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from app import config
from app.identity import employee_email, id_token

_log = logging.getLogger(__name__)

# Tools each server is expected to expose, used for placeholders when it can't be listed.
HRIS_TOOLS = {
    "get_my_profile": "Return the calling employee's profile.",
    "search_directory": "Search the employee directory by name, team or office.",
    "get_leave_balance": "Return the calling employee's annual leave balance.",
    "list_leave_requests": "List the calling employee's leave requests.",
    "submit_leave_request": "Submit a leave request for the calling employee.",
}
TICKETING_TOOLS = {
    "open_ticket": "Open an IT ticket for the calling employee.",
    "get_ticket_status": "Return the status of one of the calling employee's tickets.",
    "list_my_tickets": "List the calling employee's tickets.",
}
COMPENSATION_TOOLS = {
    "get_salary_band": "Return the published salary band for a level in an office.",
    "get_salary": "Return one employee's annual base salary. Confidential.",
}


def header_provider(server: str) -> Callable[[ReadonlyContext], Awaitable[dict[str, str]]]:
    """Build the per-request headers for one MCP server."""
    base_url = config.mcp_base_url(server)

    async def provide(ctx: ReadonlyContext) -> dict[str, str]:
        headers = {}
        if email := employee_email(ctx.user_id):
            headers["X-User-Email"] = email
        if base_url.startswith("https://"):
            token = await asyncio.to_thread(id_token, base_url)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    return provide


class UnavailableTool(BaseTool):
    """Stands in for an MCP tool whose server refused to list its tools."""

    def __init__(self, *, name: str, description: str, server: str, error: str):
        super().__init__(name=name, description=description)
        self.server = server
        self.error = error

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema={"type": "object", "properties": {}},
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        return {
            "status": "unavailable",
            "error": f"The {self.server} server refused this call: {self.error}",
        }


async def diagnose(url: str, headers: dict[str, str]) -> str:
    """Send one MCP initialize request and describe the HTTP answer.

    The MCP client reports a refused tools/list only as "Server returned an error
    response", without the status. This shows whether it was a 403 from the gateway or
    from Cloud Run IAM, which the audit log needs.
    """
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "workplace-assistant", "version": "1"},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json=request,
                headers={**headers, "Accept": "application/json, text/event-stream"},
            )
        return f"HTTP {response.status_code}: {response.text[:300]}"
    except httpx.HTTPError as exc:
        return f"{type(exc).__name__}: {exc}"


class GuardedMcpToolset(McpToolset):
    """McpToolset that degrades to placeholder tools instead of failing the turn."""

    def __init__(self, *, server: str, expected_tools: dict[str, str], **kwargs: Any):
        super().__init__(**kwargs)
        self.server = server
        self.expected_tools = expected_tools

    async def get_tools(self, readonly_context: ReadonlyContext | None = None) -> list[BaseTool]:
        try:
            return await super().get_tools(readonly_context)
        except Exception as exc:  # the server, IAM or the gateway refused tools/list
            headers = await self._build_headers(readonly_context)
            detail = await diagnose(self._connection_params.url, headers or {})
            _log.warning("Could not list tools on %s: %s (%s)", self.server, exc, detail)
            return [
                UnavailableTool(name=name, description=desc, server=self.server, error=detail)
                for name, desc in self.expected_tools.items()
            ]


def mcp_toolset(server: str, expected_tools: dict[str, str]) -> GuardedMcpToolset:
    return GuardedMcpToolset(
        server=server,
        expected_tools=expected_tools,
        connection_params=StreamableHTTPConnectionParams(
            url=f"{config.mcp_base_url(server)}/mcp", timeout=20
        ),
        tool_filter=list(expected_tools),
        header_provider=header_provider(server),
    )
