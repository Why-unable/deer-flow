from __future__ import annotations

import json
from typing import Annotated, Any, Literal

import httpx
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg

from deerflow.config import get_app_config

DEFAULT_BASE_URL = "http://host.docker.internal:8000"
DEFAULT_TIMEOUT = 30.0


def _tool_settings(tool_name: str) -> tuple[str, float]:
    config = get_app_config().get_tool_config(tool_name)
    extra = config.model_extra if config is not None else {}
    base_url = str(extra.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    timeout = float(extra.get("timeout") or DEFAULT_TIMEOUT)
    return base_url, timeout


def _resolve_public_base_url(config: RunnableConfig | None, *, tool_name: str) -> str:
    """Return the public-facing base URL for absolutizing user-visible links.

    Precedence:
    1. ``public_base_url`` from the runtime configurable (set by the caller, e.g.
       mmkb's chat_completion proxy).
    2. The tool's static ``base_url`` config (typically an internal host like
       ``host.docker.internal`` — useful as a fallback when the caller does not
       pass a public URL).
    """
    configurable = dict(_config_get(config, "configurable") or {})
    context = dict(_config_get(config, "context") or {})
    public_base_url = str(configurable.get("public_base_url") or context.get("public_base_url") or "").strip().rstrip("/")
    if public_base_url:
        return public_base_url
    base_url, _ = _tool_settings(tool_name)
    return base_url


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _request_json(
    tool_name: str,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    base_url, timeout = _tool_settings(tool_name)
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.get(f"{base_url}{path}", params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
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
    return data


def _absolutize_urls(value: Any, base_url: str) -> Any:
    """Absolutize API-returned relative URLs so the LLM can reference them."""
    if isinstance(value, dict):
        return {key: _absolutize_url_field(key, item, base_url) for key, item in value.items()}
    if isinstance(value, list):
        return [_absolutize_urls(item, base_url) for item in value]
    return value


_URL_KEY_SUFFIXES = ("_url", "_path", "_base")


def _absolutize_url_field(key: str, value: Any, base_url: str) -> Any:
    if isinstance(value, str) and value.startswith("/") and any(key.endswith(suffix) for suffix in _URL_KEY_SUFFIXES):
        return f"{base_url}{value}"
    return _absolutize_urls(value, base_url)


# ═══════════════════════════════════════════════════════════════════════════
# Shared helper for tools that need runtime config (public_base_url, etc.)
# ═══════════════════════════════════════════════════════════════════════════


def _config_get(config: RunnableConfig | None, key: str, default: Any = None) -> Any:
    """Read a value from RunnableConfig which may be a dict or an object."""
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _fetch_and_absolutize(
    tool_name: str,
    path: str,
    params: dict[str, Any] | None = None,
    *,
    config: RunnableConfig | None = None,
) -> Any:
    """Request JSON from the local knowledge-base API and absolutize user-facing URLs."""
    # mmkb_bearer_token may ride in configurable (direct set) or context
    # (LangGraph Platform run request `context` field).
    configurable = dict(_config_get(config, "configurable") or {})
    context = dict(_config_get(config, "context") or {})
    bearer_token = str(configurable.get("mmkb_bearer_token") or context.get("mmkb_bearer_token") or "").strip()
    headers = {"Authorization": bearer_token} if bearer_token else None
    data = _request_json(tool_name, path, params=params, headers=headers)
    return _absolutize_urls(data, _resolve_public_base_url(config, tool_name=tool_name))


# ═══════════════════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════════════════


@tool("rag_list_documents", parse_docstring=True)
def rag_list_documents_tool(
    limit: Annotated[int, "Maximum number of ready documents to return, newest first (1-200)."],
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """List indexed documents that are ready for local knowledge-base search.

    Use this when you need to discover what local files are available before
    searching or opening a specific document. This tool intentionally returns
    only documents whose processing status is `ready`; failed, parsing, and
    indexing documents are excluded.

    Returns JSON with:
    - `items`: ready document rows ordered by `updated_at` descending.
    - `returned`: number of rows returned in this page.
    - `total_matched`: total ready documents matching the API-side filter.
    - `status_filter`: always `ready` for this tool.

    Each item includes the document `id` needed by the other RAG tools, `title`,
    `source_ext`, page/chunk progress fields, and output paths such as
    `input_file_path`, `markdown_merged_path`, and `markdown_image_dir_path`.
    Relative URL/path fields are converted to absolute URLs when the caller
    provides a public base URL. These paths are MMKB API-side metadata, not
    sandbox-readable files. Do not pass them to `read_file`, `grep`, `bash`, or
    other sandbox tools; use the RAG tools below to read document content.

    Typical workflow:
    1. Use `rag_list_documents` to discover candidate document IDs.
    2. Use `rag_search` for semantic/keyword retrieval across all ready docs.
    3. Use `rag_get_document_preview`, `rag_get_document_chunks`, or
       `rag_get_document_assets` only when you need deeper context from one
       specific document.

    Args:
        limit: Maximum number of ready documents to return, capped to 200.
    """
    limit = max(min(int(limit), 200), 1)
    data = _fetch_and_absolutize(
        "rag_list_documents",
        "/api/documents",
        params={"status": "ready", "limit": limit},
        config=config,
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

    Use this first when the user asks about uploaded/local documents. It calls
    the local knowledge-base search API and leaves answer planning and
    synthesis to the agent.

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
    - `image_url`: public image URL when available. You may include it in an
      answer as Markdown, for example `![caption](image_url)`.
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
    limit = max(min(int(limit), 50), 1)
    data = _fetch_and_absolutize(
        "rag_search",
        "/api/search",
        params={"q": query, "mode": mode, "limit": limit},
        config=config,
    )
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

    Args:
        document_id: UUID of the local knowledge-base document.
    """
    document_id = str(document_id or "").strip()
    if not document_id:
        return _json({"error": "document_id is required"})
    data = _fetch_and_absolutize("rag_get_document", f"/api/documents/{document_id}", config=config)
    return _json(data)


@tool("rag_get_document_preview", parse_docstring=True)
def rag_get_document_preview_tool(
    document_id: Annotated[str, "UUID of the local knowledge-base document."],
    max_chars: Annotated[int, "Maximum preview characters to return (1000-50000)."] = 12000,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Get a truncated merged-markdown preview for one document.

    Use this when search results identify a relevant document and you need
    broader surrounding context than the retrieved chunks provide. This reads the
    document's merged markdown output and truncates it client-side to avoid
    overloading the model context.

    Returns JSON with:
    - `document_id`
    - `preview_text`: merged markdown content, possibly truncated
    - `truncated`: whether `preview_text` was shortened
    - `total_chars`: original preview length before truncation

    The markdown may contain relative image links such as `md_images/...`.
    If you need concrete image URLs and OCR/caption metadata, call
    `rag_get_document_assets` for the same document.

    Args:
        document_id: UUID of the local knowledge-base document.
        max_chars: Maximum preview characters to return, clamped to 1000-50000.
    """
    document_id = str(document_id or "").strip()
    if not document_id:
        return _json({"error": "document_id is required"})

    data = _fetch_and_absolutize("rag_get_document_preview", f"/api/documents/{document_id}/preview", config=config)
    text = str(data.get("preview_text") or "") if isinstance(data, dict) else ""
    max_chars = max(min(int(max_chars), 50000), 1000)
    if len(text) > max_chars:
        data["preview_text"] = text[:max_chars]
        data["truncated"] = True
        data["total_chars"] = len(text)
    else:
        data["truncated"] = False
        data["total_chars"] = len(text)
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
    document_id = str(document_id or "").strip()
    if not document_id:
        return _json({"error": "document_id is required"})
    data = _fetch_and_absolutize("rag_get_document_chunks", f"/api/documents/{document_id}/chunks", config=config)
    return _json(data)


@tool("rag_get_document_assets", parse_docstring=True)
def rag_get_document_assets_tool(
    document_id: Annotated[str, "UUID of the local knowledge-base document."],
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """List all extracted visual assets for one document.

    Use this when the answer may depend on figures, screenshots, scanned pages,
    image-only documents, charts, tables captured as images, or OCR/caption
    text associated with visuals. This returns the complete extracted asset set
    for one document, not just assets matched by a search query.

    Returns JSON with:
    - `document_id`
    - `count`
    - `items`: visual asset rows ordered by page/block/id

    Each asset item includes:
    - `id`, `asset_type`, `page_id`, `block_id`
    - `image_url`: public image URL when available. You may use it directly in
      Markdown, for example `![caption](image_url)`.
    - `caption_or_ocr`: OCR/caption text. Use it as helpful but potentially
      imperfect evidence.
    - `image_path`: parser-local image filename/path inside the markdown image
      directory
    - `image_abs`: server-local file path; prefer `image_url` in user responses.
    - `metadata_json`: parser/storage metadata.

    Relative image URLs are converted to absolute URLs when the caller provides
    a public base URL. Use this tool together with `rag_search` or
    `rag_get_document_chunks` when you need to place relevant images near a
    text-based answer.

    Args:
        document_id: UUID of the local knowledge-base document.
    """
    document_id = str(document_id or "").strip()
    if not document_id:
        return _json({"error": "document_id is required"})
    data = _fetch_and_absolutize("rag_get_document_assets", f"/api/documents/{document_id}/assets", config=config)
    return _json(data)


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
    data = _fetch_and_absolutize("rag_list_collections", "/api/collections", config=config)
    return _json(data)
