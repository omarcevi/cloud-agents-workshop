"""Who the agent acts for, and how it proves its own identity to Cloud Run.

Two identities are in play:
- The employee (end user). Gemini Enterprise and the workshop scripts pass the
  employee's email as the ADK user id. The agent forwards it to the MCP servers in
  the X-User-Email header. The model never sees or sets that header.
- The agent itself. On Agent Runtime with Agent Identity, the agent has its own
  principal. It calls the IAM-protected Cloud Run MCP servers with an ID token
  minted for that principal.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import google.auth.exceptions
from google.auth.transport.requests import Request
from google.oauth2 import id_token as google_id_token

from app import config

_log = logging.getLogger(__name__)

# User ids that tools use when they run outside a real chat front end.
_FIXED_LOCAL_USER_IDS = {"cli-user", "eval-cli-user", "user", "test_user", "default-user-id"}


def employee_email(user_id: str | None) -> str:
    """Map an ADK user id to the employee email the HRIS knows."""
    if user_id and "@" in user_id:
        return user_id.strip().lower()
    if user_id and user_id not in _FIXED_LOCAL_USER_IDS:
        _log.info("user id %r is not an email; acting for the demo user", user_id)
    return config.DEMO_USER_EMAIL


_tokens: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()
_TOKEN_TTL_SECONDS = 45 * 60  # Google ID tokens live for 60 minutes


def _mint_id_token(audience: str) -> str:
    try:
        # On Agent Runtime this asks the metadata server for a token for the agent's
        # own identity. bind_id_token=False: Cloud Run rejects certificate-bound
        # tokens on *.run.app URLs.
        token: str = google_id_token.fetch_id_token(
            Request(), audience, bind_id_token=False
        )
        return token
    except google.auth.exceptions.DefaultCredentialsError:
        # Local development with user credentials: google-auth cannot mint ID tokens
        # for a user account, but gcloud can, and Cloud Run accepts them.
        result = subprocess.run(
            ["gcloud", "auth", "print-identity-token"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()


def id_token(audience: str) -> str:
    """Return a cached Google-signed ID token for a Cloud Run service URL."""
    with _lock:
        cached = _tokens.get(audience)
        if cached and cached[1] > time.monotonic():
            return cached[0]
    token = _mint_id_token(audience)
    with _lock:
        _tokens[audience] = (token, time.monotonic() + _TOKEN_TTL_SECONDS)
    return token
