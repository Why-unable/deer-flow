"""Sanitize session-scoped artifact references before they enter memory."""

from __future__ import annotations

import copy
import posixpath
import re
from typing import Any

_OUTPUT_ARTIFACT_RE = re.compile(r"/mnt/user-data/outputs/[^\s`\"')\]}<>]+")
_SIGNED_ARTIFACT_RE = re.compile(r"(?:https?://[^\s`\"')\]}<>]+)?/api/(?:agent|deerflow)/artifacts/[^\s`\"')\]}<>]+")
_TRAILING_PUNCTUATION = ".,;:!?，。；、"
_SIGNED_LINK_PLACEHOLDER = "[历史生成文件下载链接已省略；需要时请重新生成或重新签名]"


def _split_trailing_punctuation(value: str) -> tuple[str, str]:
    """Split sentence punctuation accidentally captured with a path or URL."""
    trailing = ""
    while value and value[-1] in _TRAILING_PUNCTUATION:
        trailing = value[-1] + trailing
        value = value[:-1]
    return value, trailing


def sanitize_memory_artifact_text(text: str) -> str:
    """Replace session-scoped artifact links with non-clickable historical notes.

    DeerFlow artifacts live under a per-user, per-thread directory. Persisting
    raw ``/mnt/user-data/outputs/*`` paths or signed MMKB download URLs in
    long-term memory lets a future session re-sign the path against the wrong
    thread. Memory may remember that a historical file existed, but not a path
    that automatic link rewriters can treat as a current-session artifact.
    """

    def replace_output_path(match: re.Match[str]) -> str:
        raw, trailing = _split_trailing_punctuation(match.group(0))
        filename = posixpath.basename(raw.rstrip("/")) or "artifact"
        return f"[历史生成文件：{filename}，下载链接不可跨会话复用]{trailing}"

    def replace_signed_link(match: re.Match[str]) -> str:
        _raw, trailing = _split_trailing_punctuation(match.group(0))
        return f"{_SIGNED_LINK_PLACEHOLDER}{trailing}"

    text = _SIGNED_ARTIFACT_RE.sub(replace_signed_link, text)
    return _OUTPUT_ARTIFACT_RE.sub(replace_output_path, text)


def sanitize_memory_artifact_references(value: Any) -> Any:
    """Recursively sanitize artifact references in JSON-like memory data."""
    if isinstance(value, str):
        return sanitize_memory_artifact_text(value)
    if isinstance(value, list):
        return [sanitize_memory_artifact_references(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_memory_artifact_references(item) for key, item in value.items()}
    return copy.deepcopy(value)
