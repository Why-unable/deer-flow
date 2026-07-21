"""Run lifecycle service layer.

Centralizes the business logic for creating runs, formatting SSE
frames, and consuming stream bridge events.  Router modules
(``thread_runs``, ``runs``) are thin HTTP handlers that delegate here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, Request
from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import convert_to_messages

from app.gateway.deps import get_run_context, get_run_manager, get_stream_bridge
from app.gateway.utils import sanitize_log_param
from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.model_config import ModelConfig
from deerflow.runtime import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    ConflictError,
    DisconnectMode,
    RunManager,
    RunRecord,
    RunStatus,
    StreamBridge,
    UnsupportedStrategyError,
    run_agent,
)
from deerflow.runtime.runs.naming import resolve_root_run_name
from deerflow.runtime.user_context import reset_current_user, set_current_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SSE formatting
# ---------------------------------------------------------------------------


def format_sse(event: str, data: Any, *, event_id: str | None = None) -> str:
    """Format a single SSE frame.

    Field order: ``event:`` -> ``data:`` -> ``id:`` (optional) -> blank line.
    This matches the LangGraph Platform wire format consumed by the
    ``useStream`` React hook and the Python ``langgraph-sdk`` SSE decoder.
    """
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Input / config helpers
# ---------------------------------------------------------------------------


def normalize_stream_modes(raw: list[str] | str | None) -> list[str]:
    """Normalize the stream_mode parameter to a list.

    Default matches what ``useStream`` expects: values + messages-tuple.
    """
    if raw is None:
        return ["values"]
    if isinstance(raw, str):
        return [raw]
    return raw if raw else ["values"]


def normalize_input(raw_input: dict[str, Any] | None) -> dict[str, Any]:
    """Convert LangGraph Platform input format to LangChain state dict.

    Delegates dict→message coercion to ``langchain_core.messages.utils.convert_to_messages``
    so that ``additional_kwargs`` (e.g. uploaded-file metadata — gh #3132), ``id``,
    ``name``, and non-human roles (ai/system/tool) survive unchanged.  An earlier
    hand-rolled version only forwarded ``content`` and collapsed every role to
    ``HumanMessage``, which silently stripped frontend-supplied attachments.

    Malformed message dicts (missing ``role``/``type``/``content``, unsupported
    role, etc.) raise ``HTTPException(400)`` with the offending index, instead
    of bubbling up as a 500.  The gateway is a system boundary, so per-entry
    validation errors are the right shape for clients to retry against.
    """
    if raw_input is None:
        return {}
    messages = raw_input.get("messages")
    if messages and isinstance(messages, list):
        converted: list[Any] = []
        for index, msg in enumerate(messages):
            if isinstance(msg, BaseMessage):
                converted.append(msg)
            elif isinstance(msg, dict):
                try:
                    converted.extend(convert_to_messages([msg]))
                except (ValueError, TypeError, NotImplementedError) as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid message at input.messages[{index}]: {exc}",
                    ) from exc
            else:
                converted.append(msg)
        return {**raw_input, "messages": converted}
    return raw_input


_DEFAULT_ASSISTANT_ID = "lead_agent"


# Whitelist of run-context keys that the langgraph-compat layer forwards from
# ``body.context`` into the run config. ``config["context"]`` exists in
# LangGraph >=0.6, but these values must be written to both ``configurable``
# (for legacy ``_get_runtime_config`` consumers) and ``context`` because
# LangGraph >=1.1.9 no longer makes ``ToolRuntime.context`` fall back to
# ``configurable`` for consumers like ``setup_agent``.
_CONTEXT_CONFIGURABLE_KEYS: frozenset[str] = frozenset(
    {
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
        "agent_name",
        "is_bootstrap",
        "public_base_url",
        "mmkb_workspace_id",
        "mmkb_user_id",
        "mmkb_tenant_id",
    }
)


def _optional_float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mmkb_runtime_model_config(context: Mapping[str, Any] | None) -> ModelConfig | None:
    """Convert MMKB tenant Chat LLM settings into a per-run model config."""
    if not isinstance(context, Mapping):
        return None
    raw = context.get("mmkb_model_config")
    if not isinstance(raw, Mapping):
        return None

    protocol = str(raw.get("protocol") or "openai_compatible").strip()
    if protocol != "openai_compatible":
        return None

    model_name = str(raw.get("model") or raw.get("model_name") or raw.get("name") or "").strip()
    name = str(raw.get("name") or model_name).strip()
    base_url = str(raw.get("base_url") or "").strip().rstrip("/")
    api_key = str(raw.get("api_key") or "").strip()
    if not name or not model_name or not base_url or not api_key:
        return None

    return ModelConfig(
        name=name[:128],
        display_name=str(raw.get("display_name") or f"{name} (MMKB tenant)").strip(),
        description="Runtime model forwarded by MMKB tenant settings",
        use="langchain_openai:ChatOpenAI",
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        request_timeout=_optional_float(raw.get("request_timeout"), 600.0),
        max_retries=_optional_int(raw.get("max_retries"), 2),
        max_tokens=_optional_int(raw.get("max_tokens"), 16000),
        temperature=_optional_float(raw.get("temperature"), 0.7),
        supports_thinking=bool(raw.get("supports_thinking") is True),
        supports_vision=bool(raw.get("supports_vision") is True),
    )


def _app_config_with_mmkb_runtime_model(
    base_config: AppConfig,
    runtime_model: ModelConfig | None,
) -> AppConfig:
    """Return an AppConfig copy with the MMKB tenant model available for this run."""
    if runtime_model is None:
        return base_config

    app_config = base_config.model_copy(deep=True)
    app_config.models = [runtime_model, *[model for model in app_config.models if model.name != runtime_model.name]]
    return app_config


def _context_without_mmkb_model_config(context: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(context, Mapping) or "mmkb_model_config" not in context:
        return context
    sanitized = dict(context)
    sanitized.pop("mmkb_model_config", None)
    return sanitized


def _safe_context_log_value(value: Any) -> str:
    """Return one single-line value for context diagnostics."""

    return sanitize_log_param(str(value or "").strip())[:200] or "-"


def merge_run_context_overrides(config: dict[str, Any], context: Mapping[str, Any] | None) -> None:
    """Merge whitelisted keys from ``body.context`` into both ``config['configurable']``
    and ``config['context']`` so they are visible to legacy configurable readers and
    to LangGraph ``ToolRuntime.context`` consumers (e.g. the ``setup_agent`` tool —
    see issue #2677)."""
    if not context:
        return
    configurable = config.setdefault("configurable", {})
    runtime_context = config.setdefault("context", {})
    for key in _CONTEXT_CONFIGURABLE_KEYS:
        if key in context:
            if isinstance(configurable, dict):
                configurable.setdefault(key, context[key])
            if isinstance(runtime_context, dict):
                runtime_context.setdefault(key, context[key])
    thread_id = ""
    if isinstance(configurable, dict):
        thread_id = str(configurable.get("thread_id") or "")
    logger.info(
        "deerflow_run_context_merge thread_id=%s incoming_public_base_url_present=%s "
        "incoming_public_base_url=%s configurable_public_base_url=%s context_public_base_url=%s "
        "mmkb_workspace_present=%s mmkb_user_present=%s",
        sanitize_log_param(thread_id) or "-",
        str(bool(context.get("public_base_url"))).lower(),
        _safe_context_log_value(context.get("public_base_url")),
        _safe_context_log_value(configurable.get("public_base_url") if isinstance(configurable, dict) else ""),
        _safe_context_log_value(runtime_context.get("public_base_url") if isinstance(runtime_context, dict) else ""),
        str(bool(context.get("mmkb_workspace_id"))).lower(),
        str(bool(context.get("mmkb_user_id"))).lower(),
    )


_SAFE_USER_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_user_id_part(value: Any) -> str:
    return _SAFE_USER_ID_RE.sub("-", str(value or "").strip()).strip("-")


def resolve_mmkb_proxy_user(request: Request, context: Mapping[str, Any] | None) -> SimpleNamespace | None:
    """Resolve the MMKB workspace/user pair into a DeerFlow runtime user.

    MMKB identity is trusted only after authz marks the request as an internal
    MMKB proxy run. The resulting id is path-safe for DeerFlow user buckets.
    """

    if not getattr(request.state, "mmkb_proxy", False) or not isinstance(context, Mapping):
        return None

    workspace_id = _safe_user_id_part(context.get("mmkb_workspace_id"))
    user_id = _safe_user_id_part(context.get("mmkb_user_id"))
    if not workspace_id or not user_id:
        return None

    return SimpleNamespace(id=f"mmkb-{workspace_id}-{user_id}", system_role="mmkb_proxy")


def inject_authenticated_user_context(config: dict[str, Any], request: Request) -> None:
    """Stamp the authenticated user into the run context for background tools.

    Tool execution may happen after the request handler has returned, so tools
    that persist user-scoped files should not rely only on ambient ContextVars.
    The value comes from server-side auth state, never from client context.
    """

    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        return

    runtime_context = config.setdefault("context", {})
    if isinstance(runtime_context, dict):
        runtime_context["user_id"] = str(user_id)


def resolve_agent_factory(assistant_id: str | None):
    """Resolve the agent factory callable from config.

    Custom agents are implemented as ``lead_agent`` + an ``agent_name``
    injected into ``configurable`` or ``context`` — see
    :func:`build_run_config`.  All ``assistant_id`` values therefore map to the
    same factory; the routing happens inside ``make_lead_agent`` when it reads
    ``cfg["agent_name"]``.
    """
    from deerflow.agents.lead_agent.agent import make_lead_agent

    return make_lead_agent


def build_run_config(
    thread_id: str,
    request_config: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    *,
    assistant_id: str | None = None,
) -> dict[str, Any]:
    """Build a RunnableConfig dict for the agent.

    When *assistant_id* refers to a custom agent (anything other than
    ``"lead_agent"`` / ``None``), the name is forwarded as ``agent_name`` in
    whichever runtime options container is active: ``context`` for
    LangGraph >= 0.6.0 requests, otherwise ``configurable``.
    ``make_lead_agent`` reads this key to load the matching
    ``agents/<name>/SOUL.md`` and per-agent config — without it the agent
    silently runs as the default lead agent.

    This mirrors the channel manager's ``_resolve_run_params`` logic so that
    the LangGraph Platform-compatible HTTP API and the IM channel path behave
    identically.
    """
    config: dict[str, Any] = {"recursion_limit": 100}
    if request_config:
        # LangGraph >= 0.6.0 introduced ``context`` as the preferred way to
        # pass thread-level data and rejects requests that include both
        # ``configurable`` and ``context``.  If the caller already sends
        # ``context``, honour it and skip our own ``configurable`` dict.
        if "context" in request_config:
            if "configurable" in request_config:
                logger.warning(
                    "build_run_config: client sent both 'context' and 'configurable'; preferring 'context' (LangGraph >= 0.6.0). thread_id=%s, caller_configurable keys=%s",
                    thread_id,
                    list(request_config.get("configurable", {}).keys()),
                )
            context_value = request_config["context"]
            if context_value is None:
                context = {}
            elif isinstance(context_value, Mapping):
                context = dict(context_value)
            else:
                raise ValueError("request config 'context' must be a mapping or null.")
            config["context"] = context
        else:
            configurable = {"thread_id": thread_id}
            configurable.update(request_config.get("configurable", {}))
            config["configurable"] = configurable
        for k, v in request_config.items():
            if k not in ("configurable", "context"):
                config[k] = v
    else:
        config["configurable"] = {"thread_id": thread_id}

    # Inject custom agent name when the caller specified a non-default assistant.
    # Honour an explicit agent_name in the active runtime options container.
    if assistant_id and assistant_id != _DEFAULT_ASSISTANT_ID:
        normalized = assistant_id.strip().lower().replace("_", "-")
        if not normalized or not re.fullmatch(r"[a-z0-9-]+", normalized):
            raise ValueError(f"Invalid assistant_id {assistant_id!r}: must contain only letters, digits, and hyphens after normalization.")
        if "configurable" in config:
            target = config["configurable"]
        elif "context" in config:
            target = config["context"]
        else:
            target = config.setdefault("configurable", {})
        if target is not None and "agent_name" not in target:
            target["agent_name"] = normalized
        config.setdefault("run_name", resolve_root_run_name(config, normalized))
    if metadata:
        config.setdefault("metadata", {}).update(metadata)
    return config


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


async def start_run(
    body: Any,
    thread_id: str,
    request: Request,
) -> RunRecord:
    """Create a RunRecord and launch the background agent task.

    Parameters
    ----------
    body : RunCreateRequest
        The validated request body (typed as Any to avoid circular import
        with the router module that defines the Pydantic model).
    thread_id : str
        Target thread.
    request : Request
        FastAPI request — used to retrieve singletons from ``app.state``.
    """
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    run_ctx = get_run_context(request)

    disconnect = DisconnectMode.cancel if body.on_disconnect == "cancel" else DisconnectMode.continue_

    body_context = getattr(body, "context", None) or {}
    if not isinstance(body_context, Mapping):
        body_context = {}
    mmkb_runtime_model = _mmkb_runtime_model_config(body_context)
    app_config = _app_config_with_mmkb_runtime_model(get_app_config(), mmkb_runtime_model)
    model_name = body_context.get("model_name")

    # Coerce non-string model_name values to str before truncation.
    if model_name is not None and not isinstance(model_name, str):
        model_name = str(model_name)
    if not model_name and mmkb_runtime_model is not None:
        model_name = mmkb_runtime_model.name

    # Validate model against the allowlist when a model_name is provided.
    if model_name:
        resolved = app_config.get_model_config(model_name)
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"Model {model_name!r} is not in the configured model allowlist",
            )

    mmkb_user = resolve_mmkb_proxy_user(request, body_context)
    mmkb_user_token = None
    if mmkb_user is not None:
        request.state.user = mmkb_user
        mmkb_user_token = set_current_user(mmkb_user)

    try:
        try:
            record = await run_mgr.create_or_reject(
                thread_id,
                body.assistant_id,
                on_disconnect=disconnect,
                metadata=body.metadata or {},
                kwargs={"input": body.input, "config": body.config},
                multitask_strategy=body.multitask_strategy,
                model_name=model_name,
            )
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except UnsupportedStrategyError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc

        # Upsert thread metadata so the thread appears in /threads/search,
        # even for threads that were never explicitly created via POST /threads
        # (e.g. stateless runs).
        try:
            existing = await run_ctx.thread_store.get(thread_id)
            if existing is None:
                await run_ctx.thread_store.create(
                    thread_id,
                    assistant_id=body.assistant_id,
                    metadata=body.metadata,
                )
            else:
                await run_ctx.thread_store.update_status(thread_id, "running")
        except Exception:
            logger.warning("Failed to upsert thread_meta for %s (non-fatal)", sanitize_log_param(thread_id))

        agent_factory = resolve_agent_factory(body.assistant_id)
        graph_input = normalize_input(body.input)
        config = build_run_config(thread_id, body.config, body.metadata, assistant_id=body.assistant_id)

        # Merge DeerFlow-specific context overrides into both ``configurable`` and ``context``.
        # The ``context`` field is a custom extension for the langgraph-compat layer
        # that carries agent configuration (model_name, thinking_enabled, etc.).
        # Only agent-relevant keys are forwarded; unknown keys (e.g. thread_id) are ignored.
        merge_run_context_overrides(config, _context_without_mmkb_model_config(body_context))
        inject_authenticated_user_context(config, request)

        stream_modes = normalize_stream_modes(body.stream_mode)
        effective_run_ctx = replace(run_ctx, app_config=app_config) if mmkb_runtime_model is not None else run_ctx

        task = asyncio.create_task(
            run_agent(
                bridge,
                run_mgr,
                record,
                ctx=effective_run_ctx,
                agent_factory=agent_factory,
                graph_input=graph_input,
                config=config,
                stream_modes=stream_modes,
                stream_subgraphs=body.stream_subgraphs,
                interrupt_before=body.interrupt_before,
                interrupt_after=body.interrupt_after,
            )
        )
        record.task = task

        # Title sync is handled by worker.py's finally block which reads the
        # title from the checkpoint and calls thread_store.update_display_name
        # after the run completes.

        return record
    finally:
        if mmkb_user_token is not None:
            reset_current_user(mmkb_user_token)


async def sse_consumer(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
):
    """Async generator that yields SSE frames from the bridge.

    The ``finally`` block implements ``on_disconnect`` semantics:
    - ``cancel``: abort the background task on client disconnect.
    - ``continue``: let the task run; events are discarded.
    """
    last_event_id = request.headers.get("Last-Event-ID")
    try:
        async for entry in bridge.subscribe(record.run_id, last_event_id=last_event_id):
            if await request.is_disconnected():
                break

            if entry is HEARTBEAT_SENTINEL:
                yield ": heartbeat\n\n"
                continue

            if entry is END_SENTINEL:
                yield format_sse("end", None, event_id=entry.id or None)
                return

            yield format_sse(entry.event, entry.data, event_id=entry.id or None)

    finally:
        if record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)


async def wait_for_run_completion(
    bridge: StreamBridge,
    record: RunRecord,
    request: Request,
    run_mgr: RunManager,
) -> bool:
    """Block until the run publishes ``END_SENTINEL``, honouring on_disconnect.

    The non-streaming ``/wait`` endpoints used to ``await record.task``
    directly with no disconnect handling.  When the client (or an
    intermediate HTTP proxy) timed out during a long tool call such as
    ``pip install``, the handler would swallow ``CancelledError`` and
    serialize whatever checkpoint happened to exist — masking a half-finished
    run as a normal completion (issue #3265).

    This helper consumes the same bridge that ``sse_consumer`` does so the
    wait path shares its disconnect semantics: each wake-up polls
    ``request.is_disconnected()``; on a real disconnect it cancels the
    background run when ``record.on_disconnect`` is ``cancel``.  The bridge's
    heartbeat sentinels guarantee at least one wake-up per
    ``heartbeat_interval`` even when the agent emits no events for a while.

    Returns:
        ``True`` when ``END_SENTINEL`` was observed (run reached a terminal
        state), ``False`` when the loop exited because the client
        disconnected.  Callers must skip checkpoint serialization on
        ``False`` so a partial checkpoint is not returned as a normal
        response.
    """
    completed = False
    try:
        async for entry in bridge.subscribe(record.run_id):
            # END_SENTINEL means the run reached a terminal state; honour it
            # even if the client just disconnected so the caller still serializes
            # the real final checkpoint.
            if entry is END_SENTINEL:
                completed = True
                return True
            if await request.is_disconnected():
                break
            # Heartbeats and regular events: keep waiting for END_SENTINEL.
        return completed
    finally:
        if not completed and record.status in (RunStatus.pending, RunStatus.running):
            if record.on_disconnect == DisconnectMode.cancel:
                await run_mgr.cancel(record.run_id)
