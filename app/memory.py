"""Memory Bank wiring: save each turn, recall at the start of the next one.

- Recall: every agent has PreloadMemoryTool, which searches the user's memories with
  the new message and adds the matches to the model's instructions.
- Save: `MemoryBankPlugin` runs after every turn, whichever agent answered, and asks
  Memory Bank to extract facts from that turn's events.

Sessions hold one conversation. Memory Bank holds facts about one user across all
their conversations, scoped by (app name, user id).
"""

from __future__ import annotations

import logging

from google.adk.agents.invocation_context import InvocationContext
from google.adk.plugins.base_plugin import BasePlugin

_log = logging.getLogger(__name__)


class MemoryBankPlugin(BasePlugin):
    """After each turn, send that turn's events to the memory service."""

    def __init__(self) -> None:
        super().__init__(name="memory_bank")

    async def after_run_callback(self, *, invocation_context: InvocationContext) -> None:
        memory = invocation_context.memory_service
        if memory is None:
            return
        session = invocation_context.session
        events = [e for e in session.events if e.invocation_id == invocation_context.invocation_id]
        if not events:
            return
        try:
            # wait_for_completion=False starts generation on the server and returns.
            # Extraction then runs in Memory Bank, not in this container.
            await memory.add_events_to_memory(
                app_name=session.app_name,
                user_id=session.user_id,
                session_id=session.id,
                events=events,
                custom_metadata={"wait_for_completion": False},
            )
        except Exception:  # memory is best effort; never fail the user's turn
            _log.exception("Could not send the turn to Memory Bank")
