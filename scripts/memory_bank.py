"""Inspect and configure the deployed agent's Memory Bank (lab step 3).

Usage (from the repo root):
  uv run python scripts/memory_bank.py configure        # apply infra/memory/memory-bank.json
  uv run python scripts/memory_bank.py list [--user ID]  # facts Memory Bank holds for a user
  uv run python scripts/memory_bank.py clear [--user ID] # delete a user's memories (rehearsal reset)

The user defaults to "cli-user", the fixed user id `agents-cli run` sends.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import agentplatform

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "app"  # App(name="app") in app/agent.py; Memory Bank scopes memories by app and user


def engine_name() -> str:
    meta = json.loads((ROOT / "deployment_metadata.json").read_text())
    name = meta.get("remote_agent_runtime_id")
    if not name:
        sys.exit(
            "No deployed agent in deployment_metadata.json. Run `agents-cli deploy` first."
        )
    return str(name)


def client_for(name: str) -> agentplatform.Client:
    _, project, _, location, *_ = name.split("/")
    return agentplatform.Client(project=project, location=location)


def configure(name: str) -> None:
    project = name.split("/")[1]
    raw = (ROOT / "infra" / "memory" / "memory-bank.json").read_text()
    config = json.loads(raw.replace("PROJECT_ID", project))
    config.pop("_comment", None)
    client_for(name).runtimes.update(
        name=name, config={"context_spec": {"memory_bank_config": config}}
    )
    labels = [
        t.get("custom_memory_topic", {}).get("label")
        or t["managed_memory_topic"]["managed_topic_enum"]
        for t in config["customization_configs"][0]["memory_topics"]
    ]
    print(f"Memory Bank topics set: {', '.join(labels)}")


def list_memories(name: str, user: str) -> int:
    scope = {"app_name": APP_NAME, "user_id": user}
    found = list(
        client_for(name).memory_banks.memories.retrieve(name=name, scope=scope)
    )
    if not found:
        print(
            f"No memories yet for user {user!r}. Memories appear about a minute after the turn; try again."
        )
        return 1
    for item in found:
        memory = item.memory
        topics = ", ".join(
            (t.custom_memory_topic_label or str(t.managed_memory_topic))
            for t in (memory.topics or [])
        )
        print(f"- {memory.fact}" + (f"  [{topics}]" if topics else ""))
    return 0


def clear(name: str, user: str) -> None:
    client = client_for(name)
    scope = {"app_name": APP_NAME, "user_id": user}
    count = 0
    for item in client.memory_banks.memories.retrieve(name=name, scope=scope):
        client.memory_banks.memories.delete(name=item.memory.name)
        count += 1
    print(f"Deleted {count} memories for user {user!r}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["configure", "list", "clear"])
    parser.add_argument(
        "--user", default="cli-user", help="ADK user id (default: cli-user)"
    )
    args = parser.parse_args()
    name = engine_name()
    if args.command == "configure":
        configure(name)
        return 0
    if args.command == "clear":
        clear(name, args.user)
        return 0
    return list_memories(name, args.user)


if __name__ == "__main__":
    sys.exit(main())
