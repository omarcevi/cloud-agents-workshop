"""IT ticketing MCP server: open tickets and check their status.

Fictional data for the fictional company Kuzey Labs, loaded from data/seed.
State lives in memory, so it resets when Cloud Run starts a new instance.
"""

from __future__ import annotations

import copy
import datetime as dt
from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_servers.common import audit, caller_email, create_server, load_seed, serve

SERVER = "ticketing"
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
WRITE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)

Category = Literal["HARDWARE", "SOFTWARE", "ACCESS", "NETWORK", "OTHER"]
Priority = Literal["P1", "P2", "P3", "P4"]
Status = Literal["OPEN", "IN_PROGRESS", "RESOLVED"]

mcp = create_server(
    "kuzey-ticketing",
    instructions="Kuzey Labs IT desk. Tickets belong to the employee in the X-User-Email header.",
)

_tickets: list[dict[str, Any]] = []


def reset() -> None:
    """Reload the seed data. Tests call this to start from a known state."""
    _tickets.clear()
    _tickets.extend(copy.deepcopy(load_seed("tickets.json")["tickets"]))


reset()


@mcp.tool(annotations=WRITE)
def open_ticket(
    summary: Annotated[str, Field(description="One line describing the problem.")],
    category: Category,
    priority: Priority = "P3",
    details: str = "",
) -> dict[str, Any]:
    """Open an IT ticket for the calling employee. Priorities follow the IT handbook (P1 = cannot work)."""
    email = caller_email()
    if not summary.strip():
        raise ToolError("summary must not be empty.")
    ticket = {
        "id": f"IT-{2300 + len(_tickets)}",
        "requester": email,
        "summary": summary.strip(),
        "details": details,
        "category": category,
        "priority": priority,
        "status": "OPEN",
        "assignee": None,
        "created": dt.date.today().isoformat(),
    }
    _tickets.append(ticket)
    audit(SERVER, "open_ticket", email, "ok", ticket_id=ticket["id"], priority=priority)
    return ticket


@mcp.tool(annotations=READ_ONLY)
def get_ticket_status(
    ticket_id: Annotated[str, Field(description="Ticket id, for example IT-2201.")],
) -> dict[str, Any]:
    """Return the status of one of the calling employee's tickets."""
    email = caller_email()
    wanted = ticket_id.strip().upper()
    for ticket in _tickets:
        # Other people's tickets look the same as missing ones.
        if ticket["id"] == wanted and ticket["requester"] == email:
            audit(SERVER, "get_ticket_status", email, "ok", ticket_id=wanted)
            return ticket
    audit(SERVER, "get_ticket_status", email, "not_found", ticket_id=wanted)
    raise ToolError(f"No ticket {wanted} found for {email}.")


@mcp.tool(annotations=READ_ONLY)
def list_my_tickets(status: Status | None = None) -> list[dict[str, Any]]:
    """List the calling employee's tickets, optionally filtered by status."""
    email = caller_email()
    mine = [
        t
        for t in _tickets
        if t["requester"] == email and (status is None or t["status"] == status)
    ]
    audit(SERVER, "list_my_tickets", email, "ok", count=len(mine))
    return mine


def main() -> None:
    serve(mcp)


if __name__ == "__main__":
    main()
