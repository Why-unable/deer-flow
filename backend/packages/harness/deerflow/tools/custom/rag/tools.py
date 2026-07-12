from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal
from uuid import UUID

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg

from deerflow.tools.custom.rag.assets import (
    ASSET_CATALOG_DEFAULT_LIMIT,
    ASSET_CATALOG_MAX_LIMIT,
)
from deerflow.tools.custom.rag.assets import (
    compact_asset_catalog as _compact_asset_catalog,
)
from deerflow.tools.custom.rag.assets import (
    select_document_asset as _select_document_asset,
)
from deerflow.tools.custom.rag.service import (
    build_mmkb_service as _build_mmkb_service,
)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _normalize_document_id(document_id: Any) -> tuple[str | None, dict[str, str] | None]:
    value = str(document_id or "").strip()
    if not value:
        return None, {"error": "document_id is required"}
    try:
        return str(UUID(value)), None
    except (TypeError, ValueError, AttributeError):
        return None, {
            "error": (
                "document_id must be a MMKB document UUID copied from "
                "rag_search or rag_list_documents; do not use a filename, "
                "title, path, or document_url field name"
            ),
            "received": value[:120],
            "next_step": (
                "Call rag_search for topical questions, or rag_list_documents "
                "for inventory, then pass the returned document_id value."
            ),
        }


def _normalize_int(
    value: Any,
    *,
    name: str,
    min_value: int,
    max_value: int | None = None,
) -> tuple[int | None, dict[str, str] | None]:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None, {"error": f"{name} must be an integer"}
    if normalized < min_value:
        return None, {"error": f"{name} must be >= {min_value}"}
    if max_value is not None and normalized > max_value:
        normalized = max_value
    return normalized, None


def _normalize_mode(mode: Any) -> tuple[str | None, dict[str, str] | None]:
    normalized = str(mode or "hybrid").strip().lower()
    if normalized not in {"semantic", "sparse", "hybrid"}:
        return None, {"error": "mode must be one of: semantic, sparse, hybrid"}
    return normalized, None


_PREVIEW_RAW_IMAGE_PATTERN = re.compile(
    r"!\[(?P<alt>[^\]\n]*)\]\("
    r"(?P<src>[^)\n]*(?:md_images/|/api/documents/[^)\n]*/media/|documents/[^)\n]*/markdown/)[^)\n]*)"
    r"\)(?:\s*<!--IMG_META:(?P<meta>.*?)-->)?",
    re.DOTALL,
)
_PREVIEW_IMAGE_META_PATTERN = re.compile(r"<!--IMG_META:.*?-->", re.DOTALL)
_PREVIEW_PATH_TOKEN_PATTERN = re.compile(
    r"https?://[^\s)\]]+|"
    r"(?<!\S)/(?:api/documents|home|mnt|var|tmp|documents)/[^\s)\]]+|"
    r"(?<!\S)(?:md_images|documents)/[^\s)\]]+|"
    r"(?<!\S)[^\s)\]]+\.(?:png|jpe?g|gif|webp|bmp|tiff?)(?!\S)",
    re.IGNORECASE,
)
_PREVIEW_IMAGE_PLACEHOLDER = (
    "[图片链接已省略：preview 不提供可展示图片 URL；"
    "需要展示图片请调用 rag_get_document_assets 或 rag_get_document_asset，"
    "并逐字复制返回的 image_url。]"
)
_PREVIEW_IMAGE_LINK_NOTE = "图片链接已省略，展示图片请调用 rag_get_document_asset。"
_PREVIEW_IMAGE_TEXT_MAX_CHARS = 600


def _compact_preview_fragment(value: Any, *, max_chars: int = _PREVIEW_IMAGE_TEXT_MAX_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    text = _PREVIEW_PATH_TOKEN_PATTERN.sub("[路径已省略]", text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _format_preview_image_description(alt_text: str, meta_json: str | None) -> tuple[str, bool]:
    """Return a path-free plain-text image note extracted from safe metadata."""
    parts: list[str] = []
    alt = _compact_preview_fragment(alt_text, max_chars=160)
    if alt:
        parts.append(f"alt={alt}")

    meta: dict[str, Any] = {}
    if meta_json:
        try:
            parsed = json.loads(meta_json)
        except (TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            meta = parsed

    for key, label in (("page_id", "page"), ("block_id", "block"), ("asset_type", "type")):
        value = _compact_preview_fragment(meta.get(key), max_chars=80)
        if value:
            parts.append(f"{label}={value}")

    ocr = meta.get("ocr")
    if isinstance(ocr, dict):
        ocr_text = _compact_preview_fragment(ocr.get("content"))
        if ocr_text:
            parts.append(f"OCR={ocr_text}")

    orphan_text = meta.get("orphan_text")
    if isinstance(orphan_text, list):
        orphan_parts = []
        for item in orphan_text:
            if isinstance(item, dict):
                content = item.get("content")
            else:
                content = item
            content_text = _compact_preview_fragment(content, max_chars=200)
            if content_text:
                orphan_parts.append(content_text)
        orphan_summary = _compact_preview_fragment("；".join(orphan_parts))
        if orphan_summary:
            parts.append(f"关联文字={orphan_summary}")

    if not parts:
        return _PREVIEW_IMAGE_PLACEHOLDER, False
    return f"[图片说明：{'；'.join(parts)}。{_PREVIEW_IMAGE_LINK_NOTE}]", True


def _sanitize_preview_text(text: str) -> tuple[str, int, int, int]:
    """Remove raw image paths while retaining safe plain-text image context."""
    image_links_removed = 0
    image_descriptions_preserved = 0

    def replace_raw_image(match: re.Match[str]) -> str:
        nonlocal image_descriptions_preserved, image_links_removed
        image_links_removed += 1
        replacement, preserved = _format_preview_image_description(match.group("alt"), match.group("meta"))
        if preserved:
            image_descriptions_preserved += 1
        return replacement

    sanitized = _PREVIEW_RAW_IMAGE_PATTERN.sub(replace_raw_image, text)
    sanitized, image_metadata_removed = _PREVIEW_IMAGE_META_PATTERN.subn("", sanitized)
    return sanitized, image_links_removed, image_metadata_removed, image_descriptions_preserved


# ═══════════════════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════════════════


@tool("rag_list_documents", parse_docstring=True)
def rag_list_documents_tool(
    limit: Annotated[int, "Maximum number of ready documents to return in this page, newest first (1-100)."] = 100,
    offset: Annotated[int, "Zero-based page offset. Use next_offset to continue when has_more is true."] = 0,
    collection_id: Annotated[int | None, "Optional MMKB collection ID used to restrict the listed documents."] = None,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """List indexed documents that are ready for local knowledge-base search.

    Use this for document inventory and scope discovery, such as listing ready
    documents or establishing a candidate pool for a multi-document review.
    Do not call it as a fixed prerequisite for an ordinary topical question;
    use `rag_search` first when the goal is to answer what local documents say.
    This tool intentionally returns only documents whose processing status is
    `ready`; failed, parsing, and indexing documents are excluded.

    Returns JSON with:
    - `items`: ready document rows ordered by `updated_at` descending.
    - `returned`: number of rows returned in this page.
    - `total_matched`: total ready documents matching the API-side filter.
    - `offset`, `limit`, `has_more`, `next_offset`: pagination fields.
    - `status_filter`: always `ready` for this tool.

    Each item includes the document `id` needed by the other RAG tools, `title`,
    `source_ext`, page/chunk progress fields, associated `collections`, and
    output paths such as `input_file_path`, `markdown_merged_path`, and
    `markdown_image_dir_path`.
    Relative URL/path fields are converted to absolute URLs when the caller
    provides a public base URL. These paths are MMKB API-side metadata, not
    sandbox-readable files. Do not pass them to `read_file`, `grep`, `bash`, or
    other sandbox tools; use the RAG tools below to read document content.
    This tool intentionally does not return document body text or previews.

    Typical inventory/review workflow:
    1. Use `rag_list_documents` to discover candidate document IDs.
    2. Use `rag_search` for semantic/keyword retrieval across all ready docs.
    3. Use `rag_get_document_preview`, `rag_get_document_chunks`, or
       `rag_get_document_assets` only when you need deeper context from one
       specific document.

    Args:
        limit: Maximum number of ready documents to return in this page, capped to 100.
        offset: Zero-based page offset. Use the returned `next_offset` to continue.
        collection_id: Optional MMKB collection ID used to restrict the listed documents.
    """
    limit, error = _normalize_int(limit, name="limit", min_value=1, max_value=100)
    if error:
        return _json(error)
    offset, error = _normalize_int(offset, name="offset", min_value=0)
    if error:
        return _json(error)
    normalized_collection_id = None
    if collection_id is not None:
        try:
            normalized_collection_id = int(collection_id)
        except (TypeError, ValueError):
            return _json({"error": "collection_id must be an integer"})
        if normalized_collection_id <= 0:
            return _json({"error": "collection_id must be positive"})
    data = _build_mmkb_service("rag_list_documents", config).list_documents(
        limit=limit,
        offset=offset,
        collection_id=normalized_collection_id,
    )
    return _json(data)


@tool("rag_search", parse_docstring=True)
def rag_search_tool(
    query: Annotated[str, "Search query in natural language."],
    mode: Annotated[Literal["semantic", "sparse", "hybrid"], "Retrieval mode: hybrid for most questions, semantic for meaning-only matches, sparse for exact terms."] = "hybrid",
    limit: Annotated[int, "Maximum number of direct vector/BM25 hits before linked images are added (1-50)."] = 10,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Search the local knowledge base's unified text-and-image index.

    Use this as the default entry point for ordinary topical questions about
    uploaded/local documents. It calls the local knowledge-base search API and
    leaves answer planning and synthesis to the agent. Use
    `rag_list_documents` instead when the task is document inventory, scope
    discovery, or candidate-pool construction for a multi-document review.

    Retrieval modes:
    - `hybrid`: default and usually best. Combines semantic vector retrieval and
      keyword/BM25 matching.
    - `semantic`: vector-only. Use when the user asks a conceptual question or
      may use words different from the document wording.
    - `sparse`: keyword/BM25 only. Use for exact phrases, names, IDs, section
      titles, abbreviations, or quoted text.

    Returns JSON with:
    - `query`: normalized query string.
    - `mode`: effective retrieval mode.
    - `chunks`: direct-hit text chunks only.
    - `assets`: deduplicated visual assets, including both direct-hit images
      and images linked from direct-hit chunks.

    Important `chunks` fields:
    - `document_id`, `document_title`, `document_url`: source document identity.
    - `obj_content`: retrieved chunk text to quote or summarize.
    - `page_start`, `page_end`: page range when available.
    - `score`, `distance`, `certainty`: retrieval metadata; higher `score`
      usually means stronger sparse/hybrid match, lower `distance` means closer
      vector match.

    Important `assets` fields:
    - `hit`: true when the image/visual asset itself was directly retrieved.
    - `from_chunk_ids`: chunk IDs that referenced this image. If `hit` is false
      but this list is non-empty, the image is contextual media associated with
      a matched text chunk.
    - `image_url`: signed public image URL when available. You may include it
      unchanged in an answer as Markdown, for example `![caption](image_url)`.
    - `caption_or_ocr`: OCR/caption text extracted from the image. Treat it as
      useful but potentially noisy.
    - `image_abs`: server-local file path. Do not show this to the user unless
      debugging; prefer `image_url`.
    - `page_id`, `block_id`, `asset_type`: source location/type metadata.

    Guidance:
    - Use `chunks` as primary textual evidence.
    - Use direct-hit `assets` when the user's question is about figures,
      screenshots, scanned pages, charts, or visual content.
    - Use linked assets (`from_chunk_ids`) to display relevant figures near a
      textual answer, especially when a chunk mentions a figure/image.
    - If results are thin, retry with a different mode or a more specific query.
    - This tool does not perform image VQA or final citation formatting by
      itself. For deep visual reasoning, inspect `caption_or_ocr`, `image_url`,
      and related document context with the other RAG tools.

    Args:
        query: Search query in natural language.
        mode: Retrieval mode. Use `hybrid` by default; use `semantic` for meaning-only search; use `sparse` for exact keyword/BM25 search.
        limit: Maximum number of direct retrieval hits to return before linked images are added. The API caps this to 50.
    """
    query = str(query or "").strip()
    if not query:
        return _json({"error": "query is required"})
    mode, error = _normalize_mode(mode)
    if error:
        return _json(error)
    limit, error = _normalize_int(limit, name="limit", min_value=1, max_value=50)
    if error:
        return _json(error)
    data = _build_mmkb_service("rag_search", config).search(query=query, mode=mode, limit=limit)
    return _json(data)


@tool("rag_get_document", parse_docstring=True)
def rag_get_document_tool(
    document_id: Annotated[str, "UUID of the local knowledge-base document."],
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Get one local knowledge-base document's metadata and generated paths.

    Use this after `rag_search` or `rag_list_documents` when you need the
    document-level record for a specific `document_id`.

    Returns JSON with fields such as:
    - `id`, `title`, `status`, `source_ext`
    - parsing/indexing progress: `total_pages`, `parsed_pages`,
      `index_total_chunks`, `indexed_chunks`, plus progress fields
    - output paths: `input_file_path`, `markdown_merged_path`,
      `markdown_image_dir_path`, `md_asset_base`
    - `error_message` if processing failed
    - timestamps: `created_at`, `updated_at`

    Relative URL/path fields are converted to absolute URLs when the caller
    provides a public base URL. Use this tool for orientation; use
    preview/chunks/assets tools for the actual document content. The returned
    paths are MMKB API metadata and are not mounted inside the DeerFlow sandbox;
    do not use `read_file`, `grep`, or `bash` on them.

    Difference from `rag_get_document_preview`: this returns metadata and
    generated path/URL fields only. It does not read the merged markdown body.

    Args:
        document_id: UUID of the local knowledge-base document.
    """
    document_id, error = _normalize_document_id(document_id)
    if error:
        return _json(error)
    data = _build_mmkb_service("rag_get_document", config).get_document(document_id=document_id)
    return _json(data)


@tool("rag_get_document_preview", parse_docstring=True)
def rag_get_document_preview_tool(
    document_id: Annotated[str, "UUID of the local knowledge-base document."],
    max_chars: Annotated[int, "Maximum preview characters to return (1000-50000)."] = 12000,
    start_char: Annotated[int, "Zero-based character offset in sanitized preview text."] = 0,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Get a truncated merged-markdown preview for one document.

    Use this when search results identify a relevant document and you need
    broader surrounding context than the retrieved chunks provide. This reads the
    document's merged markdown output and returns a bounded text window to avoid
    overloading the model context.

    Returns JSON with:
    - `document_id`
    - `preview_text`: merged markdown content window, possibly partial. Raw
      markdown image references such as `md_images/...`, protected
      `/api/documents/<id>/media/...`, and `IMG_META` comments are not copied
      into user-visible output. Safe image context from alt text and whitelisted
      `IMG_META` fields may be retained as path-free plain text.
    - `start_char`, `end_char`, `returned_chars`: returned window boundaries in
      sanitized preview text characters.
    - `has_before`, `has_after`: whether content exists before or after this
      returned window.
    - `truncated`: whether `preview_text` is not the full sanitized preview.
    - `total_chars`: sanitized preview length before windowing.
    - `preview_image_links_removed`: number of raw markdown image links omitted,
      present only when non-zero.
    - `preview_image_descriptions_preserved`: number of image links whose safe
      alt/OCR metadata was preserved as plain text, present only when non-zero.

    If you need concrete image URLs and OCR/caption metadata, call
    `rag_get_document_assets` or `rag_get_document_asset` for the same document
    and copy the returned `image_url` unchanged.

    If `truncated` is true, the preview is partial. If the returned preview is
    not enough to understand the document overview, such as an incomplete table
    of contents, section structure, or opening context, call this tool again
    with a larger `max_chars` or with `start_char=end_char` to read the next
    preview window without repeating earlier text. For reliable coverage of
    later sections, methods, experiments, results, limitations, or other
    complete-document claims, prefer `rag_get_document_chunks` or targeted
    `rag_search`. If you answer from a partial preview alone, state that the
    evidence is limited to the returned preview window.

    Args:
        document_id: UUID of the local knowledge-base document.
        max_chars: Maximum preview characters to return, clamped to 1000-50000.
            Increase this only when a broader overview window is needed; use
            chunks for reliable later-section or whole-document evidence.
        start_char: Zero-based character offset in sanitized preview text.
            Use the previous response's `end_char` to continue reading the next
            preview window without repeating earlier text.
    """
    document_id, error = _normalize_document_id(document_id)
    if error:
        return _json(error)

    max_chars, error = _normalize_int(max_chars, name="max_chars", min_value=1000, max_value=50000)
    if error:
        return _json(error)
    start_char, error = _normalize_int(start_char, name="start_char", min_value=0)
    if error:
        return _json(error)

    data = _build_mmkb_service("rag_get_document_preview", config).get_document_preview(document_id=document_id)
    if not isinstance(data, dict):
        return _json(data)

    text = str(data.get("preview_text") or "")
    text, image_links_removed, image_metadata_removed, image_descriptions_preserved = _sanitize_preview_text(text)
    data = {**data, "preview_text": text}
    if image_links_removed:
        data["preview_image_links_removed"] = image_links_removed
    if image_metadata_removed:
        data["preview_image_metadata_removed"] = image_metadata_removed
    if image_descriptions_preserved:
        data["preview_image_descriptions_preserved"] = image_descriptions_preserved
    if image_links_removed or image_metadata_removed:
        data["media_safety_note"] = (
            "preview_text omits raw markdown image links and raw IMG_META comments; "
            "safe image descriptions may be retained as path-free plain text. "
            "Use rag_get_document_assets/rag_get_document_asset for signed image_url."
        )
    total_chars = len(text)
    window_start = min(start_char, total_chars)
    window_end = min(window_start + max_chars, total_chars)
    window_text = text[window_start:window_end]
    data["preview_text"] = window_text
    data["start_char"] = window_start
    data["end_char"] = window_end
    data["returned_chars"] = len(window_text)
    data["total_chars"] = total_chars
    data["has_before"] = window_start > 0
    data["has_after"] = window_end < total_chars
    data["truncated"] = data["has_before"] or data["has_after"]
    data["offset_unit"] = "sanitized_preview_text_chars"
    return _json(data)


@tool("rag_get_document_chunks", parse_docstring=True)
def rag_get_document_chunks_tool(
    document_id: Annotated[str, "UUID of the local knowledge-base document."],
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """List all indexed text chunks for one document.

    Use this after `rag_search` when you need exact chunk text, page ranges, or
    neighboring chunks from a specific document. This is more precise than
    `rag_get_document_preview` and is useful for detailed evidence checking,
    quote extraction, or retrieval-quality debugging.

    Returns JSON with:
    - `document_id`
    - `count`
    - `items`: chunk rows ordered by index

    Each chunk item includes:
    - `id`: chunk row id, which can match asset `from_chunk_ids` from
      `rag_search`
    - `index`: chunk order in the document
    - `text`: chunk markdown/text content
    - `char_len`
    - `page_start`, `page_end`

    If the chunk text contains markdown image links, use
    `rag_get_document_assets` to resolve the extracted images and their public
    `image_url` values.

    Args:
        document_id: UUID of the local knowledge-base document.
    """
    document_id, error = _normalize_document_id(document_id)
    if error:
        return _json(error)
    data = _build_mmkb_service("rag_get_document_chunks", config).get_document_chunks(document_id=document_id)
    return _json(data)


@tool("rag_get_document_assets", parse_docstring=True)
def rag_get_document_assets_tool(
    document_id: Annotated[str, "UUID of the local knowledge-base document."],
    offset: Annotated[int, "Zero-based catalog offset. Use next_page.offset to continue."] = 0,
    limit: Annotated[int, "Maximum assets in this catalog page (1-10)."] = ASSET_CATALOG_DEFAULT_LIMIT,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """List a compact, paginated catalog of extracted visual assets for one document.

    Use this when the answer may depend on figures, screenshots, scanned pages,
    image-only documents, charts, tables captured as images, or OCR/caption
    text associated with visuals. This is a discovery tool: each page
    deliberately omits server-local paths, full metadata, and full OCR so its
    complete signed URLs remain visible in the model context.

    Returns JSON with:
    - `document_id`
    - `count`: total assets in the document.
    - `offset`, `limit`, `returned`, `has_more`, and optional `next_page`.
    - `items`: visual asset rows ordered by page/block/id

    Each compact asset item includes:
    - `id`, `asset_type`, `page_id`, `block_id`
    - `image_url`: signed public image URL when available. You may use it
      unchanged in Markdown, for example `![caption](image_url)`.
    - `video_url`, `video_thumbnail_url`: signed public video/media URLs.
    - `caption_preview`: whitespace-normalized OCR/caption preview.
    - `caption_truncated`: whether the preview omits additional text.

    Relative image URLs are converted to absolute URLs when the caller provides
    a public base URL. Use this tool together with `rag_search` or
    `rag_get_document_chunks` when you need to place relevant images near a
    text-based answer. Before making claims from a truncated caption or when you
    need one asset's complete fields, call `rag_get_document_asset` with the
    returned document and asset IDs.

    Args:
        document_id: UUID of the local knowledge-base document.
        offset: Zero-based catalog offset. Use the returned next_page offset to continue.
        limit: Maximum number of compact assets to return, capped to 10.
    """
    document_id, error = _normalize_document_id(document_id)
    if error:
        return _json(error)
    offset, error = _normalize_int(offset, name="offset", min_value=0)
    if error:
        return _json(error)
    limit, error = _normalize_int(limit, name="limit", min_value=1, max_value=ASSET_CATALOG_MAX_LIMIT)
    if error:
        return _json(error)
    data = _build_mmkb_service("rag_get_document_assets", config).get_document_assets(document_id=document_id)
    return _json(_compact_asset_catalog(data, offset=offset, limit=limit))


@tool("rag_get_document_asset", parse_docstring=True)
def rag_get_document_asset_tool(
    document_id: Annotated[str, "UUID of the local knowledge-base document."],
    asset_id: Annotated[int, "Numeric asset ID returned by rag_search or rag_get_document_assets."],
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Get the complete details for one visual asset in a document.

    Use this after `rag_get_document_assets` identifies a relevant asset. It
    returns a leading `media_urls` manifest followed by exactly one complete
    item with full `caption_or_ocr`, parser metadata, and server-local
    diagnostic fields. The manifest keeps complete signed URLs visible even
    when the large detail response is externalized.

    User-facing media links must be copied unchanged from `image_url`,
    `video_url`, or `video_thumbnail_url`. Never construct or repair a signed
    URL from another asset.

    Args:
        document_id: UUID of the document containing the asset.
        asset_id: Numeric asset ID from the compact catalog or search result.
    """
    document_id, error = _normalize_document_id(document_id)
    if error:
        return _json(error)
    normalized_asset_id, error = _normalize_int(asset_id, name="asset_id", min_value=1)
    if error:
        return _json(error)

    data = _build_mmkb_service("rag_get_document_asset", config).get_document_assets(document_id=document_id)
    return _json(_select_document_asset(data, normalized_asset_id))


@tool("rag_list_collections", parse_docstring=True)
def rag_list_collections_tool(
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """List document collections used to organize the local knowledge base.

    Use this for orientation when the user refers to folders, categories,
    projects, datasets, or a subset of documents. Collections can be nested up
    to two levels. This tool does not filter `rag_search` by collection; it is
    for discovering the taxonomy and deciding which documents to inspect.

    Returns JSON describing collection nodes, their document counts, and child
    collections. After identifying relevant categories, use
    `rag_list_documents` to list ready documents and `rag_search` to retrieve
    evidence across the indexed knowledge base.

    Args:
        config: Runtime configuration injected automatically.
    """
    data = _build_mmkb_service("rag_list_collections", config).list_collections()
    return _json(data)
