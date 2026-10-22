"""Find a trace of the deployed agent in Cloud Trace and print it as a waterfall (lab step 5).

Usage (from the repo root):
  uv run python scripts/trace.py                       # newest trace with a leave request
  uv run python scripts/trace.py --session SESSION_ID  # the trace of one session
  uv run python scripts/trace.py --span "execute_tool open_ticket"
  uv run python scripts/trace.py --json                # summary for scripts/check.sh

Cloud Trace has no gcloud read command, so this calls the Cloud Trace API v1.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

DEFAULT_SPAN = "execute_tool submit_leave_request"
SUB_AGENTS = {"hr_policy_agent", "leave_agent", "it_desk_agent"}


def _time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def find_trace(project: str, trace_filter: str, minutes: int) -> dict[str, Any] | None:
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    http = AuthorizedSession(credentials)
    base = f"https://cloudtrace.googleapis.com/v1/projects/{project}/traces"
    since = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes)
    response = http.get(
        base,
        params={
            "filter": trace_filter,
            "startTime": since.isoformat(),
            "view": "MINIMAL",
            "orderBy": "start desc",
            "pageSize": "1",
        },
        timeout=60,
    )
    response.raise_for_status()
    traces = response.json().get("traces", [])
    if not traces:
        return None
    detail = http.get(f"{base}/{traces[0]['traceId']}", timeout=60)
    detail.raise_for_status()
    trace: dict[str, Any] = detail.json()
    return trace


def summarize(trace: dict[str, Any]) -> dict[str, Any]:
    """Count what a check needs. Spans that are still arriving are simply not counted yet."""
    spans = sorted(trace["spans"], key=lambda s: s["startTime"])
    names = [s["name"] for s in spans]
    sub_agent_spans = [
        n
        for n in names
        if n.startswith("invoke_agent ") and n.split(" ", 1)[1] in SUB_AGENTS
    ]
    tool_spans = [
        n
        for n in names
        if n.startswith("execute_tool ") and n != "execute_tool transfer_to_agent"
    ]
    errors = [
        f"{s['name']}: {s['labels']['error.type']}"
        for s in spans
        if "error.type" in s.get("labels", {})
    ]
    return {
        "trace_id": trace["traceId"],
        "spans": len(spans),
        "sub_agent_spans": sub_agent_spans,
        "tool_spans": tool_spans,
        "model_calls": sum(n.startswith("generate_content") for n in names),
        "errors": errors,
    }


def waterfall(trace: dict[str, Any]) -> None:
    spans = sorted(trace["spans"], key=lambda s: s["startTime"])
    by_id = {s["spanId"]: s for s in spans}
    t0 = _time(spans[0]["startTime"])

    def depth(span: dict[str, Any]) -> int:
        d, parent = 0, span.get("parentSpanId")
        while parent in by_id:
            d, parent = d + 1, by_id[parent].get("parentSpanId")
        return d

    for span in spans:
        start = (_time(span["startTime"]) - t0).total_seconds()
        length = (_time(span["endTime"]) - _time(span["startTime"])).total_seconds()
        error = span.get("labels", {}).get("error.type")
        flag = f"  !! {error}" if error else ""
        print(f"{start:7.2f}s {length:7.2f}s  {'  ' * depth(span)}{span['name']}{flag}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Show a Workplace Assistant trace.")
    parser.add_argument("--project", default=None)
    parser.add_argument("--session", help="ADK session id (gen_ai.conversation.id)")
    parser.add_argument(
        "--span",
        default=DEFAULT_SPAN,
        help=f"span name to look for (default: {DEFAULT_SPAN!r})",
    )
    parser.add_argument("--minutes", type=int, default=120, help="how far back to look")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    project = str(args.project or google.auth.default()[1])
    trace_filter = (
        f"+gen_ai.conversation.id:{args.session}"
        if args.session
        else f'+span:"{args.span}"'
    )
    trace = find_trace(project, trace_filter, args.minutes)
    if not trace:
        print(
            f"No trace matching {trace_filter} in the last {args.minutes} minutes.",
            file=sys.stderr,
        )
        print(
            "Traces take a minute or two to arrive in Cloud Trace. Try again shortly.",
            file=sys.stderr,
        )
        return 1
    if args.json:
        print(json.dumps(summarize(trace)))
        return 0
    waterfall(trace)
    print(
        f"\nhttps://console.cloud.google.com/traces/explorer;traceId={trace['traceId']}?project={project}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
