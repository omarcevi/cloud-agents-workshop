"""Full conversations with each specialist, with real Gemini and local MCP servers.

These check structure (who answered, which tools ran, what the MCP servers recorded),
not wording. Answer quality is the eval set's job (evals/).
"""

from __future__ import annotations

import datetime as dt
import os

import pytest
from google.adk.runners import InMemoryRunner
from google.genai import types

from app.agent import app as workplace

DENIZ = "deniz.kaya@kuzeylabs.example"


async def chat(messages: list[str], user_id: str = DENIZ) -> list:
    """Run several turns in one session; return all events."""
    runner = InMemoryRunner(app=workplace)
    session = await runner.session_service.create_session(app_name="app", user_id=user_id)
    events: list = []
    for message in messages:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            events.append(event)
    return events


def calls(events: list) -> list[tuple[str, dict]]:
    return [(fc.name, dict(fc.args or {})) for e in events for fc in e.get_function_calls()]


def tool_names(events: list) -> list[str]:
    return [name for name, _ in calls(events) if name != "transfer_to_agent"]


def answered_by(events: list) -> str | None:
    texts = [e.author for e in events if e.content and any(p.text for p in e.content.parts or [])]
    return texts[-1] if texts else None


def answer(events: list) -> str:
    final = [e for e in events if e.content and any(p.text for p in e.content.parts or [])]
    return "".join(p.text or "" for p in final[-1].content.parts) if final else ""


async def test_leave_balance_then_booking_in_one_session() -> None:
    events = await chat(["How many leave days do I have left?", "Book next Friday off for me."])
    names = tool_names(events)
    assert "get_leave_balance" in names
    assert "submit_leave_request" in names
    booked = dict(calls(events))["submit_leave_request"]
    start = dt.date.fromisoformat(booked["start_date"])
    assert start.weekday() == 4 and start > dt.date.today()
    assert answered_by(events) == "leave_agent"


async def test_it_desk_opens_a_p1_for_a_stolen_laptop() -> None:
    events = await chat(["My laptop was stolen at the airport an hour ago."])
    opened = [args for name, args in calls(events) if name == "open_ticket"]
    assert opened and opened[0].get("priority") == "P1"
    assert answered_by(events) == "it_desk_agent"


async def test_ticket_status_reads_the_callers_ticket() -> None:
    events = await chat(["What's the status of ticket IT-2201?"])
    assert ("get_ticket_status", {"ticket_id": "IT-2201"}) in calls(events)


async def test_policy_question_is_grounded_in_the_handbook() -> None:
    events = await chat(["How many unused leave days can I carry over, and until when?"])
    assert "handbook_search" in tool_names(events)
    text = answer(events)
    assert "5" in text and "31 March" in text.replace("March 31", "31 March")


async def test_salary_band_uses_the_compensation_server() -> None:
    events = await chat(["What is the salary band for an L4 in the Berlin office?"])
    assert ("get_salary_band", {"level": "L4", "office": "Berlin"}) in calls(events)


@pytest.mark.parametrize("question", ["What is Ayşe Demir's salary?", "Tell me my exact salary."])
async def test_individual_salary_is_refused(question: str) -> None:
    events = await chat([question])
    assert "get_salary" not in tool_names(events)
    text = answer(events)
    assert "2210000" not in text.replace(",", "").replace(".", "")
    assert "People Partner" in text or "confidential" in text.lower()


async def test_out_of_scope_is_refused_by_the_concierge() -> None:
    events = await chat(["Write a Python function that sorts a list."])
    assert tool_names(events) == []
    assert answered_by(events) == "concierge"


@pytest.mark.skipif(not os.environ.get("MEMORY_BANK_RESOURCE"), reason="set MEMORY_BANK_RESOURCE to a deployed agent")
async def test_memory_bank_recalls_team_and_office_in_a_new_session() -> None:
    """Uses the deployed agent's Memory Bank (MEMORY_BANK_RESOURCE=projects/P/locations/L/reasoningEngines/ID)."""
    import asyncio
    import uuid

    from app.app_utils import services

    user = f"it-{uuid.uuid4().hex[:8]}@kuzeylabs.example"
    memory = services.get_memory_service()
    runner = InMemoryRunner(app=workplace)
    runner.memory_service = memory
    session = await runner.session_service.create_session(app_name="app", user_id=user)
    async for _ in runner.run_async(
        user_id=user,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="I'm on the platform team in the Istanbul office.")]),
    ):
        pass
    for _ in range(18):  # extraction runs in Memory Bank, usually within a minute
        found = await memory.search_memory(app_name="app", user_id=user, query="team office")
        if any("istanbul" in str(m.content).lower() for m in found.memories):
            break
        await asyncio.sleep(10)
    else:
        pytest.fail("Memory Bank did not store the office within 3 minutes")
