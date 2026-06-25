from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig

from deerflow.tools.custom.rag.client import HTTPMMKBClient, MMKBClient
from deerflow.tools.custom.rag.context import config_get, resolve_mmkb_runtime_context
from deerflow.tools.custom.rag.mmkb_links import log_mmkb_link_processing, process_mmkb_response_links
from deerflow.utils.mmkb_resource_validation import log_mmkb_resource_validation, validate_mmkb_resource_urls


class RawMMKBClient(Protocol):
    """Compatibility interface for legacy path-based callers."""

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any: ...


class MMKBService:
    """Apply shared response policy over a transport-neutral MMKB client."""

    def __init__(
        self,
        *,
        tool_name: str,
        client: MMKBClient,
        public_base_url: str,
        public_base_url_source: str = "",
        public_base_url_fallback_used: bool = False,
        thread_id: str = "",
        run_id: str = "",
    ) -> None:
        self._tool_name = tool_name
        self._client = client
        self._public_base_url = public_base_url
        self._log_context = {
            key: value
            for key, value in {
                "tool": tool_name,
                "thread_id": thread_id,
                "run_id": run_id,
                "public_base_url_source": public_base_url_source,
                "public_base_url_fallback_used": str(public_base_url_fallback_used).lower()
                if public_base_url_source
                else "",
            }.items()
            if value
        }

    def _process(self, request: Callable[[], Any]) -> Any:
        data = request()
        processed, link_stats = process_mmkb_response_links(data, self._public_base_url)
        log_mmkb_link_processing(self._tool_name, link_stats)
        validation_stats = validate_mmkb_resource_urls(processed, expected_base_url=self._public_base_url)
        log_mmkb_resource_validation("mmkb_tool_resource_validation", validation_stats, **self._log_context)
        return processed

    def list_documents(self, *, limit: int) -> Any:
        return self._process(lambda: self._client.list_documents(limit=limit))

    def search(self, *, query: str, mode: str, limit: int) -> Any:
        return self._process(lambda: self._client.search(query=query, mode=mode, limit=limit))

    def get_document(self, *, document_id: str) -> Any:
        return self._process(lambda: _with_document_page_url(self._client.get_document(document_id=document_id), document_id))

    def get_document_preview(self, *, document_id: str) -> Any:
        return self._process(lambda: _with_document_page_url(self._client.get_document_preview(document_id=document_id), document_id))

    def get_document_chunks(self, *, document_id: str) -> Any:
        return self._process(lambda: _with_document_page_url(self._client.get_document_chunks(document_id=document_id), document_id))

    def get_document_assets(self, *, document_id: str) -> Any:
        return self._process(lambda: _with_document_page_url(self._client.get_document_assets(document_id=document_id), document_id))

    def list_collections(self) -> Any:
        return self._process(self._client.list_collections)


def _with_document_page_url(data: Any, document_id: str) -> Any:
    """Expose the human document page URL on MMKB API document-detail responses."""

    if not isinstance(data, dict) or data.get("document_url"):
        return data
    resolved_document_id = str(data.get("id") or document_id or "").strip()
    if not resolved_document_id:
        return data
    return {**data, "document_url": f"/documents/{resolved_document_id}"}


def build_mmkb_service(tool_name: str, config: RunnableConfig | None = None) -> MMKBService:
    """Build the current transport behind the stable semantic service contract."""
    runtime = resolve_mmkb_runtime_context(config, tool_name=tool_name)
    client = HTTPMMKBClient(
        base_url=runtime.base_url,
        timeout=runtime.timeout,
        headers=runtime.headers,
    )
    return MMKBService(
        tool_name=tool_name,
        client=client,
        public_base_url=runtime.public_base_url,
        public_base_url_source=runtime.public_base_url_source,
        public_base_url_fallback_used=runtime.public_base_url_fallback_used,
        thread_id=runtime.thread_id,
        run_id=runtime.run_id,
    )


def fetch_mmkb_response(
    tool_name: str,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    config: RunnableConfig | None = None,
    client: RawMMKBClient | None = None,
    public_base_url: str | None = None,
) -> Any:
    """Compatibility helper for legacy path-based MMKB callers."""
    if client is None:
        runtime = resolve_mmkb_runtime_context(config, tool_name=tool_name)
        client = HTTPMMKBClient(
            base_url=runtime.base_url,
            timeout=runtime.timeout,
            headers=runtime.headers,
        )
        resolved_public_base_url = runtime.public_base_url
        public_base_url_source = runtime.public_base_url_source
        public_base_url_fallback_used = runtime.public_base_url_fallback_used
    else:
        resolved_public_base_url = str(public_base_url or "").rstrip("/")
        public_base_url_source = "explicit" if resolved_public_base_url else ""
        public_base_url_fallback_used = False

    data = client.get(path, params=params)
    processed, link_stats = process_mmkb_response_links(data, resolved_public_base_url)
    log_mmkb_link_processing(tool_name, link_stats)
    validation_stats = validate_mmkb_resource_urls(processed, expected_base_url=resolved_public_base_url)
    configurable = dict(config_get(config, "configurable") or {})
    context = dict(config_get(config, "context") or {})
    log_context = {
        key: value
        for key, value in {
            "tool": tool_name,
            "thread_id": str(configurable.get("thread_id") or context.get("thread_id") or "").strip(),
            "run_id": str(configurable.get("run_id") or context.get("run_id") or "").strip(),
            "public_base_url_source": public_base_url_source,
            "public_base_url_fallback_used": str(public_base_url_fallback_used).lower() if public_base_url_source else "",
        }.items()
        if value
    }
    log_mmkb_resource_validation("mmkb_tool_resource_validation", validation_stats, **log_context)
    return processed
