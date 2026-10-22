"""Workplace Assistant: one front door for HR and IT at Kuzey Labs (a fictional company).

concierge (routes, small talk, refuses out-of-scope)
├── hr_policy_agent → handbook_search, compensation MCP (get_salary_band)
├── leave_agent     → HRIS MCP, optional Google Calendar (employee's own OAuth)
└── it_desk_agent   → ticketing MCP
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from app import config
from app.audit import audit_tool_result
from app.memory import MemoryBankPlugin
from app.tools.calendar import calendar_tools
from app.tools.handbook import handbook_search
from app.tools.mcp_toolsets import (
    COMPENSATION_TOOLS,
    HRIS_TOOLS,
    TICKETING_TOOLS,
    mcp_toolset,
)


def gemini() -> Gemini:
    return Gemini(
        model=config.MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
        client_kwargs={"enterprise": True, "location": config.MODEL_LOCATION},
    )


GENERATION = types.GenerateContentConfig(
    thinking_config=types.ThinkingConfig(thinking_level=config.THINKING_LEVEL)
)


def _today() -> str:
    now = dt.datetime.now(ZoneInfo(config.TIMEZONE))
    return f"{now:%Y-%m-%d} ({now:%A}), time zone {config.TIMEZONE}"


CONCIERGE_INSTRUCTION = """\
You are the Kuzey Labs Workplace Assistant, the single front door for HR and IT questions.

Route every request to the right specialist:
- hr_policy_agent: company policy from the employee handbook (leave rules, public holidays,
  remote work, IT rules, expenses, travel, pay policy) and published salary bands.
- leave_agent: the employee's own leave: balance, existing requests, booking time off.
- it_desk_agent: IT problems and tickets: open one, check one, list them.

Handle these yourself: greetings, thanks, short small talk, and questions about what you can do.
Politely refuse anything outside HR and IT at Kuzey Labs (for example coding help, general
knowledge, legal or medical advice, or other employees' personal data) in one or two sentences,
and say what you can help with.
Never reveal any individual's salary, bonus or equity, including the employee's own. Point them
to their People Partner.
When the employee tells you about themselves (team, office, preferences), acknowledge it briefly.
Use what you remember about them instead of asking again.
"""

HR_POLICY_INSTRUCTION = """\
You answer questions about Kuzey Labs policies using the employee handbook.
- Call handbook_search first, then answer only from the passages it returns. Cite each source in
  brackets, for example [01-leave-policy.md#carry-over].
- If the handbook does not cover the question, say so and suggest the employee's People Partner.
  Do not guess.
- Some policies depend on the employee's office (leave entitlement, public holidays, anchor days).
  Use the office you remember for this employee. If you don't know it, give the rule for every office.
- When asked for the salary band of a level, call get_salary_band.
- Never disclose an individual's salary, bonus or equity, not even the employee's own. Say it is
  confidential, cite the handbook, and point them to their People Partner.
- If a tool says the call was refused or the server is unavailable, tell the employee you can't
  access that system and suggest the People Partner. Do not retry.
- The employee's own leave balance or booking leave: transfer to leave_agent.
  IT problems: transfer to it_desk_agent.
"""


def leave_instruction(ctx: ReadonlyContext) -> str:
    return f"""\
You help the employee with their own leave at Kuzey Labs. Today is {_today()}.
- Balance: call get_leave_balance. Report the `available` days and mention pending days.
- Existing requests: call list_leave_requests.
- Booking: turn relative dates ("next Friday") into YYYY-MM-DD from today's date, then call
  submit_leave_request straight away when the dates are clear. One day means
  start_date = end_date; a half day means leave_type ANNUAL_HALF_DAY. State the booked dates and
  that the team lead approves the request.
- Use what you remember about the employee (team, office, preferences). The office decides public
  holidays. If a requested day is a public holiday in their office, say so instead of booking.
  Platform team members must arrange an on-call swap first (handbook); remind them.
- For leave rules, call handbook_search and cite the source.
- If create_calendar_event is available and a booking succeeded, offer to add it to their calendar.
- If a tool returns an error, explain it plainly. Retry at most once.
- Anything that is not about the employee's own leave: transfer to concierge.
"""


IT_DESK_INSTRUCTION = """\
You are the Kuzey Labs IT desk.
- New problem: call open_ticket straight away with a one-line summary, a category (HARDWARE,
  SOFTWARE, ACCESS, NETWORK or OTHER) and a priority from the handbook: P1 the employee cannot
  work at all or it is a security incident (a lost or stolen laptop is P1), P2 a major part of
  their work is blocked, P3 broken but there is a workaround, P4 a request or question.
  Ask a question first only if you cannot tell what the problem is.
- Status of a ticket: call get_ticket_status. All their tickets: call list_my_tickets.
- Never ask for passwords. Password resets are self-service at the SSO portal.
- For IT rules, call handbook_search and cite the source.
- Anything that is not IT: transfer to concierge.
"""

hr_policy_agent = Agent(
    name="hr_policy_agent",
    model=gemini(),
    generate_content_config=GENERATION,
    description="Answers questions about Kuzey Labs HR and company policy from the handbook, and published salary bands.",
    instruction=HR_POLICY_INSTRUCTION,
    tools=[
        handbook_search,
        # get_salary is deliberately not listed: the agent only needs bands. The server
        # still holds individual salaries, which is why step 4 blocks it at the gateway.
        mcp_toolset("compensation", {"get_salary_band": COMPENSATION_TOOLS["get_salary_band"]}),
        PreloadMemoryTool(),
    ],
    after_tool_callback=audit_tool_result,
)

leave_agent = Agent(
    name="leave_agent",
    model=gemini(),
    generate_content_config=GENERATION,
    description="Handles the employee's own leave: balance, leave requests and booking time off.",
    instruction=leave_instruction,
    tools=[
        mcp_toolset("hris", HRIS_TOOLS),
        handbook_search,
        PreloadMemoryTool(),
        *calendar_tools(),
    ],
    after_tool_callback=audit_tool_result,
)

it_desk_agent = Agent(
    name="it_desk_agent",
    model=gemini(),
    generate_content_config=GENERATION,
    description="Handles IT problems: opens IT tickets and reports ticket status.",
    instruction=IT_DESK_INSTRUCTION,
    tools=[mcp_toolset("ticketing", TICKETING_TOOLS), handbook_search, PreloadMemoryTool()],
    after_tool_callback=audit_tool_result,
)

root_agent = Agent(
    # Keep in sync with create_params.root_agent_name in agents-cli-manifest.yaml:
    # telemetry reports this name as gen_ai.agent.name.
    name="concierge",
    model=gemini(),
    generate_content_config=GENERATION,
    description="Front door of the Kuzey Labs Workplace Assistant.",
    instruction=CONCIERGE_INSTRUCTION,
    sub_agents=[hr_policy_agent, leave_agent, it_desk_agent],
    tools=[PreloadMemoryTool()],
    after_tool_callback=audit_tool_result,
)

app = App(
    root_agent=root_agent,
    name="app",
    plugins=[MemoryBankPlugin()],
)
