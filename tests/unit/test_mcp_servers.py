"""MCP tools against the seed data, through an in-memory FastMCP client (no network)."""

from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_servers.compensation import server as compensation
from mcp_servers.hris import server as hris
from mcp_servers.ticketing import server as ticketing

DENIZ = "deniz.kaya@kuzeylabs.example"


@pytest.fixture(autouse=True)
def as_deniz(monkeypatch: pytest.MonkeyPatch) -> None:
    # In memory there is no HTTP request, so the X-User-Email header falls back to this.
    monkeypatch.setenv("DEFAULT_USER_EMAIL", DENIZ)
    monkeypatch.setenv("HRIS_TODAY", "2026-10-22")
    hris.reset()
    ticketing.reset()


async def call(server, tool: str, args: dict | None = None):
    async with Client(server.mcp) as client:
        return (await client.call_tool(tool, args or {})).data


async def test_read_tools_are_annotated_read_only() -> None:
    expected = {
        hris: {"get_my_profile", "search_directory", "get_leave_balance", "list_leave_requests"},
        ticketing: {"get_ticket_status", "list_my_tickets"},
        compensation: {"get_salary_band", "get_salary"},
    }
    for server, read_only in expected.items():
        async with Client(server.mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
        for name, tool in tools.items():
            assert tool.annotations.read_only_hint is (name in read_only), name
            assert tool.annotations.destructive_hint is False, name


async def test_leave_balance_is_for_the_caller() -> None:
    balance = await call(hris, "get_leave_balance")
    assert balance["employee"] == DENIZ
    assert balance["available"] == 22 + 3 - 9 - 2


async def test_profile_includes_team_office_and_manager() -> None:
    profile = await call(hris, "get_my_profile")
    assert (profile["team"], profile["office"]) == ("Platform", "Istanbul")
    assert profile["manager_name"] == "Ayşe Demir"


async def test_directory_search_returns_public_fields_only() -> None:
    results = await call(hris, "search_directory", {"query": "platform"})
    assert {r["name"] for r in results} == {"Deniz Kaya", "Ayşe Demir", "Jonas Weber"}
    assert all(set(r) == {"name", "email", "title", "team", "office"} for r in results)


async def test_submit_leave_request_counts_working_days_and_updates_balance() -> None:
    # 2026-10-30 is a Friday, 2026-11-02 a Monday: two working days.
    request = await call(
        hris, "submit_leave_request", {"start_date": "2026-10-30", "end_date": "2026-11-02"}
    )
    assert request["days"] == 2
    assert request["status"] == "PENDING"
    assert request["approver"] == "ayse.demir@kuzeylabs.example"
    balance = await call(hris, "get_leave_balance")
    assert balance["pending"] == 4
    assert request["available_after_request"] == balance["available"] == 12


async def test_half_day_counts_half() -> None:
    request = await call(
        hris,
        "submit_leave_request",
        {"start_date": "2026-10-30", "end_date": "2026-10-30", "leave_type": "ANNUAL_HALF_DAY"},
    )
    assert request["days"] == 0.5


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        ("2026-10-01", "2026-10-01", "in the past"),
        ("2026-10-31", "2026-11-01", "weekend"),
        ("2026-11-05", "2026-11-04", "before start_date"),
        ("30/10/2026", "30/10/2026", "YYYY-MM-DD"),
        ("2026-11-02", "2026-12-31", "Not enough leave"),
    ],
)
async def test_submit_leave_request_rejects_bad_requests(start: str, end: str, message: str) -> None:
    with pytest.raises(ToolError, match=message):
        await call(hris, "submit_leave_request", {"start_date": start, "end_date": end})


async def test_unknown_caller_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEFAULT_USER_EMAIL", "nobody@example.com")
    with pytest.raises(ToolError, match="not in the Kuzey Labs directory"):
        await call(hris, "get_leave_balance")


async def test_missing_caller_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEFAULT_USER_EMAIL")
    with pytest.raises(ToolError, match="X-User-Email"):
        await call(hris, "get_leave_balance")


async def test_open_ticket_and_read_it_back() -> None:
    ticket = await call(
        ticketing,
        "open_ticket",
        {"summary": "Laptop stolen at the airport", "category": "HARDWARE", "priority": "P1"},
    )
    assert ticket["requester"] == DENIZ and ticket["status"] == "OPEN"
    status = await call(ticketing, "get_ticket_status", {"ticket_id": ticket["id"].lower()})
    assert status["summary"] == "Laptop stolen at the airport"


async def test_list_my_tickets_filters_by_status() -> None:
    mine = await call(ticketing, "list_my_tickets")
    assert {t["id"] for t in mine} == {"IT-2201", "IT-2187"}
    resolved = await call(ticketing, "list_my_tickets", {"status": "RESOLVED"})
    assert [t["id"] for t in resolved] == ["IT-2187"]


async def test_other_peoples_tickets_look_missing() -> None:
    with pytest.raises(ToolError, match="No ticket IT-2210"):
        await call(ticketing, "get_ticket_status", {"ticket_id": "IT-2210"})


async def test_invalid_ticket_category_is_rejected_by_schema() -> None:
    with pytest.raises(ToolError):
        await call(ticketing, "open_ticket", {"summary": "x", "category": "COFFEE"})


async def test_salary_band_uses_office_currency() -> None:
    band = await call(compensation, "get_salary_band", {"level": "L4", "office": "Berlin"})
    assert band == {"level": "L4", "office": "Berlin", "currency": "EUR", "min": 58000, "max": 72000}


async def test_get_salary_exists_so_the_gateway_has_something_to_block() -> None:
    salary = await call(compensation, "get_salary", {"employee_email": "AYSE.DEMIR@kuzeylabs.example"})
    assert salary["annual_base_salary"] == 2210000
