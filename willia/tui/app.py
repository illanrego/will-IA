"""Modal event loop and complete-frame composition for the TUI."""

from __future__ import annotations

import time
from enum import Enum

from .render import Line, Span, cell_width, render, viewport


class Mode(str, Enum):
    NORMAL = "NORMAL"
    INSERT = "INSERT"


HELP = ":q quit · :help show this line"
RAIL_WIDTH = 30

# A stream delta arrives per token; painting the whole frame for each one flickers.
_REDRAW_INTERVAL_S = 1.0 / 30.0


def _fit(text: str, width: int) -> str:
    result = ""
    for char in text:
        if cell_width(result + char) > width:
            break
        result += char
    return result + " " * max(0, width - cell_width(result))


class App:
    def __init__(self, chat, screen, *, rail_facts=(), rail_source=None,
                 theme="blue"):
        self.chat = chat
        self.screen = screen
        self.theme = theme
        self.mode = Mode.NORMAL
        self.scroll_offset = 0
        self.buffer = ""
        self.history: list[str] = []
        self.history_index: int | None = None
        self._history_draft = ""
        self.command: str | None = None
        self._pending_g = False
        self.in_flight: list[dict] = []
        self.records = []
        self.notice = ""
        self.rail_facts = list(rail_facts)
        self.rail_source = rail_source
        self.running = True
        self._last_draw: float | None = None
        if hasattr(self.screen, "on_resize"):
            self.screen.on_resize = self.redraw
        self._refresh()

    def _refresh(self) -> None:
        count = self.chat.log.count()
        self.records = self.chat.log.range(0, count - 1)
        if self.rail_source is not None:
            try:
                self.rail_facts = list(self.rail_source())
            except Exception:
                pass

    def __call__(self, event: str, **data) -> None:
        if event == "end":
            self.in_flight.clear()
            self._refresh()
            self.scroll_offset = 0
        elif event == "tool_result":
            for item in reversed(self.in_flight):
                if (item.get("event") == "tool_call"
                        and item.get("name") == data.get("name")
                        and "elapsed_ms" not in item):
                    item["elapsed_ms"] = data.get("elapsed_ms")
                    break
            self.in_flight.append({"event": event, **data})
        else:
            self.in_flight.append({"event": event, **data})
        if event == "end":
            self.redraw()
        else:
            self._redraw_soon()

    def _body_size(self) -> tuple[int, int, int]:
        width, height = self.screen.size()
        centre = max(1, width - RAIL_WIDTH)
        input_rows = 1 if self.mode == Mode.INSERT or self.command is not None else 0
        return width, max(0, height - 1 - input_rows), centre

    def _all_transcript_lines(self, centre: int) -> list[Line]:
        return render(self.records, self.in_flight, centre, -1, self.theme)

    def _max_offset(self) -> int:
        _width, body_height, centre = self._body_size()
        return max(0, len(self._all_transcript_lines(centre)) - body_height)

    def _move(self, amount: int) -> None:
        self.scroll_offset = max(
            0, min(self._max_offset(), self.scroll_offset + amount)
        )

    def _history(self, direction: int) -> None:
        if not self.history:
            return
        if self.history_index is None:
            if direction > 0:
                return
            self._history_draft = self.buffer
            self.history_index = len(self.history) - 1
        else:
            index = self.history_index + direction
            if index >= len(self.history):
                self.history_index = None
                self.buffer = self._history_draft
                return
            self.history_index = max(0, index)
        self.buffer = self.history[self.history_index]

    def _delete_word(self) -> None:
        end = len(self.buffer)
        while end and self.buffer[end - 1].isspace():
            end -= 1
        while end and not self.buffer[end - 1].isspace():
            end -= 1
        self.buffer = self.buffer[:end]

    def _send(self) -> None:
        text = self.buffer
        if not text:
            return
        self.history.append(text)
        self.history_index = None
        self.buffer = ""
        self.mode = Mode.NORMAL
        self.scroll_offset = 0
        self.in_flight = [{"event": "user", "text": text}]
        self.redraw()
        try:
            self.chat.turn([text], sink=self)
        except Exception as exc:
            self.notice = f"Turn error: {exc}"
        finally:
            if self.in_flight:
                self.in_flight.clear()
                self._refresh()
            self.redraw()

    def _command_key(self, key: str) -> None:
        if key == "ESC":
            self.command = None
        elif key == "BACKSPACE":
            self.command = self.command[:-1]
            if not self.command:
                self.command = None
        elif key == "ENTER":
            command, self.command = self.command, None
            if command == ":q":
                self.running = False
            elif command == ":help":
                self.notice = HELP
            else:
                self.notice = f"Unknown command: {command}"
        elif len(key) == 1 and key.isprintable():
            self.command += key

    def handle_key(self, key: str) -> bool:
        if key in {"CTRL_C", "EOF"}:
            self.running = False
            return False
        if self.command is not None:
            self._command_key(key)
            return self.running
        if self.mode == Mode.INSERT:
            if key == "ESC":
                self.mode = Mode.NORMAL
            elif key == "ENTER":
                self._send()
            elif key == "CTRL_J":
                self.buffer += "\n"
            elif key == "CTRL_U":
                self.buffer = ""
            elif key == "CTRL_W":
                self._delete_word()
            elif key == "BACKSPACE":
                self.buffer = self.buffer[:-1]
            elif key == "UP":
                self._history(-1)
            elif key == "DOWN":
                self._history(1)
            elif len(key) == 1 and key.isprintable():
                self.buffer += key
            return self.running

        if key in {"i", "ENTER"}:
            self.mode = Mode.INSERT
        elif key == ":":
            self.command = ":"
        elif key in {"j", "l", "DOWN", "RIGHT"}:
            self._move(-1)
        elif key in {"k", "h", "UP", "LEFT"}:
            self._move(1)
        elif key in {"CTRL_D", "PGDN"}:
            _width, body_height, _centre = self._body_size()
            self._move(-max(1, body_height // 2))
        elif key in {"CTRL_U", "PGUP"}:
            _width, body_height, _centre = self._body_size()
            self._move(max(1, body_height // 2))
        elif key in {"G", "END"}:
            self.scroll_offset = 0
        elif key in {"HOME"}:
            self.scroll_offset = self._max_offset()
        elif key == "g":
            if self._pending_g:
                self.scroll_offset = self._max_offset()
                self._pending_g = False
            else:
                self._pending_g = True
                return self.running
        else:
            self._pending_g = False
        return self.running

    def _rail_lines(self, height: int) -> list[Line]:
        lines = []
        for label, value, style in self.rail_facts:
            if label.startswith("#"):
                text = label[1:].upper()
                token = "dim"
            else:
                available = RAIL_WIDTH - 1
                label_width = min(9, available)
                value_width = max(0, available - label_width - 1)
                text = _fit(str(label), label_width) + " " + _fit(str(value), value_width)
                token = style
            lines.append(Line(_fit(text, RAIL_WIDTH - 1), token))
        return lines[:height]

    def _frame(self) -> list[Line]:
        width, height = self.screen.size()
        _full_width, body_height, centre = self._body_size()
        all_lines = self._all_transcript_lines(centre)
        transcript = viewport(all_lines, body_height, self.scroll_offset)
        rail = self._rail_lines(body_height)
        rows = []
        for index in range(body_height):
            left = rail[index] if index < len(rail) else Line(" " * (RAIL_WIDTH - 1), "panel")
            right = transcript[index] if index < len(transcript) else Line("", "body")
            left_spans = left.spans or (Span(left.text, left.style),)
            right_spans = right.spans or (Span(right.text, right.style),)
            spans = (*left_spans, Span("│", "rule"), *right_spans)
            rows.append(Line("".join(span.text for span in spans), "body", spans))

        if self.mode == Mode.INSERT or self.command is not None:
            prompt = self.command if self.command is not None else "> " + self.buffer.split("\n")[-1]
            rows.append(Line(_fit(prompt, width), "you"))
        status = self.notice or f"{self.mode.value} · transcript"
        rows.append(Line(_fit(status, width), "strong"))
        return rows[:height]

    def _redraw_soon(self) -> None:
        """Coalesce a burst of stream deltas into at most one paint per tick."""
        now = time.monotonic()
        if self._last_draw is None or now - self._last_draw >= _REDRAW_INTERVAL_S:
            self.redraw()

    def redraw(self) -> None:
        try:
            self.screen.draw(self._frame(), self.theme)
            self.screen.resized = False
            self._last_draw = time.monotonic()
        except Exception:
            pass

    def run(self) -> None:
        with self.screen:
            self.redraw()
            while self.running:
                key = self.screen.read_key()
                self.handle_key(key)
                self.redraw()
