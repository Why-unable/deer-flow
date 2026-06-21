from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from deerflow.tools.custom.rag import client as client_module
from deerflow.tools.custom.rag import context as context_module
from deerflow.tools.custom.rag import service


class _FakeAppConfig:
    def get_tool_config(self, _tool_name: str):
        return SimpleNamespace(model_extra={"base_url": "http://internal-mmkb:8000/", "timeout": 12})


def test_runtime_context_prefers_request_scoped_identity_and_public_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(context_module, "get_app_config", lambda: _FakeAppConfig())

    runtime = context_module.resolve_mmkb_runtime_context(
        {
            "configurable": {
                "mmkb_bearer_token": "Bearer configurable-token",
                "public_base_url": "https://public.example/",
                "thread_id": "thread-1",
            },
            "context": {
                "mmkb_bearer_token": "Bearer context-token",
                "public_base_url": "https://ignored.example",
                "run_id": "run-1",
            },
        },
        tool_name="rag_search",
    )

    assert runtime.base_url == "http://internal-mmkb:8000"
    assert runtime.timeout == 12
    assert runtime.public_base_url == "https://public.example"
    assert runtime.thread_id == "thread-1"
    assert runtime.run_id == "run-1"
    assert runtime.headers == {
        "Authorization": "Bearer configurable-token",
        "X-MMKB-Public-Base-URL": "https://public.example",
    }


def test_runtime_context_falls_back_to_static_base_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(context_module, "get_app_config", lambda: _FakeAppConfig())

    runtime = context_module.resolve_mmkb_runtime_context({}, tool_name="rag_search")

    assert runtime.public_base_url == "http://internal-mmkb:8000"
    assert runtime.headers == {"X-MMKB-Public-Base-URL": "http://internal-mmkb:8000"}


def test_http_client_preserves_http_error_contract(monkeypatch: pytest.MonkeyPatch):
    request = httpx.Request("GET", "http://internal-mmkb:8000/api/search")
    response = httpx.Response(403, request=request, text="forbidden")

    class FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    class FakeHTTPClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(client_module.httpx, "Client", lambda **_kwargs: FakeHTTPClient())

    result = client_module.HTTPMMKBClient(base_url="http://internal-mmkb:8000", timeout=12).get("/api/search")

    assert result == {"error": "rag_http_error", "status_code": 403, "body": "forbidden"}


@pytest.mark.parametrize(
    ("method_name", "kwargs", "expected_path", "expected_params"),
    [
        ("list_documents", {"limit": 20}, "/api/documents", {"status": "ready", "limit": 20}),
        ("search", {"query": "nist", "mode": "hybrid", "limit": 5}, "/api/search", {"q": "nist", "mode": "hybrid", "limit": 5}),
        ("get_document", {"document_id": "doc-1"}, "/api/documents/doc-1", None),
        ("get_document_preview", {"document_id": "doc-1"}, "/api/documents/doc-1/preview", None),
        ("get_document_chunks", {"document_id": "doc-1"}, "/api/documents/doc-1/chunks", None),
        ("get_document_assets", {"document_id": "doc-1"}, "/api/documents/doc-1/assets", None),
        ("list_collections", {}, "/api/collections", None),
    ],
)
def test_http_client_maps_semantic_operations_to_http_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    kwargs: dict,
    expected_path: str,
    expected_params: dict | None,
):
    captured: dict = {}

    def fake_get(self, path: str, params=None):
        captured["path"] = path
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(client_module.HTTPMMKBClient, "_get", fake_get)

    client = client_module.HTTPMMKBClient(base_url="http://internal-mmkb:8000", timeout=12)
    result = getattr(client, method_name)(**kwargs)

    assert result == {"ok": True}
    assert captured == {
        "path": expected_path,
        "params": expected_params,
    }


def test_build_mmkb_service_injects_runtime_headers(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    class FakeHTTPMMKBClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get(self, _path: str, params=None):
            return {}

    runtime = context_module.MMKBRuntimeContext(
        base_url="http://internal-mmkb:8000",
        timeout=12,
        bearer_token="Bearer workspace:secret",
        public_base_url="https://public.example",
    )
    monkeypatch.setattr(service, "resolve_mmkb_runtime_context", lambda *_args, **_kwargs: runtime)
    monkeypatch.setattr(service, "HTTPMMKBClient", FakeHTTPMMKBClient)

    mmkb_service = service.build_mmkb_service("rag_search", {})

    assert isinstance(mmkb_service, service.MMKBService)
    assert captured == {
        "base_url": "http://internal-mmkb:8000",
        "timeout": 12,
        "headers": {
            "Authorization": "Bearer workspace:secret",
            "X-MMKB-Public-Base-URL": "https://public.example",
        },
    }
