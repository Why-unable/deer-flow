from __future__ import annotations

import logging

import pytest

from deerflow.utils.mmkb_resource_validation import log_mmkb_resource_validation, validate_mmkb_resource_urls

VALID_SIGNED_URL = (
    "http://localhost:8000/api/document-media/"
    ".eJyrVkrLz1eyUkpKLFKqBQAqYgWJ%3A1wXgTO%3AJFZy4Ixr9YrBXiUSAVb_JHplVN8Ueh9jsglBgaO3VM4"
)
TRUNCATED_SIGNED_URL = (
    "http://localhost:8000/api/document-media/"
    ".eJwlYzEKgkAQhT9ItFjUGawQahVBEJJXq00lKa9t1c2d3vfvtxL48h8Yk0I50t9p27uPZ2Vgmk5Z0o0E0KxRQrVxRqtFqN4lJcY9VvQ%3D"
)
PROTECTED_URL = (
    "http://localhost:8000/api/documents/"
    "00000000-0000-0000-0000-000000000001/media/markdown/md_images/page0001.jpg"
)
DOCUMENT_URL = "http://ocrdev.tentcoo.com/documents/859b3373-a899-43bc-8c3d-669daabf70b2"
API_DOCUMENT_DETAIL_URL = "http://ocrdev.tentcoo.com/api/documents/859b3373-a899-43bc-8c3d-669daabf70b2"


def test_validate_mmkb_resource_urls_accepts_structurally_complete_signed_url():
    stats = validate_mmkb_resource_urls({"image_url": VALID_SIGNED_URL})

    assert stats.resource_urls == 1
    assert stats.signed_media_urls == 1
    assert stats.structurally_valid_signed == 1
    assert stats.malformed_signed == 0
    assert stats.has_failures is False


def test_validate_mmkb_resource_urls_detects_truncated_and_protected_urls():
    stats = validate_mmkb_resource_urls(
        f"![bad]({TRUNCATED_SIGNED_URL})\n![protected]({PROTECTED_URL})",
    )

    assert stats.resource_urls == 2
    assert stats.signed_media_urls == 1
    assert stats.malformed_signed == 1
    assert stats.missing_token_segments == 1
    assert stats.protected_unsigned == 1
    assert stats.has_failures is True


def test_validate_mmkb_resource_urls_ignores_structured_md_asset_base_metadata():
    stats = validate_mmkb_resource_urls(
        {
            "md_asset_base": (
                "http://ocrdev.tentcoo.com/api/documents/"
                "859b3373-a899-43bc-8c3d-669daabf70b2/media/markdown/"
            ),
            "image_url": PROTECTED_URL,
        },
    )

    assert stats.protected_unsigned == 1
    assert stats.resource_urls == 1
    assert stats.has_failures is True


def test_validate_mmkb_resource_urls_tracks_document_page_origin_and_session_requirement():
    stats = validate_mmkb_resource_urls(f"{DOCUMENT_URL}、", expected_base_url="http://ocrdev.tentcoo.com")

    assert stats.resource_urls == 1
    assert stats.document_page_urls == 1
    assert stats.structurally_valid_document_pages == 1
    assert stats.document_origin_matches == 1
    assert stats.document_pages_require_session == 1
    assert stats.has_failures is False


def test_validate_mmkb_resource_urls_detects_document_page_origin_and_shape_failures():
    stats = validate_mmkb_resource_urls(
        "https://wrong.example/documents/859b3373-a899-43bc-8c3d-669daabf70b2 "
        "and /documents/not-a-uuid",
        expected_base_url="http://ocrdev.tentcoo.com",
    )

    assert stats.document_page_urls == 2
    assert stats.structurally_valid_document_pages == 1
    assert stats.malformed_document_pages == 1
    assert stats.unexpected_document_origins == 1
    assert stats.has_failures is True


def test_validate_mmkb_resource_urls_detects_api_document_detail_url():
    stats = validate_mmkb_resource_urls(
        f"[source]({API_DOCUMENT_DETAIL_URL})",
        expected_base_url="http://ocrdev.tentcoo.com",
    )

    assert stats.resource_urls == 1
    assert stats.document_page_urls == 0
    assert stats.api_document_detail_urls == 1
    assert stats.has_failures is True


def test_log_mmkb_resource_validation_omits_sensitive_url_content(caplog: pytest.LogCaptureFixture):
    stats = validate_mmkb_resource_urls(
        f"{TRUNCATED_SIGNED_URL} {DOCUMENT_URL}",
        expected_base_url="http://ocrdev.tentcoo.com",
    )

    with caplog.at_level(logging.INFO):
        log_mmkb_resource_validation(
            "mmkb_tool_resource_validation",
            stats,
            tool="rag_get_document_assets",
        )

    message = caplog.messages[-1]
    assert "mmkb_tool_resource_validation tool=rag_get_document_assets" in message
    assert "malformed_signed=1" in message
    assert "document-media" not in message
    assert "eJwlYzEK" not in message
    assert "ocrdev.tentcoo.com" not in message
    assert "859b3373" not in message
