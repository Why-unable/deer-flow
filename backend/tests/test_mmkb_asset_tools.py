from __future__ import annotations

import json

import pytest

from deerflow.tools.custom.rag import assets
from deerflow.tools.custom.rag import tools as rag_tools

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"


def _full_asset_payload() -> dict:
    return {
        "document_id": DOCUMENT_ID,
        "count": 2,
        "items": [
            {
                "id": 101,
                "document_id": DOCUMENT_ID,
                "document_title": "Example.pdf",
                "document_url": "https://mmkb.example/documents/doc-1",
                "asset_type": "table",
                "page_id": 3,
                "block_id": "block-4",
                "image_url": "https://mmkb.example/api/document-media/full-signed-token",
                "video_url": "",
                "video_thumbnail_url": "",
                "caption_or_ocr": "word " * 300,
                "image_abs": "/srv/mmkb/private/image.png",
                "metadata_json": {"large": "metadata"},
            },
            {
                "id": 102,
                "document_id": DOCUMENT_ID,
                "document_title": "Example.pdf",
                "document_url": "https://mmkb.example/documents/doc-1",
                "asset_type": "image",
                "page_id": 4,
                "block_id": "block-5",
                "image_url": "https://mmkb.example/api/document-media/second-full-signed-token",
                "video_url": "",
                "video_thumbnail_url": "",
                "caption_or_ocr": "short caption",
                "image_abs": "/srv/mmkb/private/second.png",
                "metadata_json": {"other": "metadata"},
            },
        ],
    }


def test_compact_asset_catalog_keeps_complete_urls_and_drops_heavy_fields():
    result = assets.compact_asset_catalog(_full_asset_payload(), offset=0, limit=1)

    assert result["count"] == 2
    assert result["returned"] == 1
    assert result["has_more"] is True
    assert result["next_page"] == {"offset": 1, "limit": 1}
    assert result["items"][0]["image_url"] == "https://mmkb.example/api/document-media/full-signed-token"
    assert result["items"][0]["caption_truncated"] is True
    assert "image_abs" not in result["items"][0]
    assert "metadata_json" not in result["items"][0]
    assert "caption_or_ocr" not in result["items"][0]
    assert len(result["items"][0]["caption_preview"]) <= assets.ASSET_CATALOG_CAPTION_MAX_CHARS + 3


def test_get_document_assets_tool_returns_compact_catalog(monkeypatch: pytest.MonkeyPatch):
    class FakeService:
        def get_document_assets(self, *, document_id: str):
            assert document_id == DOCUMENT_ID
            return _full_asset_payload()

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", lambda *_args, **_kwargs: FakeService())

    result = json.loads(rag_tools.rag_get_document_assets_tool.func(DOCUMENT_ID, offset=1, limit=1, config={}))

    assert result["count"] == 2
    assert result["returned"] == 1
    assert result["has_more"] is False
    assert result["items"][0]["id"] == 102
    assert result["items"][0]["image_url"].endswith("/second-full-signed-token")
    assert "metadata_json" not in result["items"][0]


def test_get_document_asset_tool_returns_one_complete_asset(monkeypatch: pytest.MonkeyPatch):
    class FakeService:
        def get_document_assets(self, *, document_id: str):
            assert document_id == DOCUMENT_ID
            return _full_asset_payload()

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", lambda *_args, **_kwargs: FakeService())

    result = json.loads(rag_tools.rag_get_document_asset_tool.func(DOCUMENT_ID, 101, config={}))

    assert result["document_id"] == DOCUMENT_ID
    assert result["asset_id"] == 101
    assert result["media_urls"]["image_url"].endswith("/full-signed-token")
    assert result["item"]["caption_or_ocr"] == "word " * 300
    assert result["item"]["metadata_json"] == {"large": "metadata"}
    assert result["item"]["image_url"].endswith("/full-signed-token")


def test_get_document_asset_tool_reports_missing_asset(monkeypatch: pytest.MonkeyPatch):
    class FakeService:
        def get_document_assets(self, *, document_id: str):
            assert document_id == DOCUMENT_ID
            return _full_asset_payload()

    monkeypatch.setattr(rag_tools, "_build_mmkb_service", lambda *_args, **_kwargs: FakeService())

    result = json.loads(rag_tools.rag_get_document_asset_tool.func(DOCUMENT_ID, 999, config={}))

    assert result == {"error": "asset_not_found", "document_id": DOCUMENT_ID, "asset_id": 999}
