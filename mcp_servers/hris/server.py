"""HRIS MCP server: employee directory, leave balances and leave requests.

Fictional data for the fictional company Kuzey Labs, loaded from data/seed.
State lives in memory, so it resets when Cloud Run starts a new instance.
"""

from __future__ import annotations

import copy
import datetime as dt
import os
from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_servers.common import audit, caller_email, create_server, load_seed, serve

SERVER = "hris"
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)

LeaveType = Literal["ANNUAL", "ANNUAL_HALF_DAY", "SICK", "UNPAID"]

mcp = create_server(
    "kuzey-hris",
    instructions="Kuzey Labs HRIS. Every tool acts for the employee in the X-User-Email header.",
)

_employees: dict[str, dict[str, Any]] = {}
_balances: dict[str, dict[str, Any]] = {}
_requests: list[dict[str, Any]] = []


def reset() -> None:
    """Reload the seed data. Tests call this to start from a known state."""
    _employees.clear()
    _employees.update(
        {e["email"]: e for e in load_seed("employees.json")["employees"]}
    )
    leave = load_seed("leave.json")
    _balances.clear()
    _balances.update(copy.deepcopy(leave["balances"]))
    _requests.clear()
    _requests.extend(copy.deepcopy(leave["requests"]))


reset()


def _today() -> dt.date:
    # HRIS_TODAY pins the date for tests and rehearsals.
    if fixed := os.environ.get("HRIS_TODAY"):
        return dt.date.fromisoformat(fixed)
    return dt.date.today()


def _employee(email: str) -> dict[str, Any]:
    if email not in _employees:
        raise ToolError(f"{email} is not in the Kuzey Labs directory.")
    return _employees[email]


def _working_days(start: dt.date, end: dt.date) -> int:
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += dt.timedelta(days=1)
    return days


def _available(balance: dict[str, Any]) -> float:
    total = balance["entitlement"] + balance["carried_over"]
    return float(total - balance["used"] - balance["pending"])


@mcp.tool(annotations=READ_ONLY)
def get_my_profile() -> dict[str, Any]:
    """Return the calling employee's profile: title, level, team, office, manager and People Partner."""
    email = caller_email()
    employee = _employee(email)
    manager = _employees.get(employee["manager"] or "", {})
    partner = _employees.get(employee["people_partner"], {})
    audit(SERVER, "get_my_profile", email, "ok")
    return {
        **employee,
        "manager_name": manager.get("name"),
        "people_partner_name": partner.get("name"),
    }


@mcp.tool(annotations=READ_ONLY)
def search_directory(
    query: Annotated[str, Field(description="Name, team or office to search for.")],
) -> list[dict[str, str]]:
    """Search the employee directory by name, team or office. Returns public fields only."""
    email = caller_email()
    q = query.strip().lower()
    matches = [
        {k: e[k] for k in ("name", "email", "title", "team", "office")}
        for e in _employees.values()
        if q in e["name"].lower() or q == e["team"].lower() or q == e["office"].lower()
    ]
    audit(SERVER, "search_directory", email, "ok", matches=len(matches))
    return matches


@mcp.tool(annotations=READ_ONLY)
def get_leave_balance() -> dict[str, Any]:
    """Return the calling employee's annual leave balance for the current year, in working days."""
    email = caller_email()
    _employee(email)
    balance = _balances[email]
    audit(SERVER, "get_leave_balance", email, "ok")
    return {
        "employee": email,
        "year": 2026,
        **balance,
        "available": _available(balance),
    }


@mcp.tool(annotations=READ_ONLY)
def list_leave_requests() -> list[dict[str, Any]]:
    """List the calling employee's leave requests with their status."""
    email = caller_email()
    audit(SERVER, "list_leave_requests", email, "ok")
    return [r for r in _requests if r["employee"] == email]


@mcp.tool(annotations=WRITE)
def submit_leave_request(
    start_date: Annotated[str, Field(description="First day of leave, YYYY-MM-DD.")],
    end_date: Annotated[
        str, Field(description="Last day of leave, YYYY-MM-DD. Same as start_date for one day.")
    ],
    leave_type: LeaveType = "ANNUAL",
    note: str = "",
) -> dict[str, Any]:
    """Submit a leave request for the calling employee. Their team lead approves it in the HRIS."""
    email = caller_email()
    employee = _employee(email)
    try:
        start = dt.date.fromisoformat(start_date)
        end = dt.date.fromisoformat(end_date)
    except ValueError as exc:
        raise ToolError("Dates must be in YYYY-MM-DD format.") from exc
    if end < start:
        raise ToolError("end_date is before start_date.")
    if start < _today():
        raise ToolError(f"{start_date} is in the past. Today is {_today().isoformat()}.")
    days: float = _working_days(start, end)
    if days == 0:
        raise ToolError("The requested dates fall on a weekend.")
    if leave_type == "ANNUAL_HALF_DAY":
        days = 0.5
    balance = _balances[email]
    if leave_type.startswith("ANNUAL") and days > _available(balance):
        audit(SERVER, "submit_leave_request", email, "rejected", reason="balance")
        raise ToolError(
            f"Not enough leave: {days} days requested, {_available(balance)} available."
        )
    request = {
        "id": f"LV-{1100 + len(_requests)}",
        "employee": email,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": days,
        "leave_type": leave_type,
        "status": "PENDING",
        "approver": employee["manager"],
        "note": note,
    }
    _requests.append(request)
    if leave_type.startswith("ANNUAL"):
        balance["pending"] += days
    audit(SERVER, "submit_leave_request", email, "ok", request_id=request["id"])
    return {**request, "available_after_request": _available(balance)}


def main() -> None:
    serve(mcp)


if __name__ == "__main__":
    main()
