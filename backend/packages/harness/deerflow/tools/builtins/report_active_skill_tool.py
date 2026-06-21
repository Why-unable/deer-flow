from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_config


def _normalize_skill_names(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return {stripped} if stripped else set()
    if isinstance(value, Iterable):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def _enabled_skill_names() -> set[str]:
    from deerflow.skills.storage import get_or_new_skill_storage

    return {skill.name for skill in get_or_new_skill_storage().load_skills(enabled_only=True)}


def _allowed_skill_names(config: RunnableConfig | None) -> set[str]:
    runtime_config = config
    if runtime_config is None:
        try:
            runtime_config = get_config()
        except RuntimeError:
            runtime_config = None

    metadata = (runtime_config or {}).get("metadata") or {}
    if isinstance(metadata, dict) and "available_skills" in metadata:
        names = _normalize_skill_names(metadata.get("available_skills"))
        return names if names is not None else _enabled_skill_names()

    configurable = (runtime_config or {}).get("configurable") or {}
    if isinstance(configurable, dict) and "available_skills" in configurable:
        names = _normalize_skill_names(configurable.get("available_skills"))
        return names if names is not None else _enabled_skill_names()

    return _enabled_skill_names()


def _report_active_skill(skill_name: str, config: RunnableConfig | None = None) -> str:
    normalized = str(skill_name or "").strip()
    if not normalized:
        return "Error: skill_name is required."

    allowed = _allowed_skill_names(config)
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed)) if allowed else "(none)"
        return f"Error: skill_name must be one of the current agent skills: {allowed_text}."

    return json.dumps({"skill_name": normalized}, ensure_ascii=False)


@tool("report_active_skill")
def report_active_skill_tool(skill_name: str, config: RunnableConfig = None) -> str:
    """Report which configured skill is being used for the current turn.

    This tool records status only. It does not load, enable, disable, or execute
    a skill. Use it once before following a skill-specific workflow so clients
    can display the selected skill in progress output.
    """

    return _report_active_skill(skill_name, config=config)
