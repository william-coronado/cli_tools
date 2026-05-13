# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A suite of six Python CLI tools that pre-process inputs before passing them to Claude Code, reducing token consumption by 10–100×. Each tool is independently installable and optionally exposes an MCP interface.

| Tool | Purpose |
|---|---|
| `pdf_extractor` | Extracts text from PDFs; auto-detects text layer vs. scanned, falls back to OCR |
| `codebase_indexer` | Walks a repo and extracts signatures/docstrings without full file reads |
| `smart_file_tree` | Enhanced `tree` with sizes, ages, language detection, noise filtering |
| `url_fetcher` | Fetches URLs as clean markdown; strips nav/footers/ads/scripts |
| `log_summarizer` | Parses log files and returns only errors, warnings, tracebacks, and metrics |
| `git_context` | Extracts focused git context (commits, diff, blame, status) for a file or repo |

## Setup

```bash
# From the project root — tools live here directly, there is no tools/ subdirectory
python -m venv .venv
source .venv/bin/activate
bash setup.sh          # installs all pip deps, checks system deps, smoke-tests imports
```

`setup.sh` handles pip installs for all six tools, checks Git/Tesseract/Poppler,
warns about optional deps (Playwright, easyocr), and exits non-zero on any failure.
To install a single tool's deps manually: `pip install -r <tool_name>/requirements.txt`.

System dependencies:
- `pdf_extractor`: Tesseract OCR (`apt install tesseract-ocr`) + Poppler (`apt install poppler-utils`)
- `url_fetcher`: Playwright + Chromium is optional for JS pages — `pip install playwright && playwright install chromium`
- `git_context`: Git ≥ 2.11

Verify:
```bash
python -m <tool_name>.cli --help
```

## Running Tools

Each tool runs as `python -m <tool_name>.cli [args]`. Content goes to stdout; progress/warnings go to stderr. All tools support `--format markdown|json|text`.

Exit codes are consistent across all tools: `0` success, `1` input/parse error, `2` policy block (robots.txt/permissions), `3` wrong content type, `4` missing optional dependency.

## Architecture

### Directory Layout

```
<project_root>/
├── shared/
│   ├── __init__.py
│   ├── walker.py           # Shared exclusion + .gitignore logic
│   └── duration.py         # Duration string parsing shared by all tools
├── pdf_extractor/
│   ├── cli.py
│   ├── extractor.py        # Core: text layer detection, pdfplumber, OCR routing
│   ├── ocr.py              # OCR backend abstraction (pytesseract / easyocr)
│   ├── mcp_tool.py
│   └── requirements.txt
├── url_fetcher/
│   ├── cli.py
│   ├── fetcher.py          # Core: HTTP, robots, cache, extractor chain
│   ├── cache.py            # Disk-based response cache (~/.cache/url_fetcher/)
│   ├── robots.py           # robots.txt checker (in-memory session cache)
│   ├── renderer.py         # HTML → markdown with cleaning rules
│   ├── extractors/         # trafilatura → readability → raw (fallback chain)
│   ├── mcp_tool.py
│   └── requirements.txt
├── log_summarizer/
│   ├── cli.py
│   ├── summarizer.py       # Core: streaming pipeline, format detection, data models
│   ├── deduplicator.py     # Sliding-window repetitive line suppression
│   ├── renderer.py         # Markdown/JSON/text output
│   ├── detectors/          # Per-format detectors: pytest, python_logging, training, json, webserver, generic
│   ├── extractors/         # Traceback extractor (stateful multi-line)
│   ├── mcp_tool.py
│   └── requirements.txt
├── codebase_indexer/
│   ├── cli.py
│   ├── indexer.py
│   ├── parsers/            # Per-language parsers (python, generic)
│   ├── mcp_tool.py
│   └── requirements.txt
├── smart_file_tree/
│   ├── cli.py
│   ├── tree.py
│   ├── annotator.py
│   ├── renderer.py
│   ├── mcp_tool.py
│   └── requirements.txt
├── git_context/
│   ├── cli.py
│   ├── context.py
│   ├── git_runner.py
│   ├── renderer.py
│   ├── parsers/            # log, diff, blame, status parsers
│   ├── mcp_tool.py
│   └── requirements.txt
└── tests/
    ├── conftest.py
    ├── fixtures/           # HTML, log, and PDF test fixtures
    ├── test_extractor.py   # pdf_extractor tests
    ├── test_fetcher.py     # url_fetcher tests
    ├── test_summarizer.py  # log_summarizer tests
    ├── test_indexer.py     # codebase_indexer tests
    ├── test_tree.py        # smart_file_tree tests
    └── test_context.py     # git_context tests
```

### Key Invariants

**stdout is content, stderr is metadata.** All tools write extracted content to stdout and progress/timing/warnings to stderr. This keeps output pipeable.

**Tools are independent.** No tool imports from another. Shared logic lives only in `shared/` — never in a single tool's package.

**Never load large files fully into memory.** `log_summarizer` streams via line iterator (never `.readlines()`). `pdf_extractor` streams pages. Always size-check before calling `.read()`.

**Fail open on optional features.** Playwright, easyocr, tiktoken — never required. Tools degrade gracefully and surface install instructions when a missing optional feature is requested.

**Parse structured formats, not human-readable output.** Use `--porcelain` for git, typed regex patterns for log formats, `pdfplumber` AST for PDFs. Human-readable output changes with locale/version; structured output does not.

### Shared Utilities

`shared/walker.py` owns all directory walking and exclusion logic. Both `codebase_indexer` and `smart_file_tree` import from here. If you change hard-exclude lists or `.gitignore` handling, change it in `walker.py` — not in the individual tools.

`shared/duration.py` provides `parse_duration(s: str) -> int` (seconds) and `age_human(ts, now) -> str`. All tools that accept time windows (`--modified-after`, `--blame-window`, `--cache-ttl`) import from here. The shared format is: `30m`, `24h`, `7d`, `2w`, `1mo`, `1y`.

Both `codebase_indexer` and `smart_file_tree` also respect `.treeignore` / `.indexignore` files in the repo root (`.gitignore` syntax).

### MCP Registration

Each tool provides `mcp_tool.py`. Register tools in `.claude/mcp.json` (already configured for this repo):

```json
{
  "tools": [
    {
      "name": "extract_pdf_text",
      "command": ["python", "-m", "pdf_extractor.mcp_tool"],
      "cwd": "~/dev/cli_tools/pdf_extractor"
    },
    {
      "name": "fetch_url",
      "command": ["python", "-m", "url_fetcher.mcp_tool"],
      "cwd": "~/dev/cli_tools/url_fetcher"
    },
    {
      "name": "summarize_log",
      "command": ["python", "-m", "log_summarizer.mcp_tool"],
      "cwd": "~/dev/cli_tools/log_summarizer"
    },
    {
      "name": "index_codebase",
      "command": ["python", "-m", "codebase_indexer.mcp_tool"],
      "cwd": "~/dev/cli_tools/codebase_indexer"
    },
    {
      "name": "smart_file_tree",
      "command": ["python", "-m", "smart_file_tree.mcp_tool"],
      "cwd": "~/dev/cli_tools/smart_file_tree"
    },
    {
      "name": "git_file_context",
      "command": ["python", "-m", "git_context.mcp_tool"],
      "cwd": "~/dev/cli_tools/git_context"
    },
    {
      "name": "git_repo_context",
      "command": ["python", "-m", "git_context.mcp_tool"],
      "cwd": "~/dev/cli_tools/git_context"
    }
  ]
}
```

Update the `cwd` paths if your project root differs from `~/dev/cli_tools/`.

## Testing

All tests live under `tests/`. Run the full suite from the project root:

```bash
python -m pytest tests/
```

Test dependencies beyond the tool requirements: `fpdf2` (PDF fixtures), `respx` (httpx mocking for url_fetcher). HTTP tests use `respx` — no real network calls are made.

## Adding a New Tool

1. Create `<tool_name>/` at the project root following an existing tool's structure
2. Implement `cli.py` — content to stdout, metadata to stderr
3. Add `requirements.txt`
4. If the tool walks directories, import from `shared/walker.py`
5. If the tool accepts time windows, import `parse_duration` from `shared/duration.py`
6. Add `mcp_tool.py` and register in `.claude/mcp.json`
7. Add tests in `tests/test_<tool_name>.py`
8. Add entries to README.md under Tool Reference and Recommended Workflows
