from __future__ import annotations

import re
from urllib.parse import urljoin


class MarkdownRenderer:
    MARKDOWNIFY_OPTIONS = {
        "heading_style": "ATX",
        "bullets": "-",
        "strip": ["img", "figure"],
        "convert_links": True,
        "wrap": False,
    }

    def render(self, content_html: str, base_url: str) -> str:
        resolved = self._resolve_relative_urls(content_html, base_url)
        try:
            from markdownify import markdownify
            md = markdownify(resolved, **self.MARKDOWNIFY_OPTIONS)
        except ImportError:
            from bs4 import BeautifulSoup
            md = BeautifulSoup(resolved, "lxml").get_text(separator="\n")
        return self._clean_markdown(md)

    def render_without_links(self, content_html: str, base_url: str) -> str:
        opts = {**self.MARKDOWNIFY_OPTIONS, "convert_links": False, "strip": ["img", "figure", "a"]}
        resolved = self._resolve_relative_urls(content_html, base_url)
        try:
            from markdownify import markdownify
            md = markdownify(resolved, **opts)
        except ImportError:
            from bs4 import BeautifulSoup
            md = BeautifulSoup(resolved, "lxml").get_text(separator="\n")
        return self._clean_markdown(md)

    def _resolve_relative_urls(self, html: str, base_url: str) -> str:
        if not base_url:
            return html
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            for tag in soup.find_all(href=True):
                tag["href"] = urljoin(base_url, tag["href"])
            for tag in soup.find_all(src=True):
                tag["src"] = urljoin(base_url, tag["src"])
            return str(soup)
        except Exception:
            return html

    def _clean_markdown(self, md: str) -> str:
        # 1. Collapse 3+ blank lines to 2
        md = re.sub(r"\n{3,}", "\n\n", md)
        # 2. Strip trailing whitespace per line
        md = "\n".join(line.rstrip() for line in md.splitlines())
        # 3. Remove empty links
        md = re.sub(r"\[[ \t]*\]\([^)]*\)", "", md)
        # 4. Remove image markdown
        md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
        # 5. Fix headers missing space
        md = re.sub(r"^(#{1,6})([^# \n])", r"\1 \2", md, flags=re.MULTILINE)
        # 6. Remove repeated horizontal rules
        md = re.sub(r"(\n---\n){2,}", "\n---\n", md)
        # 7. Unescape unnecessary escapes outside code blocks
        md = _unescape_outside_code(md)
        # 8. Remove navigation link lists
        md = _strip_nav_link_lists(md)
        # 9. Trim
        return md.strip()


def _unescape_outside_code(md: str) -> str:
    """Remove backslash-escapes for ()[] outside fenced code blocks."""
    parts: list[str] = []
    in_code = False
    for line in md.splitlines(keepends=True):
        if line.startswith("```"):
            in_code = not in_code
        if not in_code:
            line = re.sub(r"\\([\(\)\[\]])", r"\1", line)
        parts.append(line)
    return "".join(parts)


def _strip_nav_link_lists(md: str) -> str:
    """Remove bullet-list blocks where every item is a bare short link."""
    lines = md.splitlines()
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^- \[", line):
            # Collect the whole list block
            block: list[str] = []
            j = i
            while j < len(lines) and (
                re.match(r"^- ", lines[j]) or (block and lines[j].startswith("  "))
            ):
                block.append(lines[j])
                j += 1
            # Check if all items are short bare links (< 5 words, link-only)
            nav_count = sum(
                1 for bl in block
                if re.match(r"^- \[[^\]]{0,40}\]\([^)]*\)\s*$", bl)
                and len(bl.split()) < 7
            )
            if block and nav_count == len(block):
                i = j  # skip the entire block
                continue
            result.extend(block)
            i = j
        else:
            result.append(line)
            i += 1
    return "\n".join(result)
