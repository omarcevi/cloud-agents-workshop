"""Turn a production session into a new eval case (lab step 6).

agents-cli has no command that imports a deployed agent's session as an eval case, so
this script does it: it fetches the session from Agent Runtime, shows what the agent
did, and appends a case to evals/cases.yaml with the last user message as the prompt.
You then edit the expected behaviour (what the agent *should* have done) and rebuild:

  uv run python scripts/session_to_eval_case.py SESSION_ID --id republic_day_regression
  # edit the new case at the end of evals/cases.yaml
  uv run python evals/build_datasets.py && ./scripts/eval.sh behaviour

Find session ids in the console (Deployments > workplace-assistant > Sessions), in the
trace (gen_ai.conversation.id), or in the output of scripts/ask.py.
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
CASES = ROOT / "evals" / "cases.yaml"


def fetch_session(session_id: str, user: str) -> dict[str, Any]:
    name = json.loads((ROOT / "deployment_metadata.json").read_text())["remote_agent_runtime_id"]
    location = name.split("/")[3]
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    response = AuthorizedSession(credentials).post(
        f"https://{location}-aiplatform.googleapis.com/v1/{name}:query",
        json={"class_method": "async_get_session", "input": {"user_id": user, "session_id": session_id}},
        timeout=60,
    )
    response.raise_for_status()
    session: dict[str, Any] = response.json()["output"]
    return session


def last_turn(session: dict[str, Any]) -> tuple[str, list[str], str]:
    """The last user message, the tools the agent called after it, and its final answer."""
    prompt, calls, answer = "", [], ""
    for event in session.get("events", []):
        parts = (event.get("content") or {}).get("parts") or []
        if event.get("author") == "user":
            texts = [p["text"] for p in parts if p.get("text")]
            if texts:
                prompt, calls, answer = " ".join(texts), [], ""
            continue
        for part in parts:
            if call := part.get("function_call"):
                calls.append(f"{event.get('author')}: {call['name']}({json.dumps(call.get('args') or {}, ensure_ascii=False)})")
            if part.get("text") and not part.get("thought"):
                answer = part["text"]
    return prompt, calls, answer


def yaml_case(case_id: str, session_id: str, prompt: str) -> str:
    return (
        f"  - id: {case_id}\n"
        f"    prompt: {json.dumps(prompt, ensure_ascii=False)}\n"
        f"    note: From production session {session_id}. Edit the expectations below to the correct behaviour.\n"
        f"    expected_agent: leave_agent            # TODO: who should answer?\n"
        f"    expected_tool_calls: []                # TODO: e.g. [{{name: get_leave_balance}}]\n"
        f"    forbidden_tools: []                    # TODO: e.g. [submit_leave_request]\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a production session to evals/cases.yaml.")
    parser.add_argument("session_id")
    parser.add_argument("--user", default="cli-user", help="user id of the session (default: cli-user)")
    parser.add_argument("--id", dest="case_id", required=True, help="id for the new eval case")
    parser.add_argument("--dry-run", action="store_true", help="print the case instead of appending it")
    args = parser.parse_args()

    prompt, calls, answer = last_turn(fetch_session(args.session_id, args.user))
    if not prompt:
        print("That session has no user message.", file=sys.stderr)
        return 1
    print(f"User:   {prompt}")
    for call in calls:
        print(f"Tool:   {call}")
    print(f"Agent:  {answer[:300]}\n")
    case = yaml_case(args.case_id, args.session_id, prompt)
    if args.dry_run:
        print(case)
        return 0
    text = CASES.read_text(encoding="utf-8")
    marker = "\nhandbook:\n"
    if marker not in text:
        print("evals/cases.yaml has no `handbook:` section to insert before.", file=sys.stderr)
        return 1
    CASES.write_text(text.replace(marker, f"\n{case}{marker}", 1), encoding="utf-8")
    print(f"Added case {args.case_id!r} to the behaviour suite in evals/cases.yaml. Edit its TODO lines, then:")
    print("  uv run python evals/build_datasets.py && ./scripts/eval.sh behaviour")
    return 0


if __name__ == "__main__":
    sys.exit(main())
