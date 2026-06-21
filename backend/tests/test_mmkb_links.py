from __future__ import annotations

import logging

import pytest
from test_mmkb_resource_validation import VALID_SIGNED_URL

from deerflow.tools.custom.rag.mmkb_links import log_mmkb_link_processing, process_mmkb_response_links
from deerflow.tools.custom.rag.service import MMKBService, fetch_mmkb_response


def test_process_mmkb_response_links_preserves_existing_absolutization_behavior():
    payload = {
        "document_url": "/documents/doc-1",
        "items": [
            {
                "image_url": "/api/document-media/signed-token",
                "image_abs": "/srv/mmkb/storage/image.png",
                "caption": "unchanged",
            }
        ],
    }

    processed, stats = process_mmkb_response_links(payload, "https://mmkb.example/")

    assert processed == {
        "document_url": "https://mmkb.example/documents/doc-1",
        "items": [
            {
                "image_url": "https://mmkb.example/api/document-media/signed-token",
                "image_abs": "/srv/mmkb/storage/image.png",
                "caption": "unchanged",
            }
        ],
    }
    assert stats.url_fields == 2
    assert stats.relative_fields == 2
    assert stats.absolutized_fields == 2
    assert stats.signed_media_fields == 1
    assert stats.protected_media_remaining == 0
    assert stats.stage4_trigger_ratio == 1.0


def test_process_mmkb_response_links_detects_media_that_mmkb_did_not_sign():
    payload = {
        "items": [
            {
                "image_url": "/api/documents/00000000-0000-0000-0000-000000000001/media/markdown/md_images/a.png",
            }
        ]
    }

    processed, stats = process_mmkb_response_links(payload, "https://mmkb.example")

    assert processed["items"][0]["image_url"].startswith("https://mmkb.example/api/documents/")
    assert stats.protected_media_remaining == 1
    assert stats.signed_media_fields == 0


def test_process_mmkb_response_links_does_not_change_absolute_or_non_url_fields():
    payload = {
        "document_url": "https://mmkb.example/documents/doc-1",
        "preview_text": "/documents/not-a-link-field",
        "nested": ["/documents/not-a-dict-field"],
    }

    processed, stats = process_mmkb_response_links(payload, "https://public.example")

    assert processed == payload
    assert stats.url_fields == 1
    assert stats.relative_fields == 0
    assert stats.absolutized_fields == 0
    assert stats.stage4_trigger_ratio == 0.0


def test_log_mmkb_link_processing_emits_aggregate_counters_without_urls(caplog: pytest.LogCaptureFixture):
    payload = {
        "document_url": "/documents/secret-document-id",
        "image_url": "/api/documents/secret-document-id/media/secret.png",
    }
    _processed, stats = process_mmkb_response_links(payload, "https://mmkb.example")

    with caplog.at_level(logging.INFO):
        log_mmkb_link_processing("rag_search", stats)

    message = caplog.messages[-1]
    assert "mmkb_link_stage4 tool=rag_search" in message
    assert "triggered=true" in message
    assert "url_fields=2" in message
    assert "absolutized_fields=2" in message
    assert "protected_media_remaining=1" in message
    assert "secret-document-id" not in message
    assert "mmkb.example" not in message


def test_fetch_mmkb_response_uses_central_link_processor_and_logs(caplog: pytest.LogCaptureFixture):
    class FakeClient:
        def get(self, path: str, params=None):
            assert path == "/api/search"
            assert params is None
            return {"document_url": "/documents/doc-1"}

    with caplog.at_level(logging.INFO):
        result = fetch_mmkb_response(
            "rag_search",
            "/api/search",
            client=FakeClient(),
            public_base_url="https://mmkb.example",
        )

    assert result == {"document_url": "https://mmkb.example/documents/doc-1"}
    assert any("mmkb_link_stage4 tool=rag_search" in message for message in caplog.messages)


def test_semantic_service_applies_same_link_policy(caplog: pytest.LogCaptureFixture):
    class FakeClient:
        def search(self, *, query: str, mode: str, limit: int):
            assert (query, mode, limit) == ("nist", "hybrid", 5)
            return {"document_url": "/documents/doc-1"}

    mmkb_service = MMKBService(
        tool_name="rag_search",
        client=FakeClient(),
        public_base_url="https://mmkb.example",
    )

    with caplog.at_level(logging.INFO):
        result = mmkb_service.search(query="nist", mode="hybrid", limit=5)

    assert result == {"document_url": "https://mmkb.example/documents/doc-1"}
    assert any("mmkb_link_stage4 tool=rag_search" in message for message in caplog.messages)
    assert any("mmkb_tool_resource_validation tool=rag_search" in message for message in caplog.messages)


def test_semantic_service_logs_document_page_origin_match(caplog: pytest.LogCaptureFixture):
    document_id = "859b3373-a899-43bc-8c3d-669daabf70b2"

    class FakeClient:
        def get_document(self, *, document_id: str):
            return {"document_url": f"/documents/{document_id}"}

    mmkb_service = MMKBService(
        tool_name="rag_get_document",
        client=FakeClient(),
        public_base_url="http://ocrdev.tentcoo.com",
    )

    with caplog.at_level(logging.INFO):
        mmkb_service.get_document(document_id=document_id)

    validation_log = next(message for message in caplog.messages if "mmkb_tool_resource_validation" in message)
    assert "document_page_urls=1" in validation_log
    assert "document_origin_matches=1" in validation_log
    assert "document_pages_require_session=1" in validation_log


def test_semantic_service_logs_mmkb_resource_structure_failures(caplog: pytest.LogCaptureFixture):
    class FakeClient:
        def get_document_assets(self, *, document_id: str):
            assert document_id == "doc-1"
            return {"image_url": VALID_SIGNED_URL.rsplit("%3A", 2)[0]}

    mmkb_service = MMKBService(
        tool_name="rag_get_document_assets",
        client=FakeClient(),
        public_base_url="https://mmkb.example",
        thread_id="thread-1",
        run_id="run-1",
    )

    with caplog.at_level(logging.INFO):
        mmkb_service.get_document_assets(document_id="doc-1")

    validation_log = next(message for message in caplog.messages if "mmkb_tool_resource_validation" in message)
    assert "tool=rag_get_document_assets" in validation_log
    assert "thread_id=thread-1" in validation_log
    assert "run_id=run-1" in validation_log
    assert "malformed_signed=1" in validation_log
