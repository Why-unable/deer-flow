from __future__ import annotations

from typing import Any, Protocol

import httpx


class MMKBClient(Protocol):
    """Transport-neutral semantic interface for MMKB knowledge operations."""

    def list_documents(self, *, limit: int, offset: int = 0, collection_id: int | None = None) -> Any: ...

    def search(self, *, query: str, mode: str, limit: int) -> Any: ...

    def get_document(self, *, document_id: str) -> Any: ...

    def get_document_preview(self, *, document_id: str) -> Any: ...

    def get_document_chunks(self, *, document_id: str) -> Any: ...

    def get_document_assets(self, *, document_id: str) -> Any: ...

    def list_collections(self) -> Any: ...


class HTTPMMKBClient:
    """Synchronous HTTP transport for MMKB's authenticated JSON APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            with httpx.Client(timeout=self._timeout, trust_env=False) as client:
                response = client.get(f"{self._base_url}{path}", params=params, headers=self._headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            return {
                "error": "rag_http_error",
                "status_code": exc.response.status_code,
                "body": exc.response.text[:2000],
            }
        except Exception as exc:
            return {
                "error": "rag_request_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Compatibility entrypoint for callers that still use a raw HTTP path."""
        return self._get(path, params=params)

    def list_documents(self, *, limit: int, offset: int = 0, collection_id: int | None = None) -> Any:
        params: dict[str, Any] = {"status": "ready", "limit": limit, "offset": offset}
        if collection_id is not None:
            params["collection_id"] = collection_id
        return self._get("/api/documents", params=params)

    def search(self, *, query: str, mode: str, limit: int) -> Any:
        return self._get("/api/search", params={"q": query, "mode": mode, "limit": limit})

    def get_document(self, *, document_id: str) -> Any:
        return self._get(f"/api/documents/{document_id}")

    def get_document_preview(self, *, document_id: str) -> Any:
        return self._get(f"/api/documents/{document_id}/preview")

    def get_document_chunks(self, *, document_id: str) -> Any:
        return self._get(f"/api/documents/{document_id}/chunks")

    def get_document_assets(self, *, document_id: str) -> Any:
        return self._get(f"/api/documents/{document_id}/assets")

    def list_collections(self) -> Any:
        return self._get("/api/collections")
