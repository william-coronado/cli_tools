# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A suite of twelve Python CLI tools that pre-process inputs before passing them to Claude Code, reducing token consumption by 10–100×. Each tool is independently installable and optionally exposes an MCP interface.

| Tool | Purpose |
|---|---|
| `pdf_extractor` | Extracts text from PDFs; auto-detects text layer vs. scanned, falls back to OCR |
| `codebase_indexer` | Walks a repo and extracts signatures/docstrings without full file reads |
| `smart_file_tree` | Enhanced `tree` with sizes, ages, language detection, noise filtering |
| `url_fetcher` | Fetches URLs as clean markdown; strips nav/footers/ads/scripts |
| `log_summarizer` | Parses log files and returns only errors, warnings, tracebacks, and metrics |
| `git_context` | Extracts focused git context (commits, diff, blame, status) for a file or repo |
| `data_summarizer` | Summarizes CSV/TSV/JSON/JSONL/Parquet/Excel/SQLite files: schema + sample + stats |
| `dep_inspector` | Inspects Python/JS manifests + lockfiles: declared/resolved/transitive + outdated/audit |
| `notebook_extractor` | Extracts code/markdown from .ipynb; stubs images, truncates outputs, dedupes streams |
| `api_spec_extractor` | Extracts endpoint catalog or detail from OpenAPI 2/3 and GraphQL SDL specs |
| `http_inspector` | Makes an HTTP request and returns status + headers + body shape/sample; HTML bodies → markdown excerpt (optional markitdown) |
| `doc_extractor` | Converts DOCX/PPTX/XLSX/EPUB/MSG to markdown via markitdown |

## Setup

```bash
# From the project root — tools live here directly, there is no tools/ subdirectory
python -m venv .venv
source .venv/bin/activate
bash setup.sh          # installs all pip deps, checks system deps, smoke-tests imports
```

`setup.sh` handles pip installs for all twelve tools (plus the MCP server dep), checks Git/Tesseract/Poppler,
warns about optional deps (Playwright, easyocr, markitdown), and exits non-zero on any failure.
To install a single tool's deps manually: `pip install -r <tool_name>/requirements.txt`.

System dependencies:
- `pdf_extractor`: Tesseract OCR (`apt install tesseract-ocr`) + Poppler (`apt install poppler-utils`)
- `url_fetcher`: Playwright + Chromium is optional for JS pages — `pip install playwright && playwright install chromium`
- `git_context`: Git ≥ 2.11
- `data_summarizer`: pandas / pyarrow / openpyxl are optional — `pip install pandas pyarrow openpyxl` (stdlib paths cover CSV/JSON/JSONL/SQLite without any of them)
- `dep_inspector`: pyyaml is optional (pnpm-lock.yaml only) — `pip install pyyaml`
- `notebook_extractor`: no system deps; pathspec only (already installed)
- `api_spec_extractor`: pyyaml is optional (.yaml/.yml specs); graphql-core is optional (.graphql/.gql) — `pip install pyyaml graphql-core`
- `http_inspector`: httpx required — `pip install httpx`; markitdown is optional (HTML body → markdown)
- `notebook_extractor`: markdownify is optional (HTML-only cell outputs → markdown tables)
- `doc_extractor`: markitdown required for conversion (exits 4 without it) — `pip install 'markitdown[docx,pptx,xlsx,outlook]'`

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
│   ├── duration.py         # Duration string parsing shared by all tools
│   └── languages.py        # Extension → language map (indexer + file tree fallback)
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
├── data_summarizer/
│   ├── cli.py
│   ├── summarizer.py       # DataSummarizer + dataclasses (DataSummary, TableSummary, ...)
│   ├── renderer.py         # markdown/json/text renderers
│   ├── stats.py            # Streaming per-column accumulators
│   ├── readers/            # csv, json, jsonl, parquet, excel, sqlite per-format readers
│   ├── mcp_tool.py
│   └── requirements.txt
├── dep_inspector/
│   ├── cli.py
│   ├── inspector.py        # DepInspector + dataclasses (DepReport, EcosystemReport, ...)
│   ├── renderer.py         # markdown/json/text renderers
│   ├── network.py          # PyPI/npm latest + OSV batch audit, ThreadPoolExecutor fan-out
│   ├── parsers/            # pypi.py (requirements.txt/pyproject.toml/poetry.lock/uv.lock/Pipfile.lock)
│   │                       # npm.py (package.json/package-lock.json/pnpm-lock.yaml)
│   ├── mcp_tool.py
│   └── requirements.txt
├── notebook_extractor/
│   ├── cli.py
│   ├── extractor.py        # NotebookExtractor + dataclasses (NotebookResult, NotebookCell, CellOutput)
│   ├── renderer.py         # markdown (light annotation), json, text
│   ├── dedup.py            # CR-strip + consecutive-line suppression for stream outputs
│   ├── mcp_tool.py
│   └── requirements.txt
├── api_spec_extractor/
│   ├── cli.py
│   ├── extractor.py        # SpecExtractor + dataclasses (SpecResult, EndpointInfo, GraphQLType, ...)
│   ├── renderer.py         # markdown/json/text; catalog table or per-endpoint detail
│   ├── fetcher.py          # stdlib urllib URL fetch (no extra deps)
│   ├── parsers/            # base.py (format detection, schema simplifier, exceptions)
│   │                       # openapi.py (OpenAPI 2/3 parser), graphql.py (GraphQL SDL parser)
│   ├── mcp_tool.py
│   └── requirements.txt
├── http_inspector/
│   ├── cli.py
│   ├── inspector.py        # HttpInspector + dataclasses (HttpResult, BodySummary, HeaderInfo, ...)
│   ├── renderer.py         # markdown/json/text; status + headers table + body shape
│   ├── body/               # json_shape.py (schema inference + sample), xml_shape.py, text.py
│   ├── mcp_tool.py
│   └── requirements.txt
├── doc_extractor/
│   ├── cli.py
│   ├── extractor.py        # DocExtractor + DocResult; markitdown routing per extension
│   ├── renderer.py         # markdown/json/text
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
    ├── test_context.py     # git_context tests
    ├── test_data_summarizer.py
    ├── test_dep_inspector.py
    ├── test_notebook_extractor.py
    ├── test_api_spec_extractor.py
    ├── test_http_inspector.py
    └── test_doc_extractor.py
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

A single FastMCP server, `mcp_server.py` at the project root, exposes **all** tools
to MCP clients (Claude Code, etc.) as one stdio server named `cli-tools`. It is a
thin typed layer: each `@mcp.tool()` function delegates to the matching per-tool
handler in `<tool>/mcp_tool.py`, so param-mapping logic stays in one tested place.

Register it via `.mcp.json` at the project root (already configured for this repo):

```json
{
  "mcpServers": {
    "cli-tools": {
      "command": "${CLAUDE_PROJECT_DIR:-.}/.venv/bin/python3",
      "args": ["${CLAUDE_PROJECT_DIR:-.}/mcp_server.py"]
    }
  }
}
```

This is Claude Code's standard MCP schema (`mcpServers` map, JSON-RPC stdio).
`${CLAUDE_PROJECT_DIR}` is injected by Claude Code and points at the repo root,
so the server resolves no matter which subdirectory Claude Code was launched
from (the `:-.` fallback keeps it working when you run the server by hand from
the root). The command uses the project venv's interpreter so the `mcp`
dependency resolves without activating the venv. The server additionally
prepends its own directory to `sys.path`, so the tool packages import
regardless of the working directory. Install the server dependency with
`pip install -r requirements-mcp.txt` (or `setup.sh`).

Verify in Claude Code with `/mcp` — the `cli-tools` server should list 13 tool
functions (`extract_pdf_text`, `index_codebase`, `smart_file_tree`, `fetch_url`,
`summarize_log`, `git_file_context`, `git_repo_context`, `summarize_data`,
`inspect_dependencies`, `extract_notebook`, `extract_document`,
`extract_api_spec`, `inspect_http`).
That is 13, not 12, because the `git_context` tool exposes two MCP functions
(`git_file_context` and `git_repo_context`); the other eleven tools expose one each.

The per-tool `<tool>/mcp_tool.py` modules contain only the `_handle()` handlers
(exercised directly by the test suite); `mcp_server.py` is the single front
door that wraps them. The server also declares MCP metadata consumed by current
Claude Code versions: server `instructions` (drives tool discovery under
deferred tool loading), per-tool `title` + `ToolAnnotations`
(readOnlyHint/openWorldHint), and `_meta["anthropic/maxResultSizeChars"]` on
tools with legitimately large outputs (extract_pdf_text, fetch_url,
summarize_log, extract_notebook, extract_document).

Several tools overlap native Claude Code capabilities that have grown over time —
the Read tool reads PDFs and `.ipynb` notebooks natively, and WebFetch fetches
URLs as markdown. Prefer the native path for simple cases; reach for these tools
when the native one falls short: `extract_pdf_text` for scanned/OCR or very large
PDFs, `extract_notebook` for huge notebooks (image-stubbing, stream dedup),
`fetch_url` for JS-rendered pages (Playwright) or cached fetches, and
`inspect_http` for JSON body-shape inference.

markitdown powers `doc_extractor` and (optionally) http_inspector's HTML body
summaries, but deliberately does not replace `url_fetcher` (its HTML converter
is markdownify-based, without the trafilatura → readability boilerplate
removal) or `pdf_extractor` (its PDF converter is text-layer only, no OCR).

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
6. Add `mcp_tool.py` with the tool's handler, then add a typed `@mcp.tool()`
   wrapper in `mcp_server.py` that delegates to it (no `.mcp.json` change needed —
   the single `cli-tools` server picks it up automatically)
7. Add tests in `tests/test_<tool_name>.py`
8. Add entries to README.md under Tool Reference and Recommended Workflows
