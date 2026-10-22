"""Optional: add approved leave to the employee's own Google Calendar.

The agent acts *on the employee's behalf* here (3-legged OAuth). Agent Identity
Auth Manager runs the consent flow once per employee and keeps their tokens in a
Google-managed vault. ADK asks for the token through `GcpAuthProvider` and injects
it as `credential`. Compare with the HRIS, which the agent calls with *its own*
identity.

Enabled only when CALENDAR_AUTH_PROVIDER is set (see the step 4 guide page).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
from google.adk.auth.auth_credential import AuthCredential

from app import config

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


async def create_calendar_event(
    summary: str,
    start_date: str,
    end_date: str,
    credential: AuthCredential | None = None,
) -> dict[str, Any]:
    """Add an all-day event, such as approved leave, to the employee's own Google Calendar.

    Args:
        summary: Event title, for example "Annual leave".
        start_date: First day, YYYY-MM-DD.
        end_date: Last day (inclusive), YYYY-MM-DD.
    """
    token = (
        credential.http.credentials.token if credential and credential.http else None
    )
    if not token:
        return {
            "error": "No calendar authorization yet. The employee needs to grant access."
        }
    end_exclusive = dt.date.fromisoformat(end_date) + dt.timedelta(days=1)
    event = {
        "summary": summary,
        "start": {"date": start_date},
        "end": {"date": end_exclusive.isoformat()},
        "transparency": "opaque",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {token}"},
            json=event,
        )
    if response.status_code >= 400:
        return {
            "error": f"Calendar API returned {response.status_code}: {response.text[:200]}"
        }
    created = response.json()
    return {
        "status": "created",
        "event_id": created.get("id"),
        "link": created.get("htmlLink"),
    }


def calendar_tools() -> list[Any]:
    """Return the calendar tool if an Auth Manager provider is configured, else nothing."""
    if not config.CALENDAR_AUTH_PROVIDER:
        return []
    # Needs the google-adk[agent-identity] extra.
    from google.adk.auth.auth_tool import AuthConfig
    from google.adk.auth.credential_manager import CredentialManager
    from google.adk.integrations.agent_identity import (
        GcpAuthProvider,
        GcpAuthProviderScheme,
    )
    from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool

    CredentialManager.register_auth_provider(GcpAuthProvider())
    auth_config = AuthConfig(
        auth_scheme=GcpAuthProviderScheme(
            name=config.CALENDAR_AUTH_PROVIDER, scopes=CALENDAR_SCOPES
        )
    )
    return [
        AuthenticatedFunctionTool(func=create_calendar_event, auth_config=auth_config)
    ]
