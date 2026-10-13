"""Native web search and page extraction tools."""

from __future__ import annotations

import json
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any

from .config import WebConfig


_BLOCK_TAGS = {
    "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5",
    "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
_IGNORED_TAGS = {"script", "style", "noscript", "template", "svg"}
_TRUNCATION_NOTE = "\n\n[truncated: head and tail preserved]\n\n"


def _error(message: object) -> str:
    return json.dumps({"error": str(message)}, ensure_ascii=False)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "li":
            self.parts.extend(("\n", "- "))
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())

    @property
    def text(self) -> str:
        lines = [re.sub(r"[ \t\f\v]+", " ", line).strip()
                 for line in "".join(self.parts).splitlines()]
        output: list[str] = []
        for line in lines:
            if line:
                output.append(line)
            elif output and output[-1]:
                output.append("")
        return "\n".join(output).strip()


def _bounded(content: str, char_limit: int) -> str:
    if len(content) <= char_limit:
        return content
    if char_limit <= len(_TRUNCATION_NOTE):
        return _TRUNCATION_NOTE.strip()
    kept = char_limit - len(_TRUNCATION_NOTE)
    head = (kept + 1) // 2
    tail = kept // 2
    ending = content[-tail:] if tail else ""
    return content[:head] + _TRUNCATION_NOTE + ending


def web_search(query: object, limit: object = None,
               config: WebConfig | None = None) -> str:
    """Search with DDGS and return the fixed JSON tool-result shape."""
    settings = config or WebConfig()
    if not isinstance(query, str) or not query.strip():
        return _error("query must be a nonempty string")
    count = settings.max_results if limit is None else limit
    if type(count) is not int or count < 1:
        return _error("limit must be a positive integer")
    count = min(count, 10)
    try:
        from ddgs import DDGS
    except ImportError as exc:
        return _error(f"web_search needs the ddgs package: {exc}")
    try:
        found = DDGS().text(query, max_results=count)
        results = []
        for item in list(found)[:count]:
            if not isinstance(item, dict):
                continue
            results.append({
                "title": str(item.get("title") or ""),
                "url": str(item.get("href") or item.get("url") or ""),
                "description": str(item.get("body") or item.get("description") or ""),
            })
        return json.dumps({"results": results}, ensure_ascii=False)
    except ImportError as exc:
        return _error(f"web_search needs the ddgs package: {exc}")
    except Exception as exc:
        return _error(exc)


def _charset(response: Any) -> str:
    headers = getattr(response, "headers", None)
    get_content_charset = getattr(headers, "get_content_charset", None)
    if callable(get_content_charset):
        return get_content_charset() or "utf-8"
    return "utf-8"


def _extract(url: str, char_limit: int) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "willia/0.0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        text = raw.decode(_charset(response), errors="replace")
    parser = _TextParser()
    parser.feed(text)
    parser.close()
    return {
        "url": url,
        "title": parser.title,
        "content": _bounded(parser.text, char_limit),
        "error": None,
    }


def web_extract(urls: object, char_limit: object = None,
                config: WebConfig | None = None) -> str:
    """Fetch each requested page independently and reduce its HTML to text."""
    settings = config or WebConfig()
    if not isinstance(urls, list):
        return _error("urls must be an array")
    if len(urls) > 5:
        return _error("urls must contain at most 5 entries")
    budget = settings.extract_char_limit if char_limit is None else char_limit
    if type(budget) is not int or budget < 1:
        return _error("char_limit must be a positive integer")
    results: list[dict[str, object]] = []
    for url in urls:
        if not isinstance(url, str) or not url:
            results.append({
                "url": url, "title": "", "content": None,
                "error": "url must be a nonempty string",
            })
            continue
        try:
            results.append(_extract(url, budget))
        except Exception as exc:
            results.append({
                "url": url, "title": "", "content": None, "error": str(exc),
            })
    return json.dumps({"results": results}, ensure_ascii=False)
