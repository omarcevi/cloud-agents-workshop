"""Audit log for tool calls that a policy refused.

Every agent gets `audit_tool_result` as its after_tool_callback. When a tool result
says the call was denied (Agent Gateway, Cloud Run IAM) or the server was
unreachable, it writes one `workplace.tool_blocked` event. A logs-based metric
counts these events for the monitoring dashboard (infra/monitoring/).
"""

from __future__ import annotations

import re
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from opentelemetry._logs import LogRecord, SeverityNumber, get_logger

EVENT_NAME = "workplace.tool_blocked"

_otel = get_logger("workplace.audit")

# Agent Gateway's egress denial text, from its troubleshooting docs.
_GATEWAY = re.compile(r"Egress request is not authorized|\b498\b", re.IGNORECASE)
# Cloud Run (or any other server) refusing the agent's identity.
_PERMISSION = re.compile(
    r"\b403\b|Forbidden|PERMISSION_DENIED|not have permission", re.IGNORECASE
)


def classify(result: Any) -> str | None:
    """Return why a tool result is a refusal, or None if the call went through."""
    if not isinstance(result, dict):
        return None
    if result.get("status") == "unavailable":
        text = str(result.get("error", ""))
    elif "error" in result:
        text = str(result["error"])
    else:
        return None
    if _GATEWAY.search(text):
        return "gateway_denied"
    if _PERMISSION.search(text):
        return "permission_denied"
    if result.get("status") == "unavailable":
        return "unavailable"
    return None


def log_blocked(tool: str, agent: str, reason: str, detail: str = "") -> None:
    """Emit the audit event as an OpenTelemetry log record (and print it for local runs).

    On Agent Runtime the OTel record lands in Cloud Logging as jsonPayload with
    labels."event.name" and the active trace id.
    """
    body = {
        "event": EVENT_NAME,
        "tool": tool,
        "agent": agent,
        "reason": reason,
        "detail": detail[:300],
    }
    _otel.emit(
        LogRecord(
            event_name=EVENT_NAME,
            severity_number=SeverityNumber.WARN,
            body=body,
            attributes={"tool": tool, "reason": reason},
        )
    )
    # Local runs: visible in the terminal. (On Agent Runtime the OTel record above is
    # what reaches Cloud Logging.)
    print(f"{EVENT_NAME} tool={tool} agent={agent} reason={reason}", flush=True)


def audit_tool_result(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any
) -> None:
    """after_tool_callback: log refused calls, leave the result unchanged."""
    reason = classify(tool_response)
    if reason:
        detail = (
            str(tool_response.get("error", ""))
            if isinstance(tool_response, dict)
            else ""
        )
        log_blocked(tool.name, tool_context.agent_name, reason, detail)
    return None
