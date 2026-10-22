"""Send one message to the deployed agent and print the conversation.

Unlike `agents-cli run --url`, which always uses the user id "cli-user", this lets you
pick the user (Gemini Enterprise passes the employee's email) and resume a session.

Usage (from the repo root):
  uv run python scripts/ask.py "How many leave days do I have?"
  uv run python scripts/ask.py --user ayse.demir@kuzeylabs.example "Book next Friday off"
  uv run python scripts/ask.py --session SESSION_ID "and the Monday after?"
  uv run python scripts/ask.py --json "..."   # machine-readable, used by scripts/check.sh
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

ROOT = Path(__file__).resolve().parents[1]


def engine_name() -> str:
    meta = json.loads((ROOT / "deployment_metadata.json").read_text())
    name = meta.get("remote_agent_runtime_id")
    if not name:
        sys.exit("No deployed agent in deployment_metadata.json. Run `agents-cli deploy` first.")
    return str(name)


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull the parts a check needs out of raw ADK events."""
    calls, results, authors, answer = [], [], [], []
    for event in events:
        author = event.get("author")
        if author and author not in authors:
            authors.append(author)
        for part in (event.get("content") or {}).get("parts") or []:
            if fc := part.get("function_call"):
                calls.append({"agent": author, "name": fc.get("name"), "args": fc.get("args") or {}})
            if fr := part.get("function_response"):
                results.append({"agent": author, "name": fr.get("name"), "response": fr.get("response")})
            if part.get("text") and not part.get("thought"):
                answer.append(part["text"])
    return {"authors": authors, "tool_calls": calls, "tool_results": results, "answer": "".join(answer)}


def ask(message: str, user: str, session_id: str | None) -> dict[str, Any]:
    """Call the Agent Runtime query API: :query to create a session, :streamQuery to chat."""
    name = engine_name()
    location = name.split("/")[3]
    base = f"https://{location}-aiplatform.googleapis.com/v1/{name}"
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    http = AuthorizedSession(credentials)
    if not session_id:
        response = http.post(
            f"{base}:query",
            json={"class_method": "async_create_session", "input": {"user_id": user}},
            timeout=60,
        )
        response.raise_for_status()
        session_id = response.json()["output"]["id"]
    response = http.post(
        f"{base}:streamQuery?alt=sse",
        json={
            "class_method": "async_stream_query",
            "input": {"user_id": user, "session_id": session_id, "message": message},
        },
        stream=True,
        timeout=300,
    )
    response.raise_for_status()
    events = []
    for line in response.iter_lines(decode_unicode=True):
        line = line.removeprefix("data:").strip() if line else ""
        if line.startswith("{"):
            events.append(json.loads(line))
    return {"user": user, "session_id": session_id, **summarize(events)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the deployed Workplace Assistant.")
    parser.add_argument("message")
    parser.add_argument("--user", default="cli-user", help="ADK user id (default: cli-user)")
    parser.add_argument("--session", help="Resume this session id")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args()
    result = ask(args.message, args.user, args.session)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    for call in result["tool_calls"]:
        print(f"  [{call['agent']}] {call['name']}({json.dumps(call['args'], ensure_ascii=False)})")
    print(f"\n{result['answer']}\n\nsession: {result['session_id']}  user: {result['user']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
