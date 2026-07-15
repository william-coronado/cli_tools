#!/usr/bin/env bash
# setup.sh — install all tool dependencies and verify system requirements
# Run from the project root with the target virtualenv already active.
set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}ok${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}warn${RESET} $*"; }
fail() { echo -e "  ${RED}fail${RESET} $*"; FAILED=$((FAILED + 1)); }

FAILED=0

# ── Locate project root ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "\n${BOLD}Claude Code Token-Saving Tools — Setup${RESET}"
echo "Project root: $SCRIPT_DIR"

# ── Python version ─────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Python${RESET}"
if ! command -v python3 &>/dev/null; then
    fail "python3 not found. Install Python 3.11+."
else
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
        fail "Python $PY_VER found; 3.11+ required."
    else
        ok "Python $PY_VER"
    fi
fi

# ── Virtualenv check ───────────────────────────────────────────────────────────
echo -e "\n${BOLD}Virtual environment${RESET}"
if [ -z "${VIRTUAL_ENV:-}" ]; then
    warn "No virtualenv active. Installing into the system/user environment."
    warn "To use a virtualenv: python3 -m venv .venv && source .venv/bin/activate"
else
    ok "Active: $VIRTUAL_ENV"
fi

# ── pip install ────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Installing Python dependencies${RESET}"
TOOLS=(pdf_extractor codebase_indexer smart_file_tree url_fetcher log_summarizer git_context data_summarizer dep_inspector notebook_extractor api_spec_extractor http_inspector doc_extractor inspect_image)
for tool in "${TOOLS[@]}"; do
    req="$tool/requirements.txt"
    if [ ! -f "$req" ]; then
        fail "$req not found"
        continue
    fi
    echo -n "  $tool ... "
    if python3 -m pip install --quiet -r "$req"; then
        echo -e "${GREEN}ok${RESET}"
    else
        echo -e "${RED}failed${RESET}"
        FAILED=$((FAILED + 1))
    fi
done

# MCP front door (mcp_server.py) — only needed if you register the suite with
# an MCP client such as Claude Code. Harmless to install regardless.
echo -n "  mcp_server (mcp) ... "
if python3 -m pip install --quiet -r requirements-mcp.txt; then
    echo -e "${GREEN}ok${RESET}"
else
    echo -e "${RED}failed${RESET}"
    FAILED=$((FAILED + 1))
fi

# ── System dependencies ────────────────────────────────────────────────────────
echo -e "\n${BOLD}System dependencies${RESET}"

# Git ≥ 2.11 (required by git_context)
if command -v git &>/dev/null; then
    GIT_VER=$(git --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
    GIT_MAJOR=$(echo "$GIT_VER" | cut -d. -f1)
    GIT_MINOR=$(echo "$GIT_VER" | cut -d. -f2)
    if [ "$GIT_MAJOR" -gt 2 ] || { [ "$GIT_MAJOR" -eq 2 ] && [ "$GIT_MINOR" -ge 11 ]; }; then
        ok "git $GIT_VER"
    else
        fail "git $GIT_VER found; 2.11+ required by git_context."
    fi
else
    fail "git not found. Install git 2.11+."
fi

# Tesseract (required by pdf_extractor OCR path)
if command -v tesseract &>/dev/null; then
    TESS_VER=$(tesseract --version 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?')
    ok "tesseract $TESS_VER  (pdf_extractor OCR)"
else
    warn "tesseract not found — pdf_extractor will work for text-layer PDFs but OCR fallback will fail."
    warn "  Ubuntu/Debian: sudo apt install tesseract-ocr"
    warn "  macOS:         brew install tesseract"
fi

# Poppler (pdfinfo / pdftoppm — required by pdf2image used in pdf_extractor OCR path)
if command -v pdftoppm &>/dev/null && command -v pdfinfo &>/dev/null; then
    POPPLER_VER=$(pdftoppm -v 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' || echo "unknown")
    ok "poppler $POPPLER_VER  (pdf_extractor OCR → pdf2image)"
else
    warn "poppler utilities not found — pdf_extractor OCR fallback will fail."
    warn "  Ubuntu/Debian: sudo apt install poppler-utils"
    warn "  macOS:         brew install poppler"
fi

# Playwright (optional — url_fetcher JS rendering)
if python3 -c "import playwright" &>/dev/null 2>&1; then
    ok "playwright  (url_fetcher JS rendering)"
else
    warn "playwright not installed (optional) — url_fetcher --js flag will be unavailable."
    warn "  pip install playwright && playwright install chromium"
fi

# easyocr (optional — pdf_extractor --ocr-backend easyocr)
if python3 -c "import easyocr" &>/dev/null 2>&1; then
    ok "easyocr  (pdf_extractor --ocr-backend easyocr)"
else
    warn "easyocr not installed (optional) — pdf_extractor --ocr-backend easyocr will be unavailable."
    warn "  pip install easyocr"
fi

# pandas / pyarrow / openpyxl (optional — data_summarizer extra formats)
if python3 -c "import pandas" &>/dev/null 2>&1; then
    ok "pandas  (data_summarizer richer CSV stats)"
else
    warn "pandas not installed (optional) — data_summarizer falls back to stdlib (fewer stats)."
    warn "  pip install pandas"
fi
if python3 -c "import pyarrow" &>/dev/null 2>&1; then
    ok "pyarrow  (data_summarizer .parquet support)"
else
    warn "pyarrow not installed (optional) — data_summarizer can't read .parquet."
    warn "  pip install pyarrow"
fi
if python3 -c "import openpyxl" &>/dev/null 2>&1; then
    ok "openpyxl  (data_summarizer .xlsx support)"
else
    warn "openpyxl not installed (optional) — data_summarizer can't read .xlsx."
    warn "  pip install openpyxl"
fi

# pyyaml (optional — dep_inspector pnpm-lock.yaml + api_spec_extractor YAML specs)
if python3 -c "import yaml" &>/dev/null 2>&1; then
    ok "pyyaml  (dep_inspector pnpm-lock.yaml; api_spec_extractor YAML specs)"
else
    warn "pyyaml not installed (optional) — dep_inspector can't parse pnpm-lock.yaml; api_spec_extractor can't read .yaml specs."
    warn "  pip install pyyaml"
fi

# graphql-core (optional — api_spec_extractor GraphQL SDL support)
if python3 -c "import graphql" &>/dev/null 2>&1; then
    ok "graphql-core  (api_spec_extractor GraphQL SDL support)"
else
    warn "graphql-core not installed (optional) — api_spec_extractor can't parse .graphql files."
    warn "  pip install graphql-core"
fi

# markitdown (doc_extractor; optionally enriches http_inspector HTML bodies
# and notebook_extractor HTML outputs via its markdownify dependency)
if python3 -c "import markitdown" &>/dev/null 2>&1; then
    ok "markitdown  (doc_extractor DOCX/PPTX/XLSX/EPUB/MSG; http_inspector HTML bodies)"
else
    warn "markitdown not installed — doc_extractor will exit 4; http_inspector shows raw HTML previews."
    warn "  pip install 'markitdown[docx,pptx,xlsx,outlook]'"
fi

# ── Smoke test: import each tool ───────────────────────────────────────────────
echo -e "\n${BOLD}Smoke tests${RESET}"
for tool in "${TOOLS[@]}"; do
    if python3 -c "import $tool" &>/dev/null 2>&1; then
        ok "import $tool"
    else
        fail "import $tool failed — check the pip install output above."
    fi
done

# ── Result ─────────────────────────────────────────────────────────────────────
echo ""
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}Setup complete.${RESET} All required dependencies are installed."
    echo ""
    echo "Verify individual tools:"
    for tool in "${TOOLS[@]}"; do
        echo "  python3 -m ${tool}.cli --help"
    done
else
    echo -e "${RED}${BOLD}Setup finished with $FAILED error(s).${RESET}"
    echo "Fix the issues above and re-run setup.sh."
    exit 1
fi
