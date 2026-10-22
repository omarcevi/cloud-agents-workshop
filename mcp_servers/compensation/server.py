"""Compensation MCP server: salary bands and individual salaries.

It exists so the workshop can show Agent Gateway blocking it. The agent's code can
reach this server; the egress policy is what stops it (lab step 4).
Fictional data for the fictional company Kuzey Labs.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_servers.common import audit, caller_email, create_server, load_seed, serve

SERVER = "compensation"
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

Level = Literal["L3", "L4", "L5", "L6", "L7"]
Office = Literal["Istanbul", "Ankara", "Berlin"]

mcp = create_server(
    "kuzey-compensation",
    instructions="Kuzey Labs compensation data. Confidential.",
)

_data = load_seed("compensation.json")


@mcp.tool(annotations=READ_ONLY)
def get_salary_band(level: Level, office: Office = "Istanbul") -> dict[str, Any]:
    """Return the published salary band for a level in an office."""
    email = caller_email()
    currency = _data["currency_by_office"][office]
    low, high = _data["bands"][level][currency]
    audit(SERVER, "get_salary_band", email, "ok", level=level, office=office)
    return {
        "level": level,
        "office": office,
        "currency": currency,
        "min": low,
        "max": high,
    }


@mcp.tool(annotations=READ_ONLY)
def get_salary(
    employee_email: Annotated[str, Field(description="Work email of the employee.")],
) -> dict[str, Any]:
    """Return one employee's annual base salary. Confidential."""
    email = caller_email()
    target = employee_email.strip().lower()
    if target not in _data["salaries"]:
        raise ToolError(f"No salary record for {target}.")
    audit(SERVER, "get_salary", email, "ok", target=target)
    return {"employee": target, "annual_base_salary": _data["salaries"][target]}


def main() -> None:
    serve(mcp)


if __name__ == "__main__":
    main()
