"""Authentication for trusted Gateway internal callers."""

from __future__ import annotations

import os
import re
import secrets
from types import SimpleNamespace

from deerflow.runtime.user_context import DEFAULT_USER_ID

INTERNAL_AUTH_HEADER_NAME = "X-DeerFlow-Internal-Token"
INTERNAL_ARTIFACT_USER_HEADER_NAME = "X-DeerFlow-Artifact-User"
INTERNAL_AUTH_ENV_VAR = "DEER_FLOW_INTERNAL_AUTH_TOKEN"
_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _load_internal_auth_token() -> str:
    token = os.environ.get(INTERNAL_AUTH_ENV_VAR)
    if token:
        return token
    return secrets.token_urlsafe(32)


_INTERNAL_AUTH_TOKEN = _load_internal_auth_token()


def create_internal_auth_headers() -> dict[str, str]:
    """Return headers that authenticate trusted Gateway internal calls."""
    return {INTERNAL_AUTH_HEADER_NAME: _INTERNAL_AUTH_TOKEN}


def is_valid_internal_auth_token(token: str | None) -> bool:
    """Return True when *token* matches this Gateway worker's internal token."""
    return bool(token) and secrets.compare_digest(token, _INTERNAL_AUTH_TOKEN)


def is_valid_internal_user_id(user_id: str | None) -> bool:
    """Return True when an internal-request user bucket id is path safe."""
    return bool(user_id) and bool(_SAFE_USER_ID_RE.fullmatch(str(user_id)))


def get_internal_user(user_id: str | None = None):
    """Return the synthetic user used for trusted internal channel calls."""
    resolved_user_id = str(user_id) if is_valid_internal_user_id(user_id) else DEFAULT_USER_ID
    return SimpleNamespace(id=resolved_user_id, system_role="internal")
