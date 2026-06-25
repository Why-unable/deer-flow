from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

URL_KEY_SUFFIXES = ("_url", "_path", "_base")
PROTECTED_DOCUMENT_MEDIA_MARKER = "/api/documents/"
PROTECTED_DOCUMENT_MEDIA_SUFFIX = "/media/"
SIGNED_DOCUMENT_MEDIA_MARKER = "/api/document-media/"
PROTECTED_MEDIA_METADATA_KEYS = {"md_asset_base"}
_API_DOCUMENT_DETAIL_RE = re.compile(
    r"^(?P<prefix>(?:https?://[^/?#]+)?)/api/documents/"
    r"(?P<document_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})/?$"
)
_DOCUMENT_PAGE_RE = re.compile(
    r"^(?P<prefix>(?:https?://[^/?#]+)?)/documents/"
    r"(?P<document_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})/?$"
)


@dataclass
class MmkbLinkProcessingStats:
    """Non-sensitive counters describing one MMKB response link-processing pass."""

    url_fields: int = 0
    relative_fields: int = 0
    absolutized_fields: int = 0
    protected_media_remaining: int = 0
    signed_media_fields: int = 0

    @property
    def stage4_triggered(self) -> bool:
        return self.absolutized_fields > 0

    @property
    def stage4_trigger_ratio(self) -> float:
        return self.absolutized_fields / self.url_fields if self.url_fields else 0.0


def process_mmkb_response_links(value: Any, base_url: str) -> tuple[Any, MmkbLinkProcessingStats]:
    """Absolutize MMKB response links and return aggregate observability counters.

    This intentionally preserves the existing Stage 4 behavior: only relative
    string fields whose names end in ``_url``, ``_path``, or ``_base`` are
    prefixed with the public base URL. MMKB remains responsible for signing
    protected media URLs.
    """

    stats = MmkbLinkProcessingStats()
    normalized_base_url = str(base_url or "").rstrip("/")

    def _canonical_document_url(field_value: str) -> str:
        match = _API_DOCUMENT_DETAIL_RE.fullmatch(field_value) or _DOCUMENT_PAGE_RE.fullmatch(field_value)
        if match is None:
            return field_value
        prefix = normalized_base_url or match.group("prefix")
        return f"{prefix}/documents/{match.group('document_id')}"

    def _process(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: _process_field(key, field_value) for key, field_value in item.items()}
        if isinstance(item, list):
            return [_process(child) for child in item]
        return item

    def _process_field(key: str, field_value: Any) -> Any:
        if not (isinstance(field_value, str) and key.endswith(URL_KEY_SUFFIXES)):
            return _process(field_value)

        stats.url_fields += 1
        result = field_value
        was_relative = field_value.startswith("/")
        if key == "document_url":
            result = _canonical_document_url(result)
        if was_relative:
            stats.relative_fields += 1
            if normalized_base_url and result.startswith("/"):
                result = f"{normalized_base_url}{result}"
                stats.absolutized_fields += 1
            elif normalized_base_url and result.startswith(f"{normalized_base_url}/"):
                stats.absolutized_fields += 1
        elif key == "document_url":
            result = _canonical_document_url(result)

        if key not in PROTECTED_MEDIA_METADATA_KEYS and PROTECTED_DOCUMENT_MEDIA_MARKER in result and PROTECTED_DOCUMENT_MEDIA_SUFFIX in result:
            stats.protected_media_remaining += 1
        if SIGNED_DOCUMENT_MEDIA_MARKER in result:
            stats.signed_media_fields += 1
        return result

    return _process(value), stats


def log_mmkb_link_processing(tool_name: str, stats: MmkbLinkProcessingStats) -> None:
    """Emit one aggregation-friendly Stage 4 metric log without URL contents."""

    logger.info(
        "mmkb_link_stage4 tool=%s triggered=%s url_fields=%d relative_fields=%d "
        "absolutized_fields=%d trigger_ratio=%.4f protected_media_remaining=%d signed_media_fields=%d",
        tool_name,
        str(stats.stage4_triggered).lower(),
        stats.url_fields,
        stats.relative_fields,
        stats.absolutized_fields,
        stats.stage4_trigger_ratio,
        stats.protected_media_remaining,
        stats.signed_media_fields,
    )
