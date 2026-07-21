from __future__ import annotations

import json

import pytest

from deerflow.tools.custom.rag import tools as rag_tools


DOC_ID = "859b3373-a899-43bc-8c3d-669daabf70b2"


class RecordingService:
    def __init__(self, calls: list[tuple]) -> None:
        self._calls = calls

    def list_documents(self, *, limit: int, offset: int = 0, collection_id: int | None = None):
        self._calls.append(("list_documents", limit, offset, collection_id))
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

    json.loads(rag_tools.rag_list_documents_tool.func(20, 100, 7, config={}))
    json.loads(rag_tools.rag_search_tool.func("nist", "hybrid", 5, config={}))
    json.loads(rag_tools.rag_get_document_tool.func(DOC_ID, config={}))
    json.loads(rag_tools.rag_get_document_preview_tool.func(DOC_ID, 12000, config={}))
    json.loads(rag_tools.rag_get_document_chunks_tool.func(DOC_ID, config={}))
    json.loads(rag_tools.rag_get_document_assets_tool.func(DOC_ID, 0, 8, config={}))
    detail = json.loads(rag_tools.rag_get_document_asset_tool.func(DOC_ID, 101, config={}))
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
        ("list_documents", 20, 100, 7),
        ("search", "nist", "hybrid", 5),
        ("get_document", DOC_ID),
        ("get_document_preview", DOC_ID),
        ("get_document_chunks", DOC_ID),
        ("get_document_assets", DOC_ID),
        ("get_document_assets", DOC_ID),
        ("list_collections",),
    ]
    assert detail["media_urls"]["image_url"] == "https://mmkb.example/image"


def test_public_tool_schemas_remain_stable():
    assert rag_tools.rag_list_documents_tool.args_schema.model_json_schema()["properties"].keys() == {
        "limit",
        "offset",
        "collection_id",
    }
    assert rag_tools.rag_search_tool.args_schema.model_json_schema()["properties"].keys() == {"query", "mode", "limit"}
    assert rag_tools.rag_get_document_preview_tool.args_schema.model_json_schema()["properties"].keys() == {
        "document_id",
        "max_chars",
        "start_char",
    }
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

    payload = json.loads(rag_tools.rag_get_document_preview_tool.func(DOC_ID, 12000, config={}))

    assert "md_images" not in payload["preview_text"]
    assert "/api/documents" not in payload["preview_text"]
    assert "IMG_META" not in payload["preview_text"]
    assert "alt=chart" in payload["preview_text"]
    assert "alt=protected" in payload["preview_text"]
    assert payload["preview_image_links_removed"] == 2
    assert payload["preview_image_metadata_removed"] == 1
    assert payload["preview_image_descriptions_preserved"] == 2
    assert "rag_get_document_asset" in payload["media_safety_note"]


def test_document_preview_preserves_mmkb_http_error(monkeypatch: pytest.MonkeyPatch):
    class ErrorPreviewService(RecordingService):
        def get_document_preview(self, *, document_id: str):
            self._calls.append(("get_document_preview", document_id))
            return {
                "error": "rag_http_error",
                "status_code": 404,
                "body": '{"error":"document not found"}',
            }

    def build_service(_tool_name: str, _config):
        return ErrorPreviewService([])

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", build_service)

    payload = json.loads(rag_tools.rag_get_document_preview_tool.func(DOC_ID, 12000, config={}))

    assert payload["error"] == "rag_http_error"
    assert payload["status_code"] == 404
    assert payload["document_id"] == DOC_ID
    assert payload["preview_available"] is False
    assert "total_chars" not in payload
    assert "rag_list_documents" in payload["next_step"]


def test_document_preview_preserves_image_description_without_paths(monkeypatch: pytest.MonkeyPatch):
    class DescriptivePreviewService(RecordingService):
        def get_document_preview(self, *, document_id: str):
            self._calls.append(("get_document_preview", document_id))
            return {
                "document_id": document_id,
                "preview_text": (
                    "before\n"
                    "![实验装置 md_images/secret.png](documents/doc-1/markdown/md_images/page_7_block0.png) "
                    '<!--IMG_META:{"page_id":7,"block_id":"block0","asset_type":"figure",'
                    '"image_path":"documents/doc-1/markdown/md_images/page_7_block0.png",'
                    '"image_url":"/api/documents/doc-1/media/markdown/md_images/page_7_block0.png",'
                    '"ocr":{"content":"Voltage profile uses /api/documents/doc-1/media/secret.png as an example",'
                    '"bbox":[1,2,3,4]},'
                    '"orphan_text":[{"content":"Panel A shows capacity retention."},'
                    '{"content":"local file /home/storage/page_7_block0.png"}]}-->\n'
                    "after"
                ),
            }

    def build_service(_tool_name: str, _config):
        return DescriptivePreviewService([])

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", build_service)

    payload = json.loads(rag_tools.rag_get_document_preview_tool.func(DOC_ID, 12000, config={}))
    preview = payload["preview_text"]

    assert "图片说明" in preview
    assert "page=7" in preview
    assert "block=block0" in preview
    assert "type=figure" in preview
    assert "Voltage profile uses" in preview
    assert "Panel A shows capacity retention." in preview
    assert "[路径已省略]" in preview
    assert "md_images" not in preview
    assert "/api/documents" not in preview
    assert "/home/storage" not in preview
    assert "image_path" not in preview
    assert "image_url" not in preview
    assert "IMG_META" not in preview
    assert payload["preview_image_links_removed"] == 1
    assert payload["preview_image_descriptions_preserved"] == 1


def test_document_preview_can_continue_from_sanitized_offset(monkeypatch: pytest.MonkeyPatch):
    class LongPreviewService(RecordingService):
        def get_document_preview(self, *, document_id: str):
            self._calls.append(("get_document_preview", document_id))
            return {
                "document_id": document_id,
                "preview_text": (
                    "a" * 1000
                    + "b" * 1000
                    + "![chart](md_images/page_7_block0.png) <!--IMG_META:{\"asset\": 1}-->\n"
                    + "c" * 1000
                ),
            }

    def build_service(_tool_name: str, _config):
        return LongPreviewService([])

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", build_service)

    first = json.loads(rag_tools.rag_get_document_preview_tool.func(DOC_ID, 1000, 0, config={}))
    second = json.loads(rag_tools.rag_get_document_preview_tool.func(DOC_ID, 1000, first["end_char"], config={}))

    assert first["preview_text"] == "a" * 1000
    assert first["start_char"] == 0
    assert first["end_char"] == 1000
    assert first["has_before"] is False
    assert first["has_after"] is True
    assert first["truncated"] is True

    assert second["preview_text"] == "b" * 1000
    assert second["start_char"] == 1000
    assert second["end_char"] == 2000
    assert second["has_before"] is True
    assert second["has_after"] is True
    assert second["offset_unit"] == "sanitized_preview_text_chars"


def test_document_tools_reject_non_uuid_document_id(monkeypatch: pytest.MonkeyPatch):
    def fail_build_service(_tool_name: str, _config):
        raise AssertionError("service should not be called for invalid document_id")

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", fail_build_service)

    tools = [
        lambda: rag_tools.rag_get_document_tool.func("science.adr2118.pdf", config={}),
        lambda: rag_tools.rag_get_document_preview_tool.func("science.adr2118.pdf", 12000, config={}),
        lambda: rag_tools.rag_get_document_chunks_tool.func("document_url", config={}),
        lambda: rag_tools.rag_get_document_assets_tool.func("/documents/not-a-uuid", 0, 5, config={}),
        lambda: rag_tools.rag_get_document_asset_tool.func("science.adr2118.pdf", 101, config={}),
    ]

    for call in tools:
        payload = json.loads(call())
        assert payload["error"].startswith("document_id must be a MMKB document UUID")
        assert "rag_search" in payload["next_step"]


def test_rag_tools_return_parameter_errors_instead_of_raising(monkeypatch: pytest.MonkeyPatch):
    def fail_build_service(_tool_name: str, _config):
        raise AssertionError("service should not be called for invalid parameters")

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", fail_build_service)

    assert json.loads(
        rag_tools.rag_list_documents_tool.func("many", 0, None, config={})
    ) == {"error": "limit must be an integer"}
    assert json.loads(
        rag_tools.rag_list_documents_tool.func(10, "later", None, config={})
    ) == {"error": "offset must be an integer"}
    assert json.loads(
        rag_tools.rag_search_tool.func("query", "wrong", 10, config={})
    ) == {"error": "mode must be one of: semantic, sparse, hybrid"}
    assert json.loads(
        rag_tools.rag_search_tool.func("query", "hybrid", "many", config={})
    ) == {"error": "limit must be an integer"}
    assert json.loads(
        rag_tools.rag_get_document_preview_tool.func(DOC_ID, "many", 0, config={})
    ) == {"error": "max_chars must be an integer"}
    assert json.loads(
        rag_tools.rag_get_document_preview_tool.func(DOC_ID, 12000, "later", config={})
    ) == {"error": "start_char must be an integer"}
    assert json.loads(
        rag_tools.rag_get_document_assets_tool.func(DOC_ID, "later", 5, config={})
    ) == {"error": "offset must be an integer"}
    assert json.loads(
        rag_tools.rag_get_document_asset_tool.func(DOC_ID, "asset", config={})
    ) == {"error": "asset_id must be an integer"}


def test_rag_tool_descriptions_distinguish_topical_search_from_inventory():
    list_description = " ".join(rag_tools.rag_list_documents_tool.description.split())
    search_description = " ".join(rag_tools.rag_search_tool.description.split())

    assert "document inventory and scope discovery" in list_description
    assert "Do not call it as a fixed prerequisite for an ordinary topical question" in list_description
    assert "default entry point for ordinary topical questions" in search_description
    assert "document inventory, scope discovery, or candidate-pool construction" in search_description
