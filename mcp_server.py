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

mcp = FastMCP("cli-tools")


# --------------------------------------------------------------------------- #
# pdf_extractor
# --------------------------------------------------------------------------- #
@mcp.tool()
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
@mcp.tool()
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
@mcp.tool()
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
    '7d' or '24h'. Use to orient in a codebase before reading files."""
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
@mcp.tool()
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
@mcp.tool()
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
@mcp.tool()
def git_file_context(
    file_path: str,
    base: Optional[str] = None,
    commits: int = 10,
    no_blame: bool = False,
) -> str:
    """Git context for a specific file: recent commits touching it, diff vs.
    base branch, blame summary, and related files. Use before editing a file
    to understand its history. ``no_blame`` is faster for large files."""
    from git_context.mcp_tool import _handle_git_file_context
    return _handle_git_file_context({
        "file_path": file_path,
        "base": base,
        "commits": commits,
        "no_blame": no_blame,
    })


@mcp.tool()
def git_repo_context(
    repo_path: str = ".",
    commits: int = 10,
) -> str:
    """Repo-level git context: branch status, uncommitted changes, and recent
    commit activity. Use at session start to orient yourself."""
    from git_context.mcp_tool import _handle_git_repo_context
    return _handle_git_repo_context({"repo_path": repo_path, "commits": commits})


# --------------------------------------------------------------------------- #
# data_summarizer
# --------------------------------------------------------------------------- #
@mcp.tool()
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
) -> str:
    """Summarize a tabular/structured data file (CSV, TSV, JSON, JSONL,
    Parquet, Excel, SQLite): schema, sample rows (head + tail), and per-column
    statistics. ``table`` selects a SQLite table or Excel sheet. Use instead
    of reading raw data files."""
    from data_summarizer.mcp_tool import _handle
    return _handle({
        "path": path,
        "format_hint": format_hint,
        "table": table,
        "sample": sample,
        "columns": columns,
        "no_stats": no_stats,
        "max_rows": max_rows,
    })


# --------------------------------------------------------------------------- #
# dep_inspector
# --------------------------------------------------------------------------- #
@mcp.tool()
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
    JavaScript): declared/resolved/transitive summary, with optional
    ``outdated`` (registry latest) and ``audit`` (OSV vulnerabilities) checks.
    Use instead of reading raw lockfiles (routinely 500 KB+)."""
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
@mcp.tool()
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
# api_spec_extractor
# --------------------------------------------------------------------------- #
@mcp.tool()
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
@mcp.tool()
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
    ["Name: Value", ...]. Use instead of curl when you care about structure."""
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


if __name__ == "__main__":
    mcp.run()
