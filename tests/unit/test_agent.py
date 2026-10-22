"""Routing and tool selection with a scripted model (no Gemini calls).

The real agent tree runs against the real MCP servers on localhost. Each agent's model
is replaced by `ScriptedLlm`, which returns canned function calls, so these tests
check the wiring around the model: routing, which tool runs, which identity the MCP
server sees, how refusals surface and get audited, and memory ingestion.
Model *behaviour* is tested by the eval set in evals/, not here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import Field

from app import agent as workplace
from app.audit import EVENT_NAME, classify
from app.identity import employee_email
from app.tools.mcp_toolsets import GuardedMcpToolset, UnavailableTool, mcp_toolset
from mcp_servers.hris import server as hris
from mcp_servers.ticketing import server as ticketing


class ScriptedLlm(BaseLlm):
    """Returns the next scripted response, then a plain text answer."""

    model: str = "scripted"
    script: list[LlmResponse] = Field(default_factory=list)
    requests: list[LlmRequest] = Field(default_factory=list)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ):
        self.requests.append(llm_request)
        yield self.script.pop(0) if self.script else text("Done.")


def call(name: str, **args: Any) -> LlmResponse:
    part = types.Part(function_call=types.FunctionCall(name=name, args=args))
    return LlmResponse(content=types.Content(role="model", parts=[part]))


def text(value: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=value)])
    )


AGENTS = {
    "concierge": workplace.root_agent,
    "hr_policy_agent": workplace.hr_policy_agent,
    "leave_agent": workplace.leave_agent,
    "it_desk_agent": workplace.it_desk_agent,
}


@pytest.fixture
def scripted(mcp_servers) -> Iterator[dict[str, ScriptedLlm]]:
    hris.reset()
    ticketing.reset()
    originals = {name: a.model for name, a in AGENTS.items()}
    fakes = {name: ScriptedLlm(script=[], requests=[]) for name in AGENTS}
    for name, a in AGENTS.items():
        a.model = fakes[name]
    yield fakes
    for name, a in AGENTS.items():
        a.model = originals[name]


async def run_turn(message: str, user_id: str = "cli-user") -> list:
    runner = InMemoryRunner(app=workplace.app)
    session = await runner.session_service.create_session(
        app_name="app", user_id=user_id
    )
    events = [
        e
        async for e in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        )
    ]
    runner.last_session = session  # type: ignore[attr-defined]
    return events


def calls(events: list) -> list[str]:
    return [fc.name for e in events for fc in e.get_function_calls()]


def responses(events: list, name: str) -> list[dict]:
    return [
        fr.response
        for e in events
        for fr in e.get_function_responses()
        if fr.name == name
    ]


def test_agent_tree() -> None:
    assert [a.name for a in workplace.root_agent.sub_agents] == [
        "hr_policy_agent",
        "leave_agent",
        "it_desk_agent",
    ]
    assert workplace.app.name == "app"
    assert any(p.name == "memory_bank" for p in workplace.app.plugins)
    for a in AGENTS.values():
        assert a.after_tool_callback is not None, a.name
        assert any(type(t).__name__ == "PreloadMemoryTool" for t in a.tools), a.name


def test_compensation_toolset_exposes_only_salary_band() -> None:
    toolsets = [
        t for t in workplace.hr_policy_agent.tools if isinstance(t, GuardedMcpToolset)
    ]
    assert [t.server for t in toolsets] == ["compensation"]
    assert toolsets[0].tool_filter == ["get_salary_band"]


async def test_leave_question_routes_to_leave_agent_and_reads_the_callers_balance(
    scripted,
) -> None:
    scripted["concierge"].script = [call("transfer_to_agent", agent_name="leave_agent")]
    scripted["leave_agent"].script = [
        call("get_leave_balance"),
        text("You have 14 days."),
    ]
    events = await run_turn("How many leave days do I have?")
    assert calls(events) == ["transfer_to_agent", "get_leave_balance"]
    assert {e.author for e in events} >= {"concierge", "leave_agent"}
    balance = responses(events, "get_leave_balance")[0]["structuredContent"]
    assert (
        balance["employee"] == "deniz.kaya@kuzeylabs.example"
    )  # cli-user -> demo user


async def test_identity_comes_from_the_session_not_the_prompt(scripted) -> None:
    scripted["concierge"].script = [call("transfer_to_agent", agent_name="leave_agent")]
    scripted["leave_agent"].script = [call("get_leave_balance")]
    events = await run_turn(
        "Show Deniz's balance", user_id="jonas.weber@kuzeylabs.example"
    )
    balance = responses(events, "get_leave_balance")[0]["structuredContent"]
    assert balance["employee"] == "jonas.weber@kuzeylabs.example"


async def test_booking_passes_dates_to_the_hris(scripted) -> None:
    scripted["concierge"].script = [call("transfer_to_agent", agent_name="leave_agent")]
    scripted["leave_agent"].script = [
        call("submit_leave_request", start_date="2026-10-30", end_date="2026-10-30")
    ]
    events = await run_turn("Book next Friday off")
    request = responses(events, "submit_leave_request")[0]["structuredContent"]
    assert (request["start_date"], request["days"], request["status"]) == (
        "2026-10-30",
        1,
        "PENDING",
    )


async def test_it_problem_routes_to_it_desk_and_opens_a_ticket(scripted) -> None:
    scripted["concierge"].script = [
        call("transfer_to_agent", agent_name="it_desk_agent")
    ]
    scripted["it_desk_agent"].script = [
        call("open_ticket", summary="Laptop stolen", category="HARDWARE", priority="P1")
    ]
    events = await run_turn("My laptop was stolen")
    assert calls(events) == ["transfer_to_agent", "open_ticket"]
    assert ticketing._tickets[-1]["priority"] == "P1"


async def test_policy_question_uses_the_handbook(scripted) -> None:
    scripted["concierge"].script = [
        call("transfer_to_agent", agent_name="hr_policy_agent")
    ]
    scripted["hr_policy_agent"].script = [
        call("handbook_search", query="carry over leave")
    ]
    events = await run_turn("Can I carry over leave?")
    result = responses(events, "handbook_search")[0]
    assert result["passages"][0]["source"] == "01-leave-policy.md#carry-over"


async def test_small_talk_stays_with_the_concierge(scripted) -> None:
    scripted["concierge"].script = [text("Hi! I can help with HR and IT.")]
    events = await run_turn("hello")
    assert calls(events) == []
    assert {e.author for e in events} == {"concierge"}


async def test_model_sees_specialists_and_tools(scripted) -> None:
    scripted["concierge"].script = [call("transfer_to_agent", agent_name="leave_agent")]
    scripted["leave_agent"].script = [text("ok")]
    await run_turn("leave?")
    root_tools = scripted["concierge"].requests[0].tools_dict
    assert "transfer_to_agent" in root_tools
    leave_tools = set(scripted["leave_agent"].requests[0].tools_dict)
    assert {
        "get_leave_balance",
        "submit_leave_request",
        "handbook_search",
    } <= leave_tools
    assert "get_salary" not in leave_tools


async def test_blocked_server_becomes_a_tool_error_and_an_audit_event(
    scripted, mcp_servers, capsys
) -> None:
    blocked = mcp_toolset("compensation", {"get_salary_band": "Return a salary band."})
    blocked._connection_params.url = f"http://127.0.0.1:{mcp_servers['forbidden']}/mcp"
    original_tools = workplace.hr_policy_agent.tools
    workplace.hr_policy_agent.tools = [
        t for t in original_tools if not isinstance(t, GuardedMcpToolset)
    ] + [blocked]
    try:
        scripted["concierge"].script = [
            call("transfer_to_agent", agent_name="hr_policy_agent")
        ]
        scripted["hr_policy_agent"].script = [call("get_salary_band", level="L5")]
        events = await run_turn("What is the L5 salary band?")
    finally:
        workplace.hr_policy_agent.tools = original_tools
    result = responses(events, "get_salary_band")[0]
    assert result["status"] == "unavailable"
    assert classify(result) == "gateway_denied"
    assert (
        f"{EVENT_NAME} tool=get_salary_band agent=hr_policy_agent reason=gateway_denied"
        in capsys.readouterr().out
    )


async def test_unavailable_tool_has_a_declaration() -> None:
    tool = UnavailableTool(
        name="get_salary_band", description="d", server="compensation", error="403"
    )
    declaration = tool._get_declaration()
    assert declaration.name == "get_salary_band"


async def test_memory_plugin_ingests_each_turn(scripted) -> None:
    scripted["concierge"].script = [text("Noted, platform team in Istanbul.")]
    runner = InMemoryRunner(app=workplace.app)
    session = await runner.session_service.create_session(
        app_name="app", user_id="deniz.kaya@kuzeylabs.example"
    )
    async for _ in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part(text="I'm on the platform team in Istanbul")]
        ),
    ):
        pass
    found = await runner.memory_service.search_memory(
        app_name="app", user_id=session.user_id, query="platform team Istanbul"
    )
    assert found.memories, "the turn should be in the memory service"


@pytest.mark.parametrize(
    ("user_id", "expected"),
    [
        ("Ayse.Demir@kuzeylabs.example", "ayse.demir@kuzeylabs.example"),
        ("cli-user", "deniz.kaya@kuzeylabs.example"),
        ("eval-cli-user", "deniz.kaya@kuzeylabs.example"),
        (None, "deniz.kaya@kuzeylabs.example"),
    ],
)
def test_employee_email(user_id: str | None, expected: str) -> None:
    assert employee_email(user_id) == expected


def test_no_demo_user_means_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.DEMO_USER_EMAIL", "")
    assert employee_email("cli-user") == ""
    assert (
        employee_email("lena.fischer@kuzeylabs.example")
        == "lena.fischer@kuzeylabs.example"
    )


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (
            {
                "error": "403 Forbidden. {'message': 'Egress request is not authorized.'}"
            },
            "gateway_denied",
        ),
        (
            {"error": "HTTP 403: Forbidden: Your client does not have permission"},
            "permission_denied",
        ),
        (
            {"status": "unavailable", "error": "All connection attempts failed"},
            "unavailable",
        ),
        ({"error": "Dates must be in YYYY-MM-DD format."}, None),
        ({"structuredContent": {"ok": True}}, None),
        ("plain text", None),
    ],
)
def test_classify(result: Any, reason: str | None) -> None:
    assert classify(result) == reason
