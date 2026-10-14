"""Pure transcript layout for the terminal UI.

Everything here is a function of its arguments: records in, styled lines out. This is the hot path
(one call per changed frame, not one per keystroke), so wrapping builds style *runs* instead of one
object per character, and per-character width is memoised.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

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
    total = cell_width(text)
    if total <= width:
        return text + (" " * (width - total) if pad else "")
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


def _quoted(value: Any) -> str:
    """A compact, single-line quoted tool argument value."""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False)


def _arguments(value: Any) -> str:
    if isinstance(value, dict):
        return "  ".join(f"{key} {_quoted(item)}" for key, item in value.items())
    return f"arguments {_quoted(value)}"


def _tool_line(arguments: Any, width: int) -> list[Line]:
    """One content line, always: argument pairs are clipped, never wrapped."""
    shown = fit(_arguments(arguments), width, ellipsis="…", pad=False)
    return [Line(shown, "dim")]


CLIPPED_LINES = 3


def _clipped(text: str, width: int, style: str, *, report_path: str | None = None,
             limit: int = CLIPPED_LINES) -> list[Line]:
    """Wrap first, then bound physical rows and report the exact omitted count."""
    lines = wrap(text, width, style)
    if len(lines) <= limit:
        return lines
    omitted = len(lines) - limit
    suffix = "line" if omitted == 1 else "lines"
    trailer = f"… {omitted} more {suffix}"
    if report_path:
        trailer += f" - full report: {report_path}"
    hidden = "\n".join(line.source_text or "" for line in lines[limit:])
    return [*lines[:limit], Line(
        fit(trailer, width, ellipsis="…", pad=False), "dim",
        source_text=hidden, source_index=lines[limit].source_index,
    )]


def _reasoning(text: str, width: int) -> list[Line]:
    return _wrap_runs((
        Span("│ ", "rule_strong"), Span(text, "reason"),
    ), width)


def _block(label: str, label_style: str, content: list[Line], width: int) -> list[Line]:
    """Frame one record with a rule and an unpadded label."""
    return [
        Line("─" * width, "rule", source_index=-1),
        Line(label, label_style, source_index=-1),
        *content,
    ]


def _work_parts(text: str) -> tuple[str, str]:
    if text.startswith("[") and "]" in text:
        end = text.index("]") + 1
        return text[:end], text[end:].lstrip()
    return "", text


def record_lines(record: Any, width: int, *, show_notes: bool = False,
                 collapsed: bool = False, report_path: str | None = None) -> list[Line]:
    """One record's lines. ``show_notes`` includes imported memory; ``collapsed`` keeps one line."""
    kind = _field(record, "kind", "")
    text = _field(record, "text", "")
    record_id = _field(record, "i")

    def tagged(lines: list[Line]) -> list[Line]:
        return [Line(
            line.text, line.style, line.spans, record_id=record_id, record_kind=kind,
            source_text=(None if line.source_index == -1 else
                         line.source_text if line.source_text is not None else text),
            source_index=line.source_index,
        ) for line in lines]

    if kind == "note" and not show_notes:
        return []
    if collapsed and kind in {"will", "user", "echo"}:
        head = text.strip().splitlines()[0] if text.strip() else ""
        content = [Line(fit(head, width, ellipsis="…", pad=False), "dim",
                        source_text=head, source_index=0)]
        label = {"user": "ILLAN", "will": "WILLIA", "echo": "RESULT"}[kind]
        label_style = {"user": "you", "will": "body", "echo": "dim"}[kind]
        return tagged(_block(label, label_style, content, width))
    if kind == "user":
        return tagged(_block("ILLAN", "you", wrap(text, width, "you"), width))
    if kind == "will":
        return tagged(_block("WILLIA", "body", wrap(text, width, "body"), width))
    if kind == "echo":
        return tagged(_block("RESULT", "dim", _clipped(text, width, "dim"), width))
    if kind == "work":
        badge, body = _work_parts(text)
        label = f"WORK · {badge}" if badge else "WORK"
        content = _clipped(body, width, "dim", report_path=report_path)
        return tagged(_block(label, "amber", content, width))
    if kind == "tool":
        try:
            packet = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            packet = {}
        if isinstance(packet, dict) and isinstance(packet.get("name"), str):
            content = _tool_line(packet.get("arguments"), width)
            return tagged(_block(f"TOOL · {packet['name']}", "agent", content, width))
        content = [Line(fit(text, width, ellipsis="…", pad=False), "dim")]
        return tagged(_block("TOOL", "agent", content, width))
    if kind == "note":
        return tagged(_block("NOTE", "dim", wrap(text, width, "dim"), width))
    if kind == "reasoning":
        return tagged(_block("THINK", "reason", _reasoning(text, width), width))
    return tagged(_block(kind.upper() or "RECORD", "dim", wrap(text, width, "body"), width))


def _flight_lines(events: Iterable[Any], width: int) -> list[Line]:
    lines: list[Line] = []
    pending: list[tuple[str, str]] = []

    def flush() -> None:
        if not pending:
            return
        content: list[Line] = []
        for kind, value in pending:
            produced = _reasoning(value, width) if kind == "reasoning" else wrap(
                value, width, "body")
            content.extend(Line(
                line.text, line.style, line.spans,
                record_kind="reasoning" if kind == "reasoning" else "will",
                source_text=line.source_text if line.source_text is not None else value,
                source_index=line.source_index,
            ) for line in produced)
        framed = _block("WILLIA", "body", content, width)
        lines.extend(Line(
            line.text, line.style, line.spans, record_kind=line.record_kind or "will",
            source_text=line.source_text, source_index=line.source_index,
        ) for line in framed)
        pending.clear()

    for event in events or ():
        event_name = _field(event, "event", _field(event, "type", ""))
        if event_name == "delta":
            kind = _field(event, "kind", "content")
            value = str(_field(event, "text", ""))
            if pending and pending[-1][0] == kind:
                pending[-1] = (kind, pending[-1][1] + value)
            else:
                pending.append((kind, value))
            continue
        flush()
        if event_name == "user":
            value = str(_field(event, "text", ""))
            produced = _block("ILLAN", "you", wrap(value, width, "you"), width)
            lines.extend(Line(
                line.text, line.style, line.spans, record_kind="user",
                source_text=line.source_text, source_index=line.source_index,
            ) for line in produced)
        elif event_name == "tool_call":
            name = str(_field(event, "name", "tool"))
            produced = _block(
                f"TOOL · {name}", "agent",
                _tool_line(_field(event, "arguments"), width), width,
            )
            lines.extend(Line(
                line.text, line.style, line.spans, record_kind="tool",
                source_text=str(_field(event, "arguments", "")),
            ) for line in produced)
        elif event_name == "tool_result":
            produced = _block(
                "RESULT", "dim",
                _clipped(str(_field(event, "result", "")), width, "dim"), width,
            )
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
           show_notes: bool = False, collapsed_records=(),
           report_paths: Mapping[str, str] | None = None) -> list[Line]:
    """Render durable records plus ephemeral stream events, without any I/O."""
    colours = palette(theme)
    width = max(1, width)
    lines: list[Line] = []
    report_paths = report_paths or {}
    for record in records:
        if record is None:
            continue
        kind = _field(record, "kind", "")
        text = _field(record, "text", "")
        badge, _body = _work_parts(text) if kind == "work" else ("", "")
        produced = record_lines(
            record, width, show_notes=show_notes,
            collapsed=_field(record, "i") in collapsed_records,
            report_path=report_paths.get(badge[1:-1]) if badge else None,
        )
        if not produced:
            continue
        lines.extend(produced)
    lines.extend(_flight_lines(in_flight or (), width))
    if any(line.style not in colours for line in lines):
        raise ValueError("Renderer produced an unknown style token")
    return lines if height is None or height < 0 else viewport(lines, height)
