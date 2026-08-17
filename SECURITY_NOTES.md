# Security-Motivated Dependency Floors

This file tracks `requirements.txt` minimum versions that exist specifically to
close a known CVE, so future dependency audits and cleanups don't accidentally
lower a floor back into vulnerable territory. Each entry is also commented
in-line at the relevant `requirements.txt` line.

When you bump a floor to fix a CVE, add a row here and a one-line comment next
to the pin in the affected `requirements.txt`. When a CVE-motivated floor is
later superseded by a newer CVE fix, update the row rather than adding a new one.

| Package | File | Floor | CVE | Issue | Notes |
|---|---|---|---|---|---|
| `pdfminer.six` | `pdf_extractor/requirements.txt` | `>=20251107` | CVE-2025-64512 | Insecure pickle deserialization → RCE via a crafted PDF | Transitive dep of `pdfplumber`; pinned directly since `pdfplumber`'s own floor doesn't guarantee a patched version. `pdf_extractor` processes untrusted/scanned PDFs, so this is high priority — do not remove. |
| `mcp` | `requirements-mcp.txt` | `>=1.29.0,<2.0.0` | CVE-2025-66416, CVE-2026-52870, CVE-2026-52869, CVE-2026-59950 | DNS-rebinding gap on HTTP/SSE transports; cross-session task leakage/cancel; session hijack via guessed session ID on SSE/Streamable HTTP; WebSocket transport missing Host/Origin validation | Low risk here — this repo's MCP server (`mcp_server.py`) runs stdio-only — but cheap to stay patched. Capped below 2.0.0: that release removes `mcp.server.fastmcp.FastMCP` (relocated/renamed to `mcp.server.mcpserver.MCPServer` with a different constructor), which `mcp_server.py` imports directly — upgrading past it would break the server. |
| `pygments` | `codebase_indexer/requirements.txt`, `smart_file_tree/requirements.txt` | `>=2.20.0` | CVE-2026-4539 | ReDoS | |
| `markdownify` | `url_fetcher/requirements.txt` | `>=0.14.1` | CVE-2025-46656 | DoS | |
