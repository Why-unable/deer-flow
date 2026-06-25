"""Structure-only validation for MMKB resource URLs.

DeerFlow does not have MMKB's signing secret, so it cannot verify a token's
cryptographic signature. It can still detect malformed, truncated, or
unsigned media URLs, and detect document-page origin mismatches, without
logging their sensitive contents.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

_SIGNED_MEDIA_RE = re.compile(r"/api/document-media/([^\s<>\"')\]?#]+)")
_PROTECTED_MEDIA_RE = re.compile(r"/api/documents/[^\s<>\"')\]?#]+/media/[^\s<>\"')\]?#]+")
_API_DOCUMENT_DETAIL_RE = re.compile(
    r"(?P<url>(?:https?://[^\s<>\"')\]?#/]+)?/api/documents/"
    r"(?P<document_id>[^\s<>\"')\]?#/.,;:!?，。、；：！？]+))"
    r"(?=$|[\s<>\"')\]?#,.;:!?，。、；：！？])"
)
_DOCUMENT_PAGE_RE = re.compile(
    r"(?<!/api)(?P<url>(?:https?://[^\s<>\"')\]?#/]+)?/documents/(?P<document_id>[^\s<>\"')\]?#/.,;:!?，。、；：！？]+))"
)
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
_URLSAFE_B64_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TIMESTAMP_RE = re.compile(r"^[A-Za-z0-9]+$")
_PROTECTED_MEDIA_METADATA_KEYS = {"md_asset_base"}


@dataclass
class MmkbResourceValidationStats:
    """Non-sensitive counters for one MMKB resource validation pass."""

    resource_urls: int = 0
    signed_media_urls: int = 0
    structurally_valid_signed: int = 0
    malformed_signed: int = 0
    protected_unsigned: int = 0
    missing_token_segments: int = 0
    invalid_payload_encoding: int = 0
    invalid_timestamp: int = 0
    invalid_signature: int = 0
    document_page_urls: int = 0
    structurally_valid_document_pages: int = 0
    malformed_document_pages: int = 0
    document_origin_matches: int = 0
    unexpected_document_origins: int = 0
    relative_document_pages: int = 0
    document_pages_require_session: int = 0
    api_document_detail_urls: int = 0

    @property
    def has_failures(self) -> bool:
        return (
            self.malformed_signed > 0
            or self.protected_unsigned > 0
            or self.malformed_document_pages > 0
            or self.unexpected_document_origins > 0
            or self.api_document_detail_urls > 0
        )

    def to_dict(self) -> dict[str, int | bool]:
        return {**asdict(self), "has_failures": self.has_failures}


def _is_valid_urlsafe_base64(value: str) -> bool:
    if not value or "=" in value or not _URLSAFE_B64_RE.fullmatch(value) or len(value) % 4 == 1:
        return False
    try:
        base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError:
        return False
    return True


def _validate_signed_token(token: str, stats: MmkbResourceValidationStats) -> None:
    decoded = unquote(token)
    parts = decoded.split(":")
    if len(parts) != 3 or any(not part for part in parts):
        stats.missing_token_segments += 1
        stats.malformed_signed += 1
        return

    payload, timestamp, signature = parts
    payload_value = payload[1:] if payload.startswith(".") else payload
    valid = True

    if not _is_valid_urlsafe_base64(payload_value):
        stats.invalid_payload_encoding += 1
        valid = False
    if not _TIMESTAMP_RE.fullmatch(timestamp):
        stats.invalid_timestamp += 1
        valid = False
    if not _is_valid_urlsafe_base64(signature):
        stats.invalid_signature += 1
        valid = False

    if valid:
        stats.structurally_valid_signed += 1
    else:
        stats.malformed_signed += 1


def _normalized_origin(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.scheme.lower(), parsed.netloc.lower()


def validate_mmkb_resource_urls(value: Any, *, expected_base_url: str = "") -> MmkbResourceValidationStats:
    """Inspect nested content for MMKB media and document-page URLs."""

    stats = MmkbResourceValidationStats()
    expected_origin = _normalized_origin(expected_base_url)

    def _inspect(item: Any, *, field_name: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                _inspect(child, field_name=str(key))
            return
        if isinstance(item, list):
            for child in item:
                _inspect(child)
            return
        if not isinstance(item, str):
            return

        signed_matches = list(_SIGNED_MEDIA_RE.finditer(item))
        protected_matches = [] if field_name in _PROTECTED_MEDIA_METADATA_KEYS else list(_PROTECTED_MEDIA_RE.finditer(item))
        api_document_detail_matches = list(_API_DOCUMENT_DETAIL_RE.finditer(item))
        document_page_matches = list(_DOCUMENT_PAGE_RE.finditer(item))
        stats.signed_media_urls += len(signed_matches)
        stats.protected_unsigned += len(protected_matches)
        stats.api_document_detail_urls += len(api_document_detail_matches)
        stats.document_page_urls += len(document_page_matches)
        stats.resource_urls += len(signed_matches) + len(protected_matches) + len(api_document_detail_matches) + len(document_page_matches)
        for match in signed_matches:
            _validate_signed_token(match.group(1), stats)
        for match in api_document_detail_matches:
            if not _UUID_RE.fullmatch(match.group("document_id")):
                stats.malformed_document_pages += 1
        for match in document_page_matches:
            if not _UUID_RE.fullmatch(match.group("document_id")):
                stats.malformed_document_pages += 1
                continue

            stats.structurally_valid_document_pages += 1
            stats.document_pages_require_session += 1
            actual_origin = _normalized_origin(match.group("url"))
            if actual_origin is None:
                stats.relative_document_pages += 1
            elif expected_origin is not None:
                if actual_origin == expected_origin:
                    stats.document_origin_matches += 1
                else:
                    stats.unexpected_document_origins += 1

    _inspect(value)
    return stats


def log_mmkb_resource_validation(event: str, stats: MmkbResourceValidationStats, **context: str) -> None:
    """Log aggregate validation results without URL, token, or document contents."""

    log = logger.warning if stats.has_failures else logger.info
    context_text = " ".join(f"{key}={value}" for key, value in context.items())
    log(
        "%s %s resource_urls=%d signed_media_urls=%d structurally_valid_signed=%d "
        "malformed_signed=%d protected_unsigned=%d missing_token_segments=%d "
        "invalid_payload_encoding=%d invalid_timestamp=%d invalid_signature=%d "
        "document_page_urls=%d structurally_valid_document_pages=%d malformed_document_pages=%d "
        "document_origin_matches=%d unexpected_document_origins=%d relative_document_pages=%d "
        "document_pages_require_session=%d api_document_detail_urls=%d",
        event,
        context_text,
        stats.resource_urls,
        stats.signed_media_urls,
        stats.structurally_valid_signed,
        stats.malformed_signed,
        stats.protected_unsigned,
        stats.missing_token_segments,
        stats.invalid_payload_encoding,
        stats.invalid_timestamp,
        stats.invalid_signature,
        stats.document_page_urls,
        stats.structurally_valid_document_pages,
        stats.malformed_document_pages,
        stats.document_origin_matches,
        stats.unexpected_document_origins,
        stats.relative_document_pages,
        stats.document_pages_require_session,
        stats.api_document_detail_urls,
    )
