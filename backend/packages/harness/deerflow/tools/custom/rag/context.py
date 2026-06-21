from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig

from deerflow.config import get_app_config

DEFAULT_BASE_URL = "http://host.docker.internal:8000"
DEFAULT_TIMEOUT = 30.0


def config_get(config: RunnableConfig | None, key: str, default: Any = None) -> Any:
    """Read one value from a dict-like or object-like RunnableConfig."""
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def tool_settings(tool_name: str) -> tuple[str, float]:
    """Resolve one MMKB tool's static transport settings."""
    config = get_app_config().get_tool_config(tool_name)
    extra = config.model_extra if config is not None else {}
    base_url = str(extra.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    timeout = float(extra.get("timeout") or DEFAULT_TIMEOUT)
    return base_url, timeout


@dataclass(frozen=True, slots=True)
class MMKBRuntimeContext:
    """Request-scoped MMKB identity and transport settings."""

    base_url: str
    timeout: float
    bearer_token: str
    public_base_url: str
    thread_id: str = ""
    run_id: str = ""

    @property
    def headers(self) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if self.bearer_token:
            headers["Authorization"] = self.bearer_token
        if self.public_base_url:
            headers["X-MMKB-Public-Base-URL"] = self.public_base_url
        return headers or None


def resolve_mmkb_runtime_context(config: RunnableConfig | None, *, tool_name: str) -> MMKBRuntimeContext:
    """Resolve runtime bearer/public URL plus static HTTP settings for a tool."""
    configurable = dict(config_get(config, "configurable") or {})
    context = dict(config_get(config, "context") or {})
    base_url, timeout = tool_settings(tool_name)
    bearer_token = str(configurable.get("mmkb_bearer_token") or context.get("mmkb_bearer_token") or "").strip()
    public_base_url = str(configurable.get("public_base_url") or context.get("public_base_url") or "").strip().rstrip("/")
    thread_id = str(configurable.get("thread_id") or context.get("thread_id") or "").strip()
    run_id = str(configurable.get("run_id") or context.get("run_id") or "").strip()
    return MMKBRuntimeContext(
        base_url=base_url,
        timeout=timeout,
        bearer_token=bearer_token,
        public_base_url=public_base_url or base_url,
        thread_id=thread_id,
        run_id=run_id,
    )
