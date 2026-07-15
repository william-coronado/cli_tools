# Handover: cli-tools MCP server — field notes from a real session

**Source**: a single Claude Code session doing full-stack feature work on a Phaser.js +
FastAPI + SQLite game (`claude-code-game`). Not a synthetic benchmark — this is what one
agent actually reached for, command by command, over a long multi-phase session (frontend
art integration, a new backend-consuming dashboard screen, and writing deployment configs).

**Headline finding**: the `cli-tools` MCP server was available and loaded with instructions
the entire session, and **I never called a single tool from it.** Every operation that its own
description says it covers — repo structure, dependency manifests, HTTP inspection, log
files, git history — I did with raw `Bash` instead (`find`, `cat`, `curl`, `grep`, `sqlite3`,
`tail`). That's the most important data point here: not a bug report, a discoverability
report. Sections below explain why, with the actual commands as evidence.

---

## 1. Errors or difficulties encountered

**None functionally — because the server was never invoked.** I can't report execution bugs
I didn't hit. The real difficulty is upstream of execution: at no point during the session did
I pause and evaluate "should this be an MCP call instead of Bash?" Concretely:

- My own operating instructions (harness system prompt) hardcode a Bash-based git workflow
  for the commit ritual ("run `git status`/`git diff`/`git log` via Bash before every
  commit"). That instruction is specific enough to fully route around `git_repo_context` /
  `git_file_context` for the single most repeated git-adjacent task in the session (I made 5
  commits). If those tools are meant to replace ad hoc git inspection, they need a foothold
  inside that already-mandated workflow, not just a generic "prefer this over raw reads"
  instruction competing with a more specific one.
- For everything else, raw Bash commands were simply the first thing that came to mind and
  they worked, so there was never a failure that forced reconsideration. The server's
  instructions say "prefer these over raw reads when the input is **large or noisy**" — in
  the moment, most of my individual reads (a 6-line `requirements.txt`, a `find -maxdepth 3`
  listing) felt small enough to not trigger that threshold, even in aggregate they weren't.
  That threshold is judgment-based and I consistently judged in favor of Bash.
- The one genuinely painful stretch of the session — browser automation for visual
  verification (Playwright: installing browsers, writing six separate Python scripts,
  mis-computing click coordinates three times, handling `window.prompt` dialogs, reading
  screenshots one at a time) — has **no equivalent in cli-tools at all**, so there was no
  tool to reach for even if I'd wanted to. See §3.

## 2. Recommended enhancements to existing tools

Caveat: since none of these were actually exercised this session, these are inferred from
the tool descriptions plus the moments I *should* have reached for them but didn't — treat as
hypotheses to validate, not confirmed bugs.

- **`inspect_http`**: the description doesn't distinguish "large/paginated API response" from
  "single small JSON health check." I made ~10 raw `curl` calls this session
  (`GET /api/health`, `GET/POST/DELETE /api/profiles/*`, `GET /api/rewards/*`), and every
  response was under 200 bytes — using a wrapper tool for those would likely *cost* more
  tokens than it saved (tool-call framing overhead vs. a 20-byte JSON body). If `inspect_http`
  is meant to shine on large/streamed/paginated responses, say so explicitly in its
  description so an agent can make the size call without guessing. Right now the description
  reads like it wants to be used for all HTTP inspection uniformly.
- **`smart_file_tree`**: this is the clearest missed opportunity of the session — I ran
  `find /path/to/assets/kenney -maxdepth 3 -type d | sort` and several other `find`/`ls`
  combinations to map out an unfamiliar asset directory (7 Kenney.nl packs, deeply nested).
  That's exactly "repository structure" per the tool's own stated scope, and the raw `find`
  output was genuinely noisy (60+ lines). I'd guess the miss here is pure salience, not a
  judgment call — recommend the tool description lead with a concrete trigger phrase like
  "when you're about to run `find`/`ls -R` on an unfamiliar directory," since that's the
  literal Bash pattern it should be intercepting.
- **`inspect_dependencies`**: I ran `cat backend/requirements.txt` and
  `cat frontend/package.json` directly. Both files were small, so token savings would be
  marginal here — but if this tool also normalizes/cross-references versions (e.g., flags a
  frontend/backend version mismatch, or surfaces transitive deps from a lockfile), that's a
  value proposition raw `cat` can't match regardless of file size, and that capability isn't
  obvious from the one-line description in the server instructions. Consider surfacing what
  makes it more than "cat with formatting."
- **git tools generally**: not clear from the description alone whether `git_repo_context` /
  `git_file_context` are meant to replace the routine `git status`/`git diff --stat`/`git log`
  pre-commit ritual, or are for a different use case (e.g., understanding *why* a file looks
  the way it does, blame-style archaeology). If it's the latter, that's fine and explains why
  I never reached for it — commit hygiene checks aren't archaeology. Worth clarifying in the
  description so agents don't default to raw git out of habit when there's a real winner
  available for deep-history questions.

## 3. Recommended new tools (based on actual commands run this session)

Ranked by how much friction/token cost they'd have visibly saved, with the real command as
evidence for each:

1. **Browser automation / visual verification (highest value, biggest gap).** This was the
   single most expensive, error-prone part of the session. No cli-tools equivalent exists.
   I had to: discover Playwright wasn't installed in the obvious place, find it in an
   unrelated venv (`/home/william/.venv_cli_tools/...` — ironically adjacent to this very MCP
   server's own environment), download ~300MB of browser binaries, then hand-write six
   separate Python heredoc scripts doing `page.goto` → `page.mouse.click(x, y)` →
   `page.wait_for_timeout` → `page.screenshot`, get click coordinates wrong three separate
   times against a canvas-rendered (non-DOM) UI, and read each screenshot back in as an image
   one at a time to eyeball the result. A tool like
   `browser_verify(url, actions=[click(x,y)|click(text)|fill_dialog(...)], screenshot=true)`
   that returns one compact result (success/failure + a single annotated screenshot, or a
   structured list of console errors) would have collapsed maybe 15 tool calls and several
   hundred lines of throwaway Python into 2-3 calls. This is squarely "token-efficient
   pre-processor for a large/noisy raw source" (raw Playwright stdout/scripting boilerplate)
   even though it's not a *file* source — worth considering even if it's a scope stretch for
   this server.
2. **SQLite point-query / mutation tool.** I ran several raw
   `sqlite3 /tmp/reading-game-dev.db "select id, name, created_at from child_profiles;"` and
   `sqlite3 ... "delete from session_history where id=... and items_attempted=0;"` commands
   directly against a live app database (to inspect and clean up test data created during
   verification). The server's own instructions already list "SQLite" under tabular data — if
   `summarize_data` doesn't actually support arbitrary point queries/mutations against a
   `.db` file (as opposed to summarizing a static export), that's a real gap: summarizing a
   whole table isn't what I needed, running a specific `SELECT`/`DELETE` was. Worth either
   confirming `summarize_data` covers this and improving its discoverability, or adding a
   narrower `sqlite_query` tool.
3. **Image metadata inspection.** I shelled out to Python/PIL
   (`python3 -c "from PIL import Image; im = Image.open(f); print(im.size, im.mode)"`) three
   separate times to check PNG dimensions before doing 9-slice UI work (needed to know exact
   pixel dimensions to pick sane corner insets). A tiny `inspect_image(path) -> {width,
   height, mode, format}` tool would be a cheap, high-hit-rate addition for anyone doing
   frontend/asset work — this pattern will recur constantly in game/UI-adjacent sessions.
4. **Dev-server / port awareness (lower priority).** I ran `ps aux | grep -E "vite|uvicorn"`,
   `lsof -i :8000`, and `ss -ltnp | grep 8000` multiple times across the session to check
   whether background dev servers were still alive before trusting a `curl` health check. A
   `list_dev_servers()` or `check_port(8000)` tool is a nice-to-have, not a strong need — raw
   `ps`/`lsof` output was small and this is a fairly Claude-Code-specific workflow (background
   process bookkeeping) rather than a general "large/noisy source" problem, so I'd rank this
   below the three above.

---

## Appendix: raw commands this session that overlap cli-tools' stated scope

For triage — every command below is a candidate "this should have been an MCP call":

```
find /path/to/assets/kenney -maxdepth 3 -type d | sort          # -> smart_file_tree
find assets/kenney -iname "license*" -exec cat {} \;             # -> smart_file_tree / extract_document
cat backend/requirements.txt                                     # -> inspect_dependencies
cat frontend/package.json | grep -i phaser                       # -> inspect_dependencies
curl -s http://127.0.0.1:8000/api/health --max-time 3            # -> inspect_http (marginal value, tiny response)
curl -s http://127.0.0.1:8000/api/profiles | python3 -m json.tool # -> inspect_http
curl -s -X DELETE http://127.0.0.1:8000/api/profiles/<id>        # -> inspect_http
sqlite3 /tmp/reading-game-dev.db "select ... from child_profiles" # -> summarize_data (if it does point queries) / new sqlite tool
sqlite3 /tmp/reading-game-dev.db "delete from session_history..." # -> new sqlite tool (mutation, not just summary)
python3 -c "from PIL import Image; im = Image.open(f); print(im.size)"  # -> new inspect_image tool
tail -30 backend.log / frontend.log                               # -> summarize_log (marginal value, tiny logs)
git status --porcelain / git diff --stat / git log                # -> git_repo_context? (routed around by hardcoded commit workflow)
[6x Python/Playwright heredoc scripts for click+screenshot verification]  # -> no equivalent; biggest gap
```

## Suggested next step for the planning agent

Given the evidence, I'd prioritize investigating in this order:
1. Why `smart_file_tree` and `inspect_dependencies` didn't get reached for despite clean
   matches — likely a description/salience fix, cheap to test (re-run a similar session with
   more assertive tool descriptions and see if pickup improves).
2. Whether `summarize_data` already handles SQLite point queries; if not, scope a narrow
   `sqlite_query` tool.
3. Whether browser-automation/visual-verification is in scope for this server at all (it's a
   bigger lift and a different capability class than "summarize a file") — worth a
   go/no-go decision before investing design time.
