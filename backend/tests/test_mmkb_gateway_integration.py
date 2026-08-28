"""Regression tests for the narrow MMKB-to-DeerFlow trust boundary."""

from types import SimpleNamespace

from starlette.datastructures import Headers
from starlette.requests import Request


def _request(*, headers: dict[str, str] | None = None, mmkb_proxy: bool = False):
    return SimpleNamespace(headers=Headers(headers or {}), state=SimpleNamespace(mmkb_proxy=mmkb_proxy))


def _mmkb_run_kwargs(*, internal_headers: dict[str, str]):
    return {
        "request": _request(headers=internal_headers),
        "body": {
            "config": {"configurable": {"mmkb_bearer_token": "Bearer workspace:key"}},
            "context": {"mmkb_workspace_id": "workspace-1", "mmkb_user_id": "user-1"},
        },
    }


def test_mmkb_run_create_requires_internal_auth_and_complete_identity():
    from app.gateway.authz import _is_mmkb_proxy_run_create
    from app.gateway.internal_auth import create_internal_auth_headers

    kwargs = _mmkb_run_kwargs(internal_headers=create_internal_auth_headers())
    assert _is_mmkb_proxy_run_create("runs", "create", kwargs) is True

    kwargs["request"] = _request(headers={})
    assert _is_mmkb_proxy_run_create("runs", "create", kwargs) is False

    kwargs = _mmkb_run_kwargs(internal_headers=create_internal_auth_headers())
    kwargs["body"]["context"].pop("mmkb_user_id")
    assert _is_mmkb_proxy_run_create("runs", "create", kwargs) is False
    assert _is_mmkb_proxy_run_create("threads", "create", kwargs) is False


def test_mmkb_proxy_user_is_stable_and_requires_admission_marker():
    from app.gateway.services import resolve_mmkb_proxy_user

    context = {"mmkb_workspace_id": "workspace/one", "mmkb_user_id": "user@example.com"}
    assert resolve_mmkb_proxy_user(_request(), context) is None

    first = resolve_mmkb_proxy_user(_request(mmkb_proxy=True), context)
    second = resolve_mmkb_proxy_user(_request(mmkb_proxy=True), context)
    assert first is not None
    assert first.id == second.id
    assert first.system_role == "mmkb_proxy"
    assert "/" not in first.id
    assert "@" not in first.id


def test_internal_artifact_owner_header_is_limited_to_artifact_routes():
    from app.gateway.auth_middleware import _get_internal_owner_user_id
    from app.gateway.internal_auth import INTERNAL_ARTIFACT_USER_HEADER_NAME

    def request(path: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": path,
                "raw_path": path.encode(),
                "root_path": "",
                "scheme": "http",
                "query_string": b"",
                "headers": [(INTERNAL_ARTIFACT_USER_HEADER_NAME.lower().encode(), b"mmkb-user-1")],
                "client": ("test", 1),
                "server": ("test", 80),
            }
        )

    assert _get_internal_owner_user_id(request("/api/threads/t1/artifacts/report.pdf")) == "mmkb-user-1"
    assert _get_internal_owner_user_id(request("/api/models")) is None


def test_runtime_model_is_request_scoped_and_secret_is_not_checkpointed():
    from app.gateway.services import (
        _app_config_with_mmkb_runtime_model,
        _context_without_mmkb_model_config,
        _mmkb_runtime_model_config,
    )
    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    base = AppConfig(
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        models=[
            ModelConfig(
                name="global",
                use="langchain_openai:ChatOpenAI",
                model="global",
                api_key="global-secret",
                base_url="https://global.example/v1",
            )
        ],
    )
    context = {
        "model_name": "tenant-model",
        "mmkb_model_config": {
            "name": "tenant-model",
            "model": "tenant-model",
            "protocol": "OPENAI_COMPATIBLE",
            "api_key": "tenant-secret",
            "base_url": "https://tenant.example/v1/",
            "context_window": 128000,
            "supports_reasoning_effort": True,
        },
    }
    runtime_model = _mmkb_runtime_model_config(context)
    scoped = _app_config_with_mmkb_runtime_model(base, runtime_model)
    sanitized = _context_without_mmkb_model_config(context)

    assert runtime_model is not None
    assert scoped is not base
    assert base.get_model_config("tenant-model") is None
    assert scoped.get_model_config("tenant-model").context_window == 128000
    assert scoped.get_model_config("tenant-model").supports_reasoning_effort is True
    assert "tenant-secret" not in repr(sanitized)
    assert "mmkb_model_config" not in sanitized


def test_mmkb_context_reaches_runtime_without_model_secret():
    from app.gateway.services import (
        _context_without_mmkb_model_config,
        build_run_config,
        merge_run_context_overrides,
    )

    incoming = {
        "public_base_url": "https://mmkb.example",
        "mmkb_workspace_id": "workspace-1",
        "mmkb_user_id": "user-1",
        "mmkb_tenant_id": "tenant-1",
        "mmkb_model_config": {"api_key": "tenant-secret"},
    }
    config = build_run_config("thread-1", None, None)

    merge_run_context_overrides(config, _context_without_mmkb_model_config(incoming))

    for section in ("configurable", "context"):
        assert config[section]["public_base_url"] == "https://mmkb.example"
        assert config[section]["mmkb_workspace_id"] == "workspace-1"
        assert config[section]["mmkb_user_id"] == "user-1"
        assert config[section]["mmkb_tenant_id"] == "tenant-1"
        assert "mmkb_model_config" not in config[section]
    assert "tenant-secret" not in repr(config)


def test_subagent_runtime_inheritance_is_allowlisted():
    from deerflow.tools.builtins.task_tool import _get_subagent_mmkb_runtime_values

    runtime = SimpleNamespace(
        config={
            "configurable": {
                "mmkb_bearer_token": "Bearer workspace:key",
                "mmkb_workspace_id": "workspace-1",
                "unrelated_secret": "must-not-copy",
            }
        },
        context={
            "public_base_url": "https://mmkb.example",
            "mmkb_user_id": "user-1",
            "mmkb_tenant_id": "tenant-1",
            "unrelated_context": "must-not-copy",
        },
    )

    configurable, context = _get_subagent_mmkb_runtime_values(runtime)

    assert configurable == {
        "mmkb_bearer_token": "Bearer workspace:key",
        "public_base_url": "https://mmkb.example",
    }
    assert context == {
        "public_base_url": "https://mmkb.example",
        "mmkb_workspace_id": "workspace-1",
        "mmkb_user_id": "user-1",
        "mmkb_tenant_id": "tenant-1",
    }
    assert "must-not-copy" not in repr((configurable, context))
