#!/usr/bin/env python3
"""Unified MCP server exposing all cli_tools as a single stdio MCP endpoint.

Claude Code (and any MCP client) connects to this one server and sees every
tool in the suite. Each tool function is a thin, typed wrapper that delegates
to the corresponding per-tool handler in ``<tool>/mcp_tool.py`` — so the
param-mapping logic stays in one place (and stays covered by the existing
per-tool tests).

Run directly for stdio transport:

    python3 mcp_server.py

Register in ``.mcp.json`` at the project root (see that file). Heavy/optional
imports are done lazily inside each tool function so a missing optional
dependency for one tool never prevents the server from starting.
"""
from __future__ import annotations

import os
import sys
from typing import Literal, Optional

# Make the tool packages importable regardless of the launch directory.
# ⚠️  Do NOT name tool packages after stdlib modules (e.g., json, pathlib, etc.)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP(
    "cli-tools",
    instructions=(
        "Token-efficient pre-processors that do more than a raw read, "
        "regardless of input size: cross-reference dependency manifests "
        "against lockfiles and CVE databases, filter noise out of "
        "repository structure, infer HTTP/JSON body shape, extract focused "
        "git history, OCR scanned PDFs, dedupe noisy logs and notebook "
        "output, and more. Reach for these before `find`/`ls -R`, `cat`, "
        "`curl`, or `sqlite3` on: PDFs (including scanned/OCR), Jupyter "
        "notebooks, log files, tabular data (CSV/JSON/JSONL/Parquet/Excel/"
        "SQLite), dependency manifests and lockfiles, OpenAPI/GraphQL "
        "specs, office documents (DOCX/PPTX/XLSX/EPUB), git history, "
        "repository structure, JS-rendered web pages, and HTTP APIs — even "
        "when the individual file or response looks small, since the value "
        "is in the structure/cross-referencing, not just token count. Each "
        "tool returns a compact markdown summary — typically 10-100x fewer "
        "tokens than the raw source."
    ),
)

# All tools are inspection-only. The network-facing ones (fetch_url,
# extract_api_spec URL mode, dep_inspector's registry/OSV checks) reach the
# open web; inspect_http can send non-GET requests, so it is not marked
# read-only.
_LOCAL_RO = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_NETWORK_RO = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# Some tools legitimately return large payloads (full PDF text, whole
# notebooks, fetched pages). Claude Code reads this _meta key to raise the
# per-tool output cap.
_LARGE_OUTPUT = {"anthropic/maxResultSizeChars": 200_000}


# --------------------------------------------------------------------------- #
# pdf_extractor
# --------------------------------------------------------------------------- #
@mcp.tool(title="PDF Text Extractor", annotations=_LOCAL_RO, meta=_LARGE_OUTPUT)
def extract_pdf_text(
    pdf_path: str,
    pages: Optional[str] = None,
    force_ocr: bool = False,
) -> str:
    """Extract clean text from a PDF file. Auto-detects whether the PDF has a
    text layer or requires OCR. Returns structured markdown with page markers.
    Use for scanned/image PDFs or large documents where the native reader is
    too costly. ``pages`` accepts e.g. '1-5' or '1,3,7'."""
    from pdf_extractor.mcp_tool import _handle
    return _handle({"pdf_path": pdf_path, "pages": pages, "force_ocr": force_ocr})


# --------------------------------------------------------------------------- #
# codebase_indexer
# --------------------------------------------------------------------------- #
@mcp.tool(title="Codebase Indexer", annotations=_LOCAL_RO)
def index_codebase(
    repo_path: str = ".",
    detail: Literal["low", "normal", "high"] = "normal",
    format: Literal["markdown", "json", "outline"] = "markdown",
    include_extensions: Optional[list[str]] = None,
    exclude_patterns: Optional[list[str]] = None,
) -> str:
    """Walk a code repository and return a structured index of files, classes,
    functions, and imports — without loading full file contents. Use before
    reading individual files to understand repo structure. 'low' for large
    repos, 'high' for deep analysis."""
    from codebase_indexer.mcp_tool import _handle_index_codebase
    return _handle_index_codebase({
        "repo_path": repo_path,
        "detail": detail,
        "format": format,
        "include_extensions": include_extensions,
        "exclude_patterns": exclude_patterns,
    })


# --------------------------------------------------------------------------- #
# smart_file_tree
# --------------------------------------------------------------------------- #
@mcp.tool(title="Smart File Tree", annotations=_LOCAL_RO)
def smart_file_tree(
    path: Optional[str] = None,
    depth: Optional[int] = None,
    format: Literal["tree", "compact", "json"] = "tree",
    focus: Optional[str] = None,
    modified_after: Optional[str] = None,
    exclude_patterns: Optional[list[str]] = None,
    include_extensions: Optional[list[str]] = None,
) -> str:
    """Generate an annotated file tree: sizes, ages, languages, and flags
    (large, binary, recently modified). Excludes noise (node_modules,
    __pycache__, build artifacts). ``modified_after`` takes a window like
    '7d' or '24h'. Use before running `find`/`ls -R` on an unfamiliar
    directory, and to orient in a codebase before reading files."""
    from smart_file_tree.mcp_tool import _handle_call
    return _handle_call({
        "path": path,
        "depth": depth,
        "format": format,
        "focus": focus,
        "modified_after": modified_after,
        "exclude_patterns": exclude_patterns,
        "include_extensions": include_extensions,
    })


# --------------------------------------------------------------------------- #
# url_fetcher
# --------------------------------------------------------------------------- #
@mcp.tool(title="URL Fetcher", annotations=_NETWORK_RO, meta=_LARGE_OUTPUT)
def fetch_url(
    url: str,
    use_js: bool = False,
    no_cache: bool = False,
    include_links: bool = True,
) -> str:
    """Fetch a URL and return clean, readable markdown — strips navigation,
    ads, footers, and boilerplate. Set ``use_js`` for JS-rendered pages
    (requires Playwright). Responses are cached locally unless ``no_cache``."""
    from url_fetcher.mcp_tool import _handle
    return _handle({
        "url": url,
        "use_js": use_js,
        "no_cache": no_cache,
        "include_links": include_links,
    })


# --------------------------------------------------------------------------- #
# log_summarizer
# --------------------------------------------------------------------------- #
@mcp.tool(title="Log Summarizer", annotations=_LOCAL_RO, meta=_LARGE_OUTPUT)
def summarize_log(
    path: str,
    format_hint: Optional[
        Literal["pytest", "python", "training", "json", "webserver", "generic"]
    ] = None,
    errors_only: bool = False,
    tail: Optional[int] = None,
) -> str:
    """Summarize a log file, extracting only errors, warnings, tracebacks, and
    key metrics. Handles pytest, Python logging, ML training, JSON, and web
    server logs. ``tail`` limits to the last N lines. Use instead of reading
    raw logs."""
    from log_summarizer.mcp_tool import _handle
    return _handle({
        "path": path,
        "format_hint": format_hint,
        "errors_only": errors_only,
        "tail": tail,
    })


# --------------------------------------------------------------------------- #
# git_context
# --------------------------------------------------------------------------- #
@mcp.tool(title="Git File Context", annotations=_LOCAL_RO)
def git_file_context(
    file_path: str,
    base: Optional[str] = None,
    commits: int = 10,
    no_blame: bool = False,
) -> str:
    """Git context for a specific file: recent commits touching it, diff vs.
    base branch, blame summary, and related files. For deep-history/blame
    archaeology before editing a file — not a replacement for the routine
    `git status`/`diff`/`log` pre-commit check. ``no_blame`` is faster for
    large files."""
    from git_context.mcp_tool import _handle_git_file_context
    return _handle_git_file_context({
        "file_path": file_path,
        "base": base,
        "commits": commits,
        "no_blame": no_blame,
    })


@mcp.tool(title="Git Repo Context", annotations=_LOCAL_RO)
def git_repo_context(
    repo_path: str = ".",
    commits: int = 10,
) -> str:
    """Repo-level git context: branch status, uncommitted changes, and recent
    commit activity. Use at session start to orient yourself in an unfamiliar
    repo — not a replacement for the routine `git status`/`diff`/`log`
    pre-commit check."""
    from git_context.mcp_tool import _handle_git_repo_context
    return _handle_git_repo_context({"repo_path": repo_path, "commits": commits})


# --------------------------------------------------------------------------- #
# data_summarizer
# --------------------------------------------------------------------------- #
@mcp.tool(title="Data Summarizer", annotations=_LOCAL_RO)
def summarize_data(
    path: str,
    format_hint: Optional[
        Literal["csv", "tsv", "json", "jsonl", "parquet", "xlsx", "sqlite"]
    ] = None,
    table: Optional[str] = None,
    sample: int = 5,
    columns: Optional[list[str]] = None,
    no_stats: bool = False,
    max_rows: int = 100_000,
    query: Optional[str] = None,
) -> str:
    """Summarize a tabular/structured data file (CSV, TSV, JSON, JSONL,
    Parquet, Excel, SQLite): schema, sample rows (head + tail), and per-column
    statistics. ``table`` selects a SQLite table or Excel sheet. ``query``
    runs a single read-only SELECT against a SQLite file instead of
    summarizing whole tables — use for a targeted lookup rather than a full
    dump (SELECT-only, including `WITH ... SELECT` CTEs; no mutations).
    ``query`` cannot be combined with ``table``/``columns``. Use instead of
    reading raw data files."""
    from data_summarizer.mcp_tool import _handle
    return _handle({
        "path": path,
        "format_hint": format_hint,
        "table": table,
        "sample": sample,
        "columns": columns,
        "no_stats": no_stats,
        "max_rows": max_rows,
        "query": query,
    })


# --------------------------------------------------------------------------- #
# dep_inspector
# --------------------------------------------------------------------------- #
@mcp.tool(title="Dependency Inspector", annotations=_NETWORK_RO)
def inspect_dependencies(
    path: str,
    ecosystem: Optional[Literal["pypi", "npm"]] = None,
    outdated: bool = False,
    audit: bool = False,
    no_dev: bool = False,
    direct_only: bool = False,
    severity: Optional[list[str]] = None,
) -> str:
    """Inspect a project's dependency manifest and lockfile (Python or
    JavaScript): cross-references declared vs. resolved vs. transitive deps,
    with optional ``outdated`` (registry latest) and ``audit`` (OSV
    vulnerabilities) checks — value `cat` can't give you regardless of
    manifest size. Use instead of reading raw manifests/lockfiles."""
    from dep_inspector.mcp_tool import _handle
    return _handle({
        "path": path,
        "ecosystem": ecosystem,
        "outdated": outdated,
        "audit": audit,
        "no_dev": no_dev,
        "direct_only": direct_only,
        "severity": severity,
    })


# --------------------------------------------------------------------------- #
# notebook_extractor
# --------------------------------------------------------------------------- #
@mcp.tool(title="Notebook Extractor", annotations=_LOCAL_RO, meta=_LARGE_OUTPUT)
def extract_notebook(
    path: str,
    cells: Optional[str] = None,
    code_only: bool = False,
    markdown_only: bool = False,
    tags: Optional[list[str]] = None,
    no_outputs: bool = False,
    max_output_lines: int = 30,
) -> str:
    """Extract code and markdown from a Jupyter notebook (.ipynb), stripping
    base64 images, truncating long outputs, and deduplicating progress-bar
    streams. ``cells`` is a slice like '0:20'. Use for large notebooks where
    the native reader is too costly."""
    from notebook_extractor.mcp_tool import _handle
    return _handle({
        "path": path,
        "cells": cells,
        "code_only": code_only,
        "markdown_only": markdown_only,
        "tags": tags,
        "no_outputs": no_outputs,
        "max_output_lines": max_output_lines,
    })


# --------------------------------------------------------------------------- #
# doc_extractor
# --------------------------------------------------------------------------- #
@mcp.tool(title="Document Extractor", annotations=_LOCAL_RO, meta=_LARGE_OUTPUT)
def extract_document(
    path: str,
    max_chars: int = 200_000,
) -> str:
    """Extract markdown from an office/document file: DOCX, PPTX, XLSX
    (document view), EPUB, or MSG. Use instead of reading these binary
    formats directly. For PDFs use extract_pdf_text, for .ipynb use
    extract_notebook, for data files use summarize_data."""
    from doc_extractor.mcp_tool import _handle
    return _handle({"path": path, "max_chars": max_chars})


# --------------------------------------------------------------------------- #
# api_spec_extractor
# --------------------------------------------------------------------------- #
@mcp.tool(title="API Spec Extractor", annotations=_NETWORK_RO)
def extract_api_spec(
    source: str,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    tag: Optional[str] = None,
    detail: bool = False,
    include_deprecated: bool = False,
) -> str:
    """Extract a catalog or detail view from an OpenAPI (2/3) or GraphQL SDL
    spec. Returns an endpoint table (default) or per-endpoint detail with
    parameters and response schemas (``detail=true``). ``source`` is a file
    path or URL. ``method`` is comma-separated HTTP methods."""
    from api_spec_extractor.mcp_tool import _handle
    return _handle({
        "source": source,
        "endpoint": endpoint,
        "method": method,
        "tag": tag,
        "detail": detail,
        "include_deprecated": include_deprecated,
    })


# --------------------------------------------------------------------------- #
# http_inspector
# --------------------------------------------------------------------------- #
@mcp.tool(
    title="HTTP Inspector",
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, openWorldHint=True
    ),
)
def inspect_http(
    url: str,
    method: Optional[str] = None,
    headers: Optional[list[str]] = None,
    data: Optional[str] = None,
    content_type: Optional[str] = None,
    max_array_items: int = 5,
    shape_only: bool = False,
    no_redact_cookies: bool = False,
    show_all_headers: bool = False,
    timeout: float = 10.0,
) -> str:
    """Make an HTTP request and return a token-efficient summary: status code,
    selected response headers, and a shape + sample of the body. JSON
    responses show a schema + N sample records. ``headers`` are
    ["Name: Value", ...]. Use instead of curl for large, paginated, or
    unknown-shape bodies; a plain curl is fine for a quick small/known-shape
    check (e.g. a health-check endpoint you already know the shape of)."""
    from http_inspector.mcp_tool import _handle
    return _handle({
        "url": url,
        "method": method,
        "headers": headers or [],
        "data": data,
        "content_type": content_type,
        "max_array_items": max_array_items,
        "shape_only": shape_only,
        "no_redact_cookies": no_redact_cookies,
        "show_all_headers": show_all_headers,
        "timeout": timeout,
    })


# --------------------------------------------------------------------------- #
# inspect_image
# --------------------------------------------------------------------------- #
@mcp.tool(title="Image Inspector", annotations=_LOCAL_RO)
def inspect_image(path: str) -> str:
    """Report image metadata: dimensions, color mode, format, and file size.
    Use instead of shelling out to Python/PIL for a quick dimension check
    (e.g. before doing pixel-precise UI/asset work)."""
    from inspect_image.mcp_tool import _handle
    return _handle({"path": path})


if __name__ == "__main__":
    mcp.run()
