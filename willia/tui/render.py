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
    background: str | None = None


@dataclass(frozen=True)
class Line:
    text: str
    style: str
    spans: tuple[Span, ...] = ()
    record_id: int | None = None
    record_kind: str | None = None
    source_text: str | None = None
    source_index: int | None = None


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
    """Wrap text while retaining the exact logical source line for yanking."""
    logical = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[Line] = []
    for source_index, source in enumerate(logical):
        for line in _wrap_runs((Span(source, style),), width):
            lines.append(Line(
                line.text, line.style, line.spans, source_text=source,
                source_index=source_index,
            ))
    return lines


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
    """One line, always: the arguments are clipped, not wrapped."""
    suffix = "" if elapsed_ms is None else f"  {elapsed_ms:.0f}ms"
    prefix = 2 + cell_width(name) + 1
    available = max(1, width - prefix - cell_width(suffix))
    shown = fit(_arguments(arguments), available, ellipsis="…", pad=False)
    text = f"→ {name} {shown}{suffix}"
    spans = (Span("→ ", "agent"), Span(name, "agent"),
             Span(" " + shown + suffix, "dim"))
    return [Line(text, "agent", spans)]


ECHO_LINES = 2


def _echo(text: str, width: int) -> list[Line]:
    logical = text.splitlines() or [""]
    lines: list[Line] = []
    for source_index, value in enumerate(logical[:ECHO_LINES]):
        lines.extend(Line(
            line.text, line.style, line.spans, source_text=value,
            source_index=source_index,
        ) for line in wrap(value, width, "dim"))
    if len(logical) > ECHO_LINES:
        remaining = "\n".join(logical[ECHO_LINES:])
        lines.extend(Line(
            line.text, line.style, line.spans, source_text=remaining,
            source_index=ECHO_LINES,
        ) for line in wrap(f"… {len(logical) - ECHO_LINES} more", width, "dim"))
    return lines


def record_lines(record: Any, width: int, *, show_notes: bool = False,
                 collapsed: bool = False) -> list[Line]:
    """One record's lines. ``show_notes`` includes imported memory; ``collapsed`` keeps one line."""
    kind = _field(record, "kind", "")
    text = _field(record, "text", "")
    record_id = _field(record, "i")

    def tagged(lines: list[Line]) -> list[Line]:
        return [Line(
            line.text, line.style, line.spans, record_id=record_id, record_kind=kind,
            source_text=line.source_text if line.source_text is not None else text,
            source_index=line.source_index,
        ) for line in lines]

    if kind == "note":
        if not show_notes:
            return []
        head = text.strip().splitlines()[0] if text.strip() else ""
        return tagged([Line(fit(f"note · {head}", width, ellipsis="…", pad=False), "dim")])
    if collapsed and kind in {"will", "user", "echo"}:
        head = text.strip().splitlines()[0] if text.strip() else ""
        return tagged([Line(
            fit(head, width, ellipsis="…", pad=False), "dim",
            source_text=head, source_index=0,
        )])
    if kind == "user":
        return tagged(wrap(text, width, "you"))
    if kind == "will":
        return tagged(wrap(text, width, "body"))
    if kind == "echo":
        return tagged(_echo(text, width))
    if kind == "work":
        if text.startswith("[") and "]" in text:
            end = text.index("]") + 1
            tag, body = text[:end], text[end:]
            shown = fit(body.lstrip(), max(1, width - cell_width(tag) - 1),
                        ellipsis="…", pad=False)
            spans = (Span(tag, "amber"), Span(" " + shown, "dim"))
            return tagged([Line(tag + " " + shown, "amber", spans)])
        return tagged([Line(fit(text, width, ellipsis="…", pad=False), "dim")])
    if kind == "tool":
        try:
            packet = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            packet = {}
        if isinstance(packet, dict) and isinstance(packet.get("name"), str):
            return tagged(_tool_line(packet["name"], packet.get("arguments"), width))
        return tagged(wrap("→ " + text, width, "dim"))
    return tagged(wrap(text, width, "body"))


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
                produced = _wrap_runs((
                    Span("│ ", "rule_strong"), Span(pending_text, "reason"),
                ), width)
                lines.extend(Line(
                    line.text, line.style, line.spans, record_kind="reasoning",
                    source_text=pending_text, source_index=0,
                ) for line in produced)
            else:
                produced = wrap(pending_text, width, "body")
                lines.extend(Line(
                    line.text, line.style, line.spans, record_kind="will",
                    source_text=line.source_text, source_index=line.source_index,
                ) for line in produced)
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
            produced = wrap(str(_field(event, "text", "")), width, "you")
            lines.extend(Line(
                line.text, line.style, line.spans, record_kind="user",
                source_text=line.source_text, source_index=line.source_index,
            ) for line in produced)
        elif event_name == "tool_call":
            produced = _tool_line(
                str(_field(event, "name", "tool")),
                _field(event, "arguments"), width,
                _field(event, "elapsed_ms"),
            )
            lines.extend(Line(
                line.text, line.style, line.spans, record_kind="tool",
                source_text=str(_field(event, "arguments", "")),
            ) for line in produced)
        elif event_name == "tool_result":
            produced = _echo(str(_field(event, "result", "")), width)
            lines.extend(Line(
                line.text, line.style, line.spans, record_kind="echo",
                source_text=line.source_text,
            ) for line in produced)
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
           show_notes: bool = False, collapsed_records=()) -> list[Line]:
    """Render durable records plus ephemeral stream events, without any I/O."""
    colours = palette(theme)
    width = max(1, width)
    lines: list[Line] = []
    previous_kind = None
    for record in records:
        if record is None:
            continue
        kind = _field(record, "kind", "")
        produced = record_lines(
            record, width, show_notes=show_notes,
            collapsed=_field(record, "i") in collapsed_records,
        )
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
