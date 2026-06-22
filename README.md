# Claude Code Token-Saving Tools

A suite of nine Python CLI tools that pre-process common inputs before handing them
to Claude Code — cutting token consumption by 10–100× on typical tasks.

Each tool is independently installable, exposes a consistent CLI interface, and
optionally registers as an MCP tool so Claude Code can call it directly without
a bash step.

---

## Tools

| Tool | What it replaces | Typical reduction |
|---|---|---|
| [`pdf_extractor`](#pdf-extractor) | Reading raw PDFs as images or binary | 50 KB → 3 KB per doc |
| [`codebase_indexer`](#codebase-indexer) | Reading 20–40 files to understand structure | Full files → signatures only |
| [`smart_file_tree`](#smart-file-tree) | 4–6 shell commands (`ls`, `find`, `stat`, `file`) | Multi-command → single call |
| [`url_fetcher`](#url-fetcher) | Reading raw HTML with nav/footer/script noise | 800 KB → 5 KB per page |
| [`log_summarizer`](#log-summarizer) | Reading large log files line by line | 10 MB → ~30 lines of signal |
| [`git_context`](#git-context) | 5–8 sequential `git` commands per file | Multi-command → single call |
| [`data_summarizer`](#data-summarizer) | Reading raw CSV/Parquet/SQLite/Excel/JSON | 100 MB → schema + sample + stats |
| [`dep_inspector`](#dep_inspector) | Reading raw lockfiles (500 KB+ package-lock.json) | Declared/resolved/transitive + outdated/audit |
| [`notebook_extractor`](#notebook_extractor) | Reading raw .ipynb with base64/stream noise | Clean cells + stubbed images + deduped streams |
| [`api_spec_extractor`](#api_spec_extractor) | Pasting raw OpenAPI/Swagger/GraphQL specs | Endpoint catalog or per-endpoint detail (5–100× reduction) |
| [`http_inspector`](#http_inspector) | Full API response bodies in context | Status + headers + body shape + sample (5–100× reduction) |

---

## Repository Layout

Tools live directly at the project root — there is no `tools/` subdirectory.

```
<project_root>/
├── shared/
│   ├── walker.py           # Shared exclusion logic (used by indexer + file tree)
│   └── duration.py         # Duration string parsing (used by all tools)
├── pdf_extractor/
├── codebase_indexer/
├── smart_file_tree/
├── url_fetcher/
├── log_summarizer/
├── git_context/
├── data_summarizer/
├── dep_inspector/
├── notebook_extractor/
├── api_spec_extractor/
├── http_inspector/
└── tests/
    └── fixtures/           # HTML, log, and PDF test fixtures
```

---

## Setup

### 1. Create a virtual environment

```bash
# From the project root
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install tool dependencies

```bash
bash setup.sh
```

`setup.sh` installs all pip dependencies, checks for system packages (Tesseract,
Poppler, Git), warns about optional deps (Playwright, easyocr), and runs a quick
import smoke test for each tool. Exit code is non-zero if any required step fails.

Alternatively, install each tool individually:

```bash
pip install -r pdf_extractor/requirements.txt
pip install -r codebase_indexer/requirements.txt
pip install -r smart_file_tree/requirements.txt
pip install -r url_fetcher/requirements.txt
pip install -r log_summarizer/requirements.txt
pip install -r git_context/requirements.txt
pip install -r data_summarizer/requirements.txt
pip install -r dep_inspector/requirements.txt
pip install -r notebook_extractor/requirements.txt
pip install -r api_spec_extractor/requirements.txt
pip install -r http_inspector/requirements.txt
```

### 3. System dependencies

Some tools require system packages beyond pip:

| Tool | Dependency | Install |
|---|---|---|
| `pdf_extractor` | Tesseract OCR | `brew install tesseract` / `apt install tesseract-ocr` |
| `pdf_extractor` | Poppler (pdf2image) | `brew install poppler` / `apt install poppler-utils` |
| `url_fetcher` | Playwright + Chromium *(optional, JS pages only)* | `pip install playwright && playwright install chromium` |
| `git_context` | Git ≥ 2.11 | Pre-installed on most systems |
| `data_summarizer` | pandas / pyarrow / openpyxl *(optional)* | `pip install pandas pyarrow openpyxl` |
| `dep_inspector` | pyyaml *(optional, pnpm-lock.yaml only)* | `pip install pyyaml` |
| `notebook_extractor` | *(none — stdlib + pathspec only)* | — |
| `api_spec_extractor` | pyyaml *(optional, .yaml/.yml specs)* | `pip install pyyaml` |
| `api_spec_extractor` | graphql-core *(optional, .graphql/.gql specs)* | `pip install graphql-core` |
| `http_inspector` | httpx *(required)* | `pip install httpx` |

### 4. Verify installation

```bash
python -m pdf_extractor.cli --help
python -m codebase_indexer.cli --help
python -m smart_file_tree.cli --help
python -m url_fetcher.cli --help
python -m log_summarizer.cli --help
python -m git_context.cli --help
python -m data_summarizer.cli --help
python -m dep_inspector.cli --help
python -m notebook_extractor.cli --help
python -m api_spec_extractor.cli --help
python -m http_inspector.cli --help
```

---

## MCP Registration

All tools are exposed through a **single** FastMCP server — `mcp_server.py` at the
project root — registered as one stdio MCP server named `cli-tools`. Install its
dependency and add the project-root `.mcp.json` (already present in this repo):

```bash
pip install -r requirements-mcp.txt   # installs `mcp` (FastMCP); also run by setup.sh
```

```json
{
  "mcpServers": {
    "cli-tools": {
      "command": "python3",
      "args": ["mcp_server.py"]
    }
  }
}
```

This is Claude Code's standard MCP configuration (`mcpServers` map + JSON-RPC over
stdio) and lives at `.mcp.json` in the project root — **not** `.claude/mcp.json`.
Claude Code launches project-scoped servers from the repo root, so the relative
`mcp_server.py` resolves; the server also adds its own directory to `sys.path`, so
the tool packages import no matter where it is launched from. If you register the
server globally instead, use an absolute path in `args`.

The server is a thin, typed layer: each tool function delegates to the existing
per-tool handler in `<tool>/mcp_tool.py`, so there is exactly one place that maps
parameters to work.

**Verify MCP tools are registered:**

```bash
# In Claude Code, run:
/mcp
# The `cli-tools` server should appear with all 12 tools.
```

> **Note on native overlap.** Claude Code's built-in tools now cover some of this
> ground: the Read tool reads PDFs and `.ipynb` notebooks directly, and WebFetch
> returns URLs as markdown. Prefer the native path for simple cases and reach for
> these tools when it falls short — `extract_pdf_text` for scanned/OCR or very
> large PDFs, `extract_notebook` for huge notebooks, `fetch_url` for JS-rendered
> or cached pages, and `inspect_http` for JSON body-shape inference.

---

## Tool Reference

### PDF Extractor

Extracts clean text from PDFs. Auto-detects text layer vs. scanned; falls back to
OCR for image-only pages.

```bash
# Single file → stdout
python -m pdf_extractor.cli report.pdf

# Single file → output file
python -m pdf_extractor.cli report.pdf -o report.md

# Specific pages only
python -m pdf_extractor.cli report.pdf --pages 1-5

# Force OCR (skip text layer detection)
python -m pdf_extractor.cli report.pdf --force-ocr

# Use easyocr backend instead of pytesseract
python -m pdf_extractor.cli report.pdf --force-ocr --ocr-backend easyocr

# Batch: all PDFs in a directory
python -m pdf_extractor.cli ./docs/

# JSON output (for piping)
python -m pdf_extractor.cli report.pdf --format json
```

**MCP usage (in Claude Code):**
```
extract_pdf_text(pdf_path="docs/spec.pdf")
extract_pdf_text(pdf_path="docs/scanned_contract.pdf", force_ocr=true)
extract_pdf_text(pdf_path="docs/report.pdf", pages="1-10")
```

---

### Codebase Indexer

Walks a repo and extracts signatures, docstrings, and imports — without reading
full file contents.

```bash
# Index current directory (normal detail)
python -m codebase_indexer.cli .

# Low detail: outline + language stats only (~500 tokens for a 50-file repo)
python -m codebase_indexer.cli . --detail low

# High detail: full docstrings + constants + all imports
python -m codebase_indexer.cli . --detail high

# Focus on a specific subdirectory
python -m codebase_indexer.cli . --focus src/models

# Only Python files
python -m codebase_indexer.cli . --include-ext .py

# Outline format (ultra-compact tree)
python -m codebase_indexer.cli . --format outline

# Save to file
python -m codebase_indexer.cli . -o index.md
```

**MCP usage:**
```
index_codebase()
index_codebase(detail="low")
index_codebase(detail="high", include_extensions=[".py"])
index_codebase(repo_path="src/models", detail="high")
```

---

### Smart File Tree

Enhanced `tree` with sizes, ages, language detection, and noise filtering.
Automatically excludes `node_modules`, `__pycache__`, `.git`, and other noise.
Dotfiles (names starting with `.`) are hidden by default; use `--show-hidden` to include them.

```bash
# Current directory
python -m smart_file_tree.cli .

# Limit depth
python -m smart_file_tree.cli . --depth 2

# Show only recently modified files (last 7 days)
python -m smart_file_tree.cli . --modified-after 7d

# Include dotfiles (.env, .gitignore, etc.)
python -m smart_file_tree.cli . --show-hidden

# Focus on a subdirectory
python -m smart_file_tree.cli . --focus src/

# Only Python files
python -m smart_file_tree.cli . --include-ext .py

# Flat sorted list (no tree structure), sorted by age
python -m smart_file_tree.cli . --format compact --sort age

# Files over 1 MB
python -m smart_file_tree.cli . --min-size 1MB
```

**MCP usage:**
```
smart_file_tree()
smart_file_tree(depth=2)
smart_file_tree(modified_after="7d")
smart_file_tree(focus="src/models")
smart_file_tree(format="compact", include_extensions=[".py", ".yaml"])
```

---

### URL Fetcher

Fetches a URL and returns clean markdown. Strips nav, footers, ads, and scripts.
Caches responses locally (`~/.cache/url_fetcher/`); respects `robots.txt` by default.

```bash
# Fetch a single URL
python -m url_fetcher.cli https://docs.python.org/3/library/ast.html

# Force fresh fetch (bypass cache)
python -m url_fetcher.cli https://example.com --no-cache

# Set cache TTL (uses duration format: 30m, 2h, 7d)
python -m url_fetcher.cli https://example.com --cache-ttl 30m

# Use Playwright for JS-rendered pages
python -m url_fetcher.cli https://example.com --js

# Strip hyperlinks from output
python -m url_fetcher.cli https://example.com --no-links

# Batch: fetch all URLs in a file, concatenated to stdout
python -m url_fetcher.cli --batch urls.txt

# Batch: write combined output to a file
python -m url_fetcher.cli --batch urls.txt -o fetched.md

# Clear the local cache
python -m url_fetcher.cli --clear-cache

# Skip robots.txt check
python -m url_fetcher.cli https://example.com --no-robots
```

**MCP usage:**
```
fetch_url(url="https://arxiv.org/abs/2310.06825")
fetch_url(url="https://example.com", use_js=true)
fetch_url(url="https://docs.anthropic.com/api", no_cache=true)
fetch_url(url="https://example.com", include_links=false)
```

---

### Log Summarizer

Parses log files and returns only errors, warnings, tracebacks, and metrics.
Auto-detects format: pytest, Python logging, ML training, JSON lines, nginx/apache,
or generic. Streams line-by-line — handles multi-GB files without loading into memory.

```bash
# Summarize a file
python -m log_summarizer.cli training.log

# From stdin
cat app.log | python -m log_summarizer.cli -

# Errors and tracebacks only
python -m log_summarizer.cli app.log --errors-only

# Force format (skip auto-detection)
python -m log_summarizer.cli output.log --format-hint pytest

# Available format hints: pytest | python | training | json | webserver | generic

# Process only the last 1000 lines (useful for large live logs)
python -m log_summarizer.cli app.log --tail 1000

# Process only the first 500 lines
python -m log_summarizer.cli app.log --head 500

# Summarize all .log files in a directory
python -m log_summarizer.cli ./logs/

# Recurse into subdirectories
python -m log_summarizer.cli ./logs/ --recursive --pattern "*.log"

# Disable deduplication (show every repeated line)
python -m log_summarizer.cli app.log --no-dedup

# JSON output
python -m log_summarizer.cli training.log --format json
```

**MCP usage:**
```
summarize_log(path="logs/training.log")
summarize_log(path="logs/training.log", errors_only=true)
summarize_log(path="logs/app.log", tail=500)
summarize_log(path="pytest_output.log", format_hint="pytest")
```

---

### Git Context

Extracts focused git context for a file or repo — commits, diff, blame, and status.

```bash
# File mode: context for a specific file
python -m git_context.cli src/models/classifier.py

# File mode: skip expensive sections for faster output
python -m git_context.cli src/models/classifier.py --no-blame
python -m git_context.cli src/models/classifier.py --no-diff
python -m git_context.cli src/models/classifier.py --no-related

# File mode: diff vs. specific branch
python -m git_context.cli src/models/classifier.py --base main

# Repo mode: branch status + recent activity
python -m git_context.cli .

# Repo mode: skip uncommitted diff collection
python -m git_context.cli . --no-diff

# Repo mode: more commits
python -m git_context.cli . --commits 20

# JSON output
python -m git_context.cli src/models/classifier.py --format json
```

**MCP usage:**
```
git_file_context(file_path="src/models/classifier.py")
git_file_context(file_path="src/models/classifier.py", base="main", no_blame=true)
git_repo_context()
git_repo_context(commits=20)
```

---

### `data_summarizer`

Summarizes tabular and structured data files — CSV, TSV, JSON, JSONL, Parquet,
Excel, SQLite — returning schema, sample rows, and per-column statistics
instead of the full file. Stdlib paths cover CSV/JSON/JSONL/SQLite without any
optional installs; richer stats and Parquet/Excel support need
`pip install pandas pyarrow openpyxl`.

**Common usage:**
```bash
# Single file
python -m data_summarizer.cli sales.csv

# Restrict to a few columns
python -m data_summarizer.cli sales.csv --columns order_id,amount_usd,region

# SQLite multi-table
python -m data_summarizer.cli analytics.sqlite
python -m data_summarizer.cli analytics.sqlite --table users --table orders

# JSON: array-of-records is summarized like a table;
#       a nested object falls back to a top-level structural summary
python -m data_summarizer.cli config.json
python -m data_summarizer.cli api_response.json

# Directory mode (respects .gitignore + node_modules etc.)
python -m data_summarizer.cli ./data --recursive

# Cap rows scanned (big files) — stats become sampled, file still summarized
python -m data_summarizer.cli huge.csv --max-rows 50000

# Skip statistics (faster; schema + sample still produced)
python -m data_summarizer.cli sales.csv --no-stats

# JSON output for downstream tools
python -m data_summarizer.cli sales.csv --format json
```

**MCP usage:**
```
summarize_data(path="sales.csv")
summarize_data(path="analytics.sqlite", table="orders")
summarize_data(path="huge.csv", max_rows=50000, no_stats=true)
```

**Exit codes:** `0` success · `1` input/parse error · `3` wrong content type
(no reader matches) · `4` missing optional dep (e.g. Parquet without pyarrow).

---

### `dep_inspector`

Inspects Python and JavaScript dependency manifests and lockfiles, returning
declared dependencies, resolved versions, a top-transitive summary, and
optional outdated/vulnerability checks — without dumping the raw lockfile
(which is routinely 500 KB+).

Supports: `requirements.txt`, `pyproject.toml` (PEP 621 + Poetry),
`poetry.lock`, `uv.lock`, `Pipfile.lock` (Python); `package.json`,
`package-lock.json` v2/v3, `pnpm-lock.yaml` (npm). `yarn.lock` falls back to
declared-only with a warning.

Network features (`--outdated`, `--audit`) are opt-in and fail open: network
failures produce a warning on stderr and exit 0.

**Common usage:**
```bash
# Inspect a Python project
python -m dep_inspector.cli path/to/project

# Inspect a JS project, show latest versions from npm registry
python -m dep_inspector.cli path/to/project --outdated

# Vulnerability audit via OSV
python -m dep_inspector.cli path/to/project --audit

# Only show critical/high advisories
python -m dep_inspector.cli path/to/project --audit --severity critical,high

# Show full transitive list instead of top-K summary
python -m dep_inspector.cli path/to/project --all

# Exclude devDependencies
python -m dep_inspector.cli path/to/project --no-dev

# Both outdated + audit, JSON output
python -m dep_inspector.cli path/to/project --outdated --audit --format json
```

**MCP usage:**
```
inspect_dependencies(path=".")
inspect_dependencies(path=".", outdated=true)
inspect_dependencies(path=".", audit=true, severity=["critical", "high"])
inspect_dependencies(path=".", direct_only=true, no_dev=true)
```

**Exit codes:** `0` success (including degraded-network) · `1` input/parse
error · `3` no supported manifest found · `4` missing optional dep.

---

### `notebook_extractor`

Extracts code and markdown from Jupyter `.ipynb` notebooks, stripping
base64 images (→ `<image: png 800×600, 42 KB>` stubs), truncating long
outputs, and deduplicating repetitive progress-bar streams. No optional
dependencies — only stdlib and pathspec.

**Common usage:**
```bash
# Whole notebook
python -m notebook_extractor.cli analysis.ipynb

# First 20 cells only
python -m notebook_extractor.cli analysis.ipynb --cells 0:20

# Code cells only, no outputs
python -m notebook_extractor.cli analysis.ipynb --code-only --no-outputs

# Cells tagged "training" only, keep 10 output lines max
python -m notebook_extractor.cli analysis.ipynb --tag training --max-output-lines 10

# Directory of notebooks (respects .gitignore)
python -m notebook_extractor.cli notebooks/ --recursive

# JSON output for structured processing
python -m notebook_extractor.cli analysis.ipynb --format json
```

**MCP usage:**
```
extract_notebook(path="analysis.ipynb")
extract_notebook(path="analysis.ipynb", cells="0:20", max_output_lines=10)
extract_notebook(path="analysis.ipynb", code_only=true, no_outputs=true)
extract_notebook(path="analysis.ipynb", tags=["training", "viz"])
```

**Exit codes:** `0` success · `1` file not found or not a notebook ·
`3` no `.ipynb` files found in directory.

---

### `api_spec_extractor`

Extracts a catalog table or per-endpoint detail view from OpenAPI 2/3 (Swagger)
and GraphQL SDL specs. A real-world `swagger.json` is routinely 50 KB+; this tool
surfaces the endpoint list or the exact shape of a single operation in a fraction
of the token cost.

**Common usage:**
```bash
# Endpoint catalog (default)
python -m api_spec_extractor.cli openapi.json

# Per-endpoint detail with parameters and response schemas
python -m api_spec_extractor.cli openapi.json --detail

# Filter by tag, method, or path substring
python -m api_spec_extractor.cli openapi.json --tag billing
python -m api_spec_extractor.cli openapi.json --method GET,POST
python -m api_spec_extractor.cli openapi.json --endpoint /orders

# Include deprecated endpoints (excluded by default)
python -m api_spec_extractor.cli openapi.json --include-deprecated

# YAML spec
python -m api_spec_extractor.cli openapi.yaml

# GraphQL SDL
python -m api_spec_extractor.cli schema.graphql

# URL input
python -m api_spec_extractor.cli https://petstore.example.com/openapi.json

# JSON output for structured processing
python -m api_spec_extractor.cli openapi.json --format json
```

**MCP usage:**
```
extract_api_spec(source="openapi.json")
extract_api_spec(source="openapi.json", detail=true)
extract_api_spec(source="openapi.json", tag="billing", method="GET,POST")
extract_api_spec(source="schema.graphql")
extract_api_spec(source="https://example.com/openapi.json", endpoint="/orders")
```

**Optional dependencies:**
- `pyyaml` — required for `.yaml`/`.yml` spec files (`pip install pyyaml`)
- `graphql-core` — required for `.graphql`/`.gql` files (`pip install graphql-core`)

**Exit codes:** `0` success · `1` file not found or parse error ·
`3` unrecognized format (not OpenAPI or GraphQL) · `4` missing optional dep.

---

### `http_inspector`

Makes a live HTTP request and returns a token-efficient summary: status code,
selected response headers (rate-limit, content, server), and a shape + sample
of the body. JSON responses show a schema and N sample records. Text and XML
are truncated/summarized. Cookie values are redacted by default.

Complements `url_fetcher` (which targets human-readable web pages) and
`api_spec_extractor` (which reads spec files offline).

**Common usage:**
```bash
# GET and summarize
python -m http_inspector.cli https://api.example.com/users

# POST with a JSON body
python -m http_inspector.cli https://api.example.com/users -X POST --data '{"name": "Alice"}'

# POST reading body from a file
python -m http_inspector.cli https://api.example.com/users -X POST --data @payload.json

# Custom headers
python -m http_inspector.cli https://api.example.com/me -H "Authorization: Bearer <token>"

# Shape only (no sample records)
python -m http_inspector.cli https://api.example.com/users --shape-only

# Show all headers (not just the important ones)
python -m http_inspector.cli https://api.example.com/users --show-all-headers

# JSON output
python -m http_inspector.cli https://api.example.com/users --format json
```

**MCP usage:**
```
inspect_http(url="https://api.example.com/users")
inspect_http(url="https://api.example.com/users", max_array_items=3)
inspect_http(url="https://api.example.com/users", method="POST", data='{"name":"Alice"}')
inspect_http(url="https://api.example.com/users", shape_only=true)
inspect_http(url="https://api.example.com/users", show_all_headers=true)
```

**Exit codes:** `0` success · `1` network/request error (timeout, DNS, HTTP error) ·
`4` missing httpx dependency.

---

## Recommended Workflows

These sequences show how to chain the tools for common Claude Code tasks.

### Starting a new coding session

Orient yourself before touching any files:

```
1. git_repo_context()                    # ~300 tokens: branch, uncommitted changes, recent commits
2. smart_file_tree(depth=2)              # ~200 tokens: repo layout with sizes and ages
3. index_codebase(detail="low")          # ~500 tokens: module structure at a glance
```

Total: ~1,000 tokens to fully orient in an unfamiliar repo.

---

### Editing a specific file

Get everything needed to understand the file before touching it:

```
1. git_file_context(file_path="src/models/classifier.py")   # ~400 tokens
2. index_codebase(detail="high", focus="src/models")        # ~800 tokens
```

Total: ~1,200 tokens vs. reading the full file history manually.

---

### Debugging a failing test run

```
1. summarize_log(path="pytest_output.log", format_hint="pytest")  # ~200 tokens
2. git_file_context(file_path="<failing_module>")                 # ~400 tokens
```

Skip reading the raw pytest output (often 5,000+ tokens).

---

### Researching before implementing

When you have reference docs, papers, or spec URLs to consult:

```
1. fetch_url(url="https://...")          # per URL: ~500–2,000 tokens
2. extract_pdf_text(pdf_path="spec.pdf") # per doc: ~1,000–5,000 tokens
3. index_codebase(detail="normal")       # understand existing code: ~1,500 tokens
```

---

### Reviewing an ML training run

```
1. summarize_log(path="training.log")              # ~300 tokens: metrics + errors
2. git_file_context(file_path="train.py")          # ~400 tokens: recent changes
3. index_codebase(detail="high", focus="src/")     # ~1,000 tokens: full signatures
```

Total: ~1,700 tokens. Without these tools: reading the log (~30,000 tokens) +
reading source files (~10,000 tokens) = ~40,000 tokens.

---

### Exploring an unfamiliar URL or documentation site

```
1. fetch_url(url="https://docs.example.com/overview")
2. fetch_url(url="https://docs.example.com/api-reference")
3. fetch_url(url="https://docs.example.com/quickstart")
```

Each call strips navigation, headers, and boilerplate. Use `--batch urls.txt`
if you have a list of URLs to fetch in one command.

### Probing a live API endpoint

Use `http_inspector` to see what an endpoint actually returns before writing a client:

```
1. inspect_http(url="https://api.example.com/users")
   → shape: array[50] → {id: integer, name: string, email: string}
2. inspect_http(url="https://api.example.com/users/1")
   → shape: {id: integer, name: string, roles: array[string], address: {...}}
3. inspect_http(url="https://api.example.com/users", method="POST",
                data='{"name":"test"}',
                headers=["Authorization: Bearer <token>"])
   → 201 + {id: integer} shape
```

### Understanding an API before implementing a client

Get the shape of an API spec before writing code against it:

```
1. extract_api_spec(source="openapi.json")
   → Endpoint catalog (method, path, summary, tags)
2. extract_api_spec(source="openapi.json", tag="orders", detail=true)
   → Full parameter + response schema for all /orders endpoints
3. extract_api_spec(source="openapi.json", endpoint="/orders/{id}", method="GET", detail=true)
   → Exact schema for a single operation
```

For GraphQL:

```
1. extract_api_spec(source="schema.graphql")
   → Type index + Query/Mutation catalog
2. extract_api_spec(source="schema.graphql")
   → Then ask "show me the Pet type fields" with the index already in context
```

---

## Shared Utilities

### `shared/walker.py`

`codebase_indexer` and `smart_file_tree` share directory walking and exclusion
logic via `shared/walker.py`. If you modify the hard-exclude list or `.gitignore`
handling in one tool, apply the change in `shared/walker.py` and both tools pick it up.

### `shared/duration.py`

All tools that accept time windows import `parse_duration` from `shared/duration.py`.
This ensures a consistent duration string format across the suite:

| String | Meaning |
|---|---|
| `30m` | 30 minutes |
| `24h` | 24 hours |
| `7d` | 7 days (default for "recent") |
| `2w` | 2 weeks |
| `1mo` | 1 month (30 days) |
| `1y` | 1 year |

Used by: `--modified-after` (smart_file_tree), `--blame-window` (git_context),
`--cache-ttl` (url_fetcher).

### `.treeignore` / `.indexignore`

Both `codebase_indexer` and `smart_file_tree` respect a project-level ignore file
in the repo root. Use `.gitignore` syntax to exclude paths that aren't in
`.gitignore` but shouldn't be indexed or shown in the file tree:

```gitignore
# .treeignore / .indexignore
data/raw/
models/checkpoints/
notebooks/exploratory/
*.csv
*.parquet
```

### Output format flags

All tools support `--format markdown | json | text`. Use `json` when piping
output between tools or into other scripts.

---

## Testing

All tests are in `tests/`. Run from the project root:

```bash
python -m pytest tests/
```

Test-only dependencies (not in any tool's `requirements.txt`): `fpdf2` (PDF fixture
generation), `respx` (httpx mocking for `url_fetcher` — no real network calls are made).

---

## Adding a New Tool

1. Create `<tool_name>/` at the project root following an existing tool's structure
2. Implement `cli.py` with stdout for content, stderr for metadata
3. Add `requirements.txt`
4. If the tool walks directories: import from `shared/walker.py`
5. If the tool accepts time windows: import `parse_duration` from `shared/duration.py`
6. Add `mcp_tool.py` with the handler, then add a typed `@mcp.tool()` wrapper in
   `mcp_server.py` that delegates to it (the single `cli-tools` server picks it up;
   no `.mcp.json` change needed)
7. Add tests in `tests/test_<tool_name>.py`
8. Add an entry to this README under [Tool Reference](#tool-reference) and
   [Recommended Workflows](#recommended-workflows)

---

## Design Principles

**stdout is content, stderr is metadata.**
All tools write extracted content to stdout and progress/timing/warnings to stderr.
This makes output pipeable and predictable.

**Never load large files fully into memory.**
`log_summarizer` streams line-by-line via iterator (no `.readlines()`). `pdf_extractor`
streams pages. No tool calls `.read()` on a file without a size check first.

**Fail open on optional features.**
Optional dependencies (Playwright, easyocr) are never required. Tools degrade
gracefully and surface install instructions when a missing optional feature is requested.

**Parse structured formats, not human-readable output.**
`git_context` uses `--porcelain` formats. `log_summarizer` uses typed regex patterns
per format. `pdf_extractor` uses the `pdfplumber` AST, not text heuristics.
Human-readable output changes with locale and version; structured output does not.

**Tools are independent.**
No tool imports from another. They can be installed and used individually.
Shared logic lives in `shared/` — not in any single tool's package.

**Exit codes are meaningful.**
All tools use consistent exit codes:
- `0` — success (even if content was thin or warnings were raised)
- `1` — input/network/parse error
- `2` — blocked by policy (robots.txt, permissions)
- `3` — wrong content type for this tool
- `4` — optional dependency required but not installed
