from __future__ import annotations

import json

import pytest

from deerflow.tools.custom.rag import tools as rag_tools


class RecordingService:
    def __init__(self, calls: list[tuple]) -> None:
        self._calls = calls

    def list_documents(self, *, limit: int):
        self._calls.append(("list_documents", limit))
        return {"items": []}

    def search(self, *, query: str, mode: str, limit: int):
        self._calls.append(("search", query, mode, limit))
        return {"chunks": [], "assets": []}

    def get_document(self, *, document_id: str):
        self._calls.append(("get_document", document_id))
        return {"id": document_id}

    def get_document_preview(self, *, document_id: str):
        self._calls.append(("get_document_preview", document_id))
        return {"document_id": document_id, "preview_text": "preview"}

    def get_document_chunks(self, *, document_id: str):
        self._calls.append(("get_document_chunks", document_id))
        return {"document_id": document_id, "items": []}

    def get_document_assets(self, *, document_id: str):
        self._calls.append(("get_document_assets", document_id))
        return {
            "document_id": document_id,
            "count": 1,
            "items": [{"id": 101, "document_id": document_id, "image_url": "https://mmkb.example/image"}],
        }

    def list_collections(self):
        self._calls.append(("list_collections",))
        return {"items": []}


def test_all_rag_tools_delegate_to_semantic_service(monkeypatch: pytest.MonkeyPatch):
    built_for: list[str] = []
    calls: list[tuple] = []

    def build_service(tool_name: str, _config):
        built_for.append(tool_name)
        return RecordingService(calls)

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", build_service)

    json.loads(rag_tools.rag_list_documents_tool.func(20, config={}))
    json.loads(rag_tools.rag_search_tool.func("nist", "hybrid", 5, config={}))
    json.loads(rag_tools.rag_get_document_tool.func("doc-1", config={}))
    json.loads(rag_tools.rag_get_document_preview_tool.func("doc-1", 12000, config={}))
    json.loads(rag_tools.rag_get_document_chunks_tool.func("doc-1", config={}))
    json.loads(rag_tools.rag_get_document_assets_tool.func("doc-1", 0, 8, config={}))
    detail = json.loads(rag_tools.rag_get_document_asset_tool.func("doc-1", 101, config={}))
    json.loads(rag_tools.rag_list_collections_tool.func(config={}))

    assert built_for == [
        "rag_list_documents",
        "rag_search",
        "rag_get_document",
        "rag_get_document_preview",
        "rag_get_document_chunks",
        "rag_get_document_assets",
        "rag_get_document_asset",
        "rag_list_collections",
    ]
    assert calls == [
        ("list_documents", 20),
        ("search", "nist", "hybrid", 5),
        ("get_document", "doc-1"),
        ("get_document_preview", "doc-1"),
        ("get_document_chunks", "doc-1"),
        ("get_document_assets", "doc-1"),
        ("get_document_assets", "doc-1"),
        ("list_collections",),
    ]
    assert detail["media_urls"]["image_url"] == "https://mmkb.example/image"


def test_public_tool_schemas_remain_stable():
    assert rag_tools.rag_search_tool.args_schema.model_json_schema()["properties"].keys() == {"query", "mode", "limit"}
    assert rag_tools.rag_get_document_assets_tool.args_schema.model_json_schema()["properties"].keys() == {
        "document_id",
        "offset",
        "limit",
    }
    assert rag_tools.rag_get_document_asset_tool.args_schema.model_json_schema()["required"] == ["document_id", "asset_id"]


def test_document_preview_omits_raw_markdown_image_links(monkeypatch: pytest.MonkeyPatch):
    class RawPreviewService(RecordingService):
        def get_document_preview(self, *, document_id: str):
            self._calls.append(("get_document_preview", document_id))
            return {
                "document_id": document_id,
                "preview_text": (
                    "before\n"
                    "![chart](md_images/page_7_block0.png) <!--IMG_META:{\"asset\": 1}-->\n"
                    "middle\n"
                    "![protected](/api/documents/doc-1/media/markdown/md_images/page_8.png)\n"
                    "standalone metadata <!--IMG_META:{\"asset\": 2}-->\n"
                    "after"
                ),
            }

    def build_service(_tool_name: str, _config):
        return RawPreviewService([])

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", build_service)

    payload = json.loads(rag_tools.rag_get_document_preview_tool.func("doc-1", 12000, config={}))

    assert "md_images" not in payload["preview_text"]
    assert "/api/documents" not in payload["preview_text"]
    assert "IMG_META" not in payload["preview_text"]
    assert payload["preview_image_links_removed"] == 2
    assert payload["preview_image_metadata_removed"] == 1
    assert "rag_get_document_asset" in payload["media_safety_note"]


def test_rag_tool_descriptions_distinguish_topical_search_from_inventory():
    list_description = " ".join(rag_tools.rag_list_documents_tool.description.split())
    search_description = " ".join(rag_tools.rag_search_tool.description.split())

    assert "document inventory and scope discovery" in list_description
    assert "Do not call it as a fixed prerequisite for an ordinary topical question" in list_description
    assert "default entry point for ordinary topical questions" in search_description
    assert "document inventory, scope discovery, or candidate-pool construction" in search_description
