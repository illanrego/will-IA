"""Pure transcript layout for the terminal UI.

Everything here is a function of its arguments: records in, styled lines out. This is the hot path
(one call per changed frame, not one per keystroke), so wrapping builds style *runs* instead of one
object per character, and per-character width is memoised.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from .theme import palette


@dataclass(frozen=True)
class Span:
    text: str
    style: str


@dataclass(frozen=True)
class Line:
    text: str
    style: str
    spans: tuple[Span, ...] = ()


# Per-character width is asked for constantly and never changes.
_WIDTHS: dict[str, int] = {}


def char_width(char: str) -> int:
    width = _WIDTHS.get(char)
    if width is None:
        if char in "\r\n" or unicodedata.combining(char):
            width = 0
        elif unicodedata.east_asian_width(char) in {"W", "F"}:
            width = 2
        else:
            width = 1
        _WIDTHS[char] = width
    return width


def cell_width(text: str) -> int:
    return sum(char_width(char) for char in text)


def fit(text: str, width: int, *, ellipsis: str = "", pad: bool = True) -> str:
    """Truncate to ``width`` cells in one linear pass, optionally padding with spaces."""
    if width <= 0:
        return ""
    limit = width - cell_width(ellipsis) if ellipsis else width
    limit = max(0, limit)
    used = 0
    end = 0
    for index, char in enumerate(text):
        size = char_width(char)
        if used + size > limit:
            break
        used += size
        end = index + 1
    result = text[:end] + (ellipsis if end < len(text) else "")
    if not pad:
        return result
    return result + " " * max(0, width - cell_width(result))


def _wrap_runs(spans: Iterable[Span], width: int) -> list[Line]:
    """Wrap styled runs to ``width`` cells, merging same-style neighbours per row."""
    width = max(1, width)
    rows: list[list[list[str]]] = [[]]           # rows -> runs -> [style, chars]
    cells = 0

    def add(text: str, style: str) -> None:
        if text:
            rows[-1].append([style, text])

    for span in spans:
        chunk = ""
        for char in span.text.replace("\r\n", "\n").replace("\r", "\n"):
            if char == "\n":
                add(chunk, span.style)
                chunk = ""
                rows.append([])
                cells = 0
                continue
            size = char_width(char)
            if cells and cells + size > width:
                add(chunk, span.style)
                chunk = ""
                rows.append([])
                cells = 0
            chunk += char
            cells += size
        add(chunk, span.style)

    lines: list[Line] = []
    for row in rows:
        merged: list[Span] = []
        for style, text in row:
            if merged and merged[-1].style == style:
                merged[-1] = Span(merged[-1].text + text, style)
            else:
                merged.append(Span(text, style))
        lines.append(Line(
            "".join(span.text for span in merged),
            merged[0].style if merged else "body",
            tuple(merged),
        ))
    return lines


def wrap(text: str, width: int, style: str) -> list[Line]:
    return _wrap_runs((Span(text, style),), width)


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _arguments(value: Any) -> str:
    if isinstance(value, str):
        return value.replace("\r", "\\r").replace("\n", "\\n")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _tool_line(name: str, arguments: Any, width: int,
               elapsed_ms: float | None = None) -> list[Line]:
    suffix = "" if elapsed_ms is None else f"  {elapsed_ms:.0f}ms"
    return _wrap_runs((
        Span("→ ", "agent"), Span(name, "agent"),
        Span(" " + _arguments(arguments) + suffix, "dim"),
    ), width)


ECHO_LINES = 2


def _echo(text: str, width: int) -> list[Line]:
    logical = text.splitlines() or [""]
    lines: list[Line] = []
    for value in logical[:ECHO_LINES]:
        lines.extend(wrap(value, width, "dim"))
    if len(logical) > ECHO_LINES:
        lines.extend(wrap(f"… {len(logical) - ECHO_LINES} more", width, "dim"))
    return lines


def record_lines(record: Any, width: int, *, show_notes: bool = False,
                 collapsed: bool = False) -> list[Line]:
    """One record's lines. ``show_notes`` includes imported memory; ``collapsed`` keeps one line."""
    kind = _field(record, "kind", "")
    text = _field(record, "text", "")
    if kind == "note":
        if not show_notes:
            return []
        head = text.strip().splitlines()[0] if text.strip() else ""
        return [Line(fit(f"note · {head}", width, ellipsis="…", pad=False), "dim")]
    if collapsed and kind in {"will", "user", "echo"}:
        head = text.strip().splitlines()[0] if text.strip() else ""
        return [Line(fit(head, width, ellipsis="…", pad=False), "dim")]
    if kind == "user":
        return wrap(text, width, "you")
    if kind == "will":
        return wrap(text, width, "body")
    if kind == "echo":
        return _echo(text, width)
    if kind == "work":
        if text.startswith("[") and "]" in text:
            end = text.index("]") + 1
            return _wrap_runs((Span(text[:end], "amber"), Span(text[end:], "dim")), width)
        return wrap(text, width, "dim")
    if kind == "tool":
        try:
            packet = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            packet = {}
        if isinstance(packet, dict) and isinstance(packet.get("name"), str):
            return _tool_line(packet["name"], packet.get("arguments"), width)
        return wrap("→ " + text, width, "dim")
    return wrap(text, width, "body")


# A blank line separates conversation blocks; tool traffic stays tight under its call.
_SPACED = {"user", "will", "work"}


def _flight_lines(events: Iterable[Any], width: int) -> list[Line]:
    lines: list[Line] = []
    pending_kind = None
    pending_text = ""

    def flush() -> None:
        nonlocal pending_kind, pending_text
        if pending_text:
            if pending_kind == "reasoning":
                lines.extend(_wrap_runs((
                    Span("│ ", "rule_strong"), Span(pending_text, "reason"),
                ), width))
            else:
                lines.extend(wrap(pending_text, width, "body"))
        pending_kind = None
        pending_text = ""

    for event in events or ():
        event_name = _field(event, "event", _field(event, "type", ""))
        if event_name == "delta":
            kind = _field(event, "kind", "content")
            if pending_kind not in {None, kind}:
                flush()
            pending_kind = kind
            pending_text += str(_field(event, "text", ""))
            continue
        flush()
        if event_name == "user":
            lines.extend(wrap(str(_field(event, "text", "")), width, "you"))
        elif event_name == "tool_call":
            lines.extend(_tool_line(
                str(_field(event, "name", "tool")),
                _field(event, "arguments"), width,
                _field(event, "elapsed_ms"),
            ))
        elif event_name == "tool_result":
            lines.extend(_echo(str(_field(event, "result", "")), width))
        elif event_name == "notice":
            lines.extend(wrap(str(_field(event, "text", "")), width, "red"))
    flush()
    return lines


def viewport(lines: list[Line], height: int, offset: int = 0) -> list[Line]:
    """Select a bottom-anchored page; offset zero means the newest line."""
    if height <= 0:
        return []
    offset = max(0, min(offset, max(0, len(lines) - height)))
    end = max(0, len(lines) - offset)
    return lines[max(0, end - height):end]


def render(records, in_flight, width, height, theme, *,
           show_notes: bool = False) -> list[Line]:
    """Render durable records plus ephemeral stream events, without any I/O."""
    colours = palette(theme)
    width = max(1, width)
    lines: list[Line] = []
    previous_kind = None
    for record in records:
        if record is None:
            continue
        kind = _field(record, "kind", "")
        produced = record_lines(record, width, show_notes=show_notes)
        if not produced:
            continue
        if kind != previous_kind and previous_kind in _SPACED and kind in _SPACED:
            lines.append(Line("", "body"))
        lines.extend(produced)
        previous_kind = kind
    lines.extend(_flight_lines(in_flight or (), width))
    if any(line.style not in colours for line in lines):
        raise ValueError("Renderer produced an unknown style token")
    return lines if height is None or height < 0 else viewport(lines, height)
