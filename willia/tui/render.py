"""Pure transcript layout for the terminal UI."""

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


def cell_width(text: str) -> int:
    width = 0
    for char in text:
        if char in "\r\n":
            continue
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def _wrap_spans(spans: Iterable[Span], width: int) -> list[Line]:
    width = max(1, width)
    rows: list[list[Span]] = [[]]
    cells = 0

    def append(char: str, style: str) -> None:
        nonlocal cells
        if rows[-1] and rows[-1][-1].style == style:
            previous = rows[-1][-1]
            rows[-1][-1] = Span(previous.text + char, style)
        else:
            rows[-1].append(Span(char, style))
        cells += cell_width(char)

    for span in spans:
        for char in span.text.replace("\r\n", "\n").replace("\r", "\n"):
            if char == "\n":
                rows.append([])
                cells = 0
                continue
            char_width = cell_width(char)
            if cells and cells + char_width > width:
                rows.append([])
                cells = 0
            append(char, span.style)
    result = []
    for row in rows:
        text = "".join(span.text for span in row)
        style = row[0].style if row else "body"
        result.append(Line(text, style, tuple(row)))
    return result


def wrap(text: str, width: int, style: str) -> list[Line]:
    return _wrap_spans((Span(text, style),), width)


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
    return _wrap_spans((
        Span("→ ", "agent"), Span(name, "agent"),
        Span(" " + _arguments(arguments) + suffix, "dim"),
    ), width)


def _echo(text: str, width: int) -> list[Line]:
    logical = text.splitlines() or [""]
    lines = []
    for value in logical[:3]:
        lines.extend(wrap(value, width, "dim"))
    if len(logical) > 3:
        lines.extend(wrap(f"… {len(logical) - 3} more", width, "dim"))
    return lines


def _record_lines(record: Any, width: int) -> list[Line]:
    kind = _field(record, "kind", "")
    text = _field(record, "text", "")
    if kind == "user":
        return wrap(text, width, "you")
    if kind == "will":
        return wrap(text, width, "body")
    if kind == "note":
        return wrap(text, width, "dim")
    if kind == "echo":
        return _echo(text, width)
    if kind == "work":
        if text.startswith("[") and "]" in text:
            end = text.index("]") + 1
            return _wrap_spans((
                Span(text[:end], "amber"), Span(text[end:], "dim"),
            ), width)
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


def _flight_lines(events: Iterable[Any], width: int) -> list[Line]:
    lines: list[Line] = []
    pending_kind = None
    pending_text = ""

    def flush() -> None:
        nonlocal pending_kind, pending_text
        if pending_text:
            if pending_kind == "reasoning":
                lines.extend(_wrap_spans((
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


def render(records, in_flight, width, height, theme) -> list[Line]:
    """Render durable records plus ephemeral stream events, without any I/O."""
    colours = palette(theme)
    lines: list[Line] = []
    for record in records:
        if record is not None:
            lines.extend(_record_lines(record, max(1, width)))
    lines.extend(_flight_lines(in_flight or (), max(1, width)))
    if any(line.style not in colours for line in lines):
        raise ValueError("Renderer produced an unknown style token")
    return lines if height is None or height < 0 else viewport(lines, height)
