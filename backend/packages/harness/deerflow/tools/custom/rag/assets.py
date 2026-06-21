from __future__ import annotations

from typing import Any

ASSET_CATALOG_CAPTION_MAX_CHARS = 160
ASSET_CATALOG_DEFAULT_LIMIT = 8
ASSET_CATALOG_MAX_LIMIT = 10


def compact_text(value: Any, *, max_chars: int) -> tuple[str, bool]:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "...", True


def compact_asset_catalog(data: Any, *, offset: int = 0, limit: int = ASSET_CATALOG_DEFAULT_LIMIT) -> Any:
    """Project a full MMKB asset response into a bounded discovery catalog."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return data

    source_items = data["items"]
    page_items = source_items[offset : offset + limit]
    compact_items: list[dict[str, Any]] = []
    for item in page_items:
        if not isinstance(item, dict):
            continue
        caption_preview, caption_truncated = compact_text(
            item.get("caption_or_ocr"),
            max_chars=ASSET_CATALOG_CAPTION_MAX_CHARS,
        )
        compact_items.append(
            {
                "id": item.get("id"),
                "document_id": item.get("document_id"),
                "document_title": item.get("document_title"),
                "document_url": item.get("document_url"),
                "asset_type": item.get("asset_type"),
                "page_id": item.get("page_id"),
                "block_id": item.get("block_id"),
                "image_url": item.get("image_url"),
                "video_url": item.get("video_url"),
                "video_thumbnail_url": item.get("video_thumbnail_url"),
                "caption_preview": caption_preview,
                "caption_truncated": caption_truncated,
            }
        )

    total_count = int(data.get("count") or len(source_items))
    result = {
        "document_id": data.get("document_id"),
        "count": total_count,
        "offset": offset,
        "limit": limit,
        "returned": len(compact_items),
        "has_more": offset + len(page_items) < len(source_items),
        "items": compact_items,
        "detail_tool": "Use rag_get_document_asset(document_id, asset_id) for one asset's full OCR/caption and metadata.",
    }
    if result["has_more"]:
        result["next_page"] = {"offset": offset + len(page_items), "limit": limit}
    return result


def select_document_asset(data: Any, asset_id: int) -> dict[str, Any]:
    """Select one asset and lead with a compact complete-media URL manifest."""
    if not isinstance(data, dict):
        return {"error": "invalid_asset_response"}
    if data.get("error"):
        return data
    items = data.get("items")
    if not isinstance(items, list):
        return {"error": "invalid_asset_response"}
    for item in items:
        if isinstance(item, dict) and str(item.get("id")) == str(asset_id):
            return {
                "document_id": data.get("document_id"),
                "asset_id": asset_id,
                "media_urls": {
                    "image_url": item.get("image_url"),
                    "video_url": item.get("video_url"),
                    "video_thumbnail_url": item.get("video_thumbnail_url"),
                },
                "item": item,
            }
    return {
        "error": "asset_not_found",
        "document_id": data.get("document_id"),
        "asset_id": asset_id,
    }
