from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig

from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://host.docker.internal:8000"
DEFAULT_TIMEOUT = 30.0


def _safe_log_value(value: Any) -> str:
    return str(value or "").replace("\n", "").replace("\r", "").replace("\x00", "").strip()[:200] or "-"


def config_get(config: RunnableConfig | None, key: str, default: Any = None) -> Any:
    """Read one value from a dict-like or object-like RunnableConfig."""
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def tool_settings(tool_name: str) -> tuple[str, float, str]:
    """Resolve one MMKB tool's static transport settings."""
    config = get_app_config().get_tool_config(tool_name)
    extra = config.model_extra if config is not None else {}
    base_url = str(extra.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    public_base_url_fallback = str(extra.get("public_base_url_fallback") or "").strip().rstrip("/")
    timeout = float(extra.get("timeout") or DEFAULT_TIMEOUT)
    return base_url, timeout, public_base_url_fallback


@dataclass(frozen=True, slots=True)
class MMKBRuntimeContext:
    """Request-scoped MMKB identity and transport settings."""

    base_url: str
    timeout: float
    bearer_token: str
    public_base_url: str
    public_base_url_source: str = ""
    public_base_url_fallback_used: bool = False
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
    base_url, timeout, public_base_url_fallback = tool_settings(tool_name)
    bearer_token = str(configurable.get("mmkb_bearer_token") or context.get("mmkb_bearer_token") or "").strip()
    configurable_public_base_url = str(configurable.get("public_base_url") or "").strip().rstrip("/")
    context_public_base_url = str(context.get("public_base_url") or "").strip().rstrip("/")
    if configurable_public_base_url:
        public_base_url = configurable_public_base_url
        public_base_url_source = "configurable"
    elif context_public_base_url:
        public_base_url = context_public_base_url
        public_base_url_source = "context"
    elif public_base_url_fallback:
        public_base_url = public_base_url_fallback
        public_base_url_source = "fallback_public_base_url"
    else:
        public_base_url = base_url
        public_base_url_source = "fallback_base_url"
    thread_id = str(configurable.get("thread_id") or context.get("thread_id") or "").strip()
    run_id = str(configurable.get("run_id") or context.get("run_id") or "").strip()
    public_base_url_fallback_used = public_base_url_source.startswith("fallback_")
    logger.info(
        "mmkb_runtime_context tool=%s thread_id=%s run_id=%s base_url=%s public_base_url=%s "
        "public_base_url_source=%s fallback_used=%s bearer_present=%s "
        "configurable_public_base_url_present=%s context_public_base_url_present=%s",
        tool_name,
        _safe_log_value(thread_id),
        _safe_log_value(run_id),
        _safe_log_value(base_url),
        _safe_log_value(public_base_url),
        public_base_url_source,
        str(public_base_url_fallback_used).lower(),
        str(bool(bearer_token)).lower(),
        str(bool(configurable_public_base_url)).lower(),
        str(bool(context_public_base_url)).lower(),
    )
    return MMKBRuntimeContext(
        base_url=base_url,
        timeout=timeout,
        bearer_token=bearer_token,
        public_base_url=public_base_url,
        public_base_url_source=public_base_url_source,
        public_base_url_fallback_used=public_base_url_fallback_used,
        thread_id=thread_id,
        run_id=run_id,
    )
