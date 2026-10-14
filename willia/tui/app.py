"""Modal event loop and complete-frame composition for the TUI.

Three things here exist because the first version was slow, and each is load-bearing:

* the durable transcript is **rendered once and cached**, keyed by record count, width, theme and
  the note toggle - a frame slices that cache instead of re-wrapping the whole log;
* the rail reads the engine through a **non-blocking snapshot**: while the compaction drain holds
  the engine lock (a wave can run for seconds with model calls), the frame reuses the last facts
  and says ``compacting`` rather than waiting;
* the turn runs on a **worker thread** and reports through a queue, so the UI keeps reading keys
  and repainting while the model streams and while the post-turn pass runs.
"""

from __future__ import annotations

import queue
import threading
import time
from enum import Enum

from .render import Line, Span, fit, render, viewport


class Mode(str, Enum):
    NORMAL = "NORMAL"
    INSERT = "INSERT"


HELP = ":q quit · :notes show memory · :help this line"
RAIL_WIDTH = 30

# A stream delta arrives per token; painting the whole frame for each one flickers.
_REDRAW_INTERVAL_S = 1.0 / 30.0
# How often the rail's numbers may be re-read, and how much of the log the transcript wraps.
_RAIL_INTERVAL_S = 0.5
_RECORD_WINDOW = 300


class App:
    def __init__(self, chat, screen, *, rail_facts=(), rail_source=None,
                 theme="blue", show_notes=False):
        self.chat = chat
        self.screen = screen
        self.theme = theme
        self.show_notes = show_notes
        self.mode = Mode.NORMAL
        self.scroll_offset = 0
        self.buffer = ""
        self.history: list[str] = []
        self.history_index: int | None = None
        self._history_draft = ""
        self.command: str | None = None
        self._pending_g = False
        self.in_flight: list[dict] = []
        self.records: list = []
        self.notice = ""
        self.rail_facts = list(rail_facts)
        self.rail_source = rail_source
        self.running = True
        self.busy = False
        self.compacting = False
        self._turn: threading.Thread | None = None
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._last_draw: float | None = None
        self._last_rail = 0.0
        self._cache: list[Line] = []
        self._cache_key: tuple | None = None
        if hasattr(self.screen, "on_resize"):
            self.screen.on_resize = self.redraw
        self._refresh_records()
        # The first build waits (the rail must not open empty); every later one is a snapshot.
        self._refresh_rail(blocking=True)

    # ---------------------------------------------------------------- state refresh

    def _refresh_records(self) -> None:
        try:
            count = self.chat.log.count()
            self.records = self.chat.log.range(max(0, count - _RECORD_WINDOW), count - 1)
        except Exception:
            pass

    def _refresh_rail(self, *, blocking: bool = False) -> None:
        if self.rail_source is None:
            return
        self._last_rail = time.monotonic()
        try:
            facts = self.rail_source(blocking=blocking)
        except TypeError:
            facts = self.rail_source()
        except Exception:
            return
        if facts is None:
            self.compacting = True
            return
        self.compacting = False
        self.rail_facts = list(facts)

    def _rail_due(self) -> bool:
        return time.monotonic() - self._last_rail >= _RAIL_INTERVAL_S

    # ---------------------------------------------------------------- the turn

    def _sink(self, event: str, **data) -> None:
        """Called from the worker thread: enqueue only, never touch the screen."""
        self._events.put((event, data))

    def _run_turn(self, text: str) -> None:
        try:
            self.chat.turn([text], sink=self._sink)
        except Exception as exc:
            self._events.put(("notice", {"text": f"Turn error: {exc}"}))
        finally:
            self._events.put(("done", {}))

    def _drain_events(self) -> bool:
        applied = False
        while True:
            try:
                event, data = self._events.get_nowait()
            except queue.Empty:
                return applied
            applied = True
            if event == "done":
                self.busy = False
                self.in_flight.clear()
                self._refresh_records()
                self._refresh_rail(blocking=True)
                continue
            self.__call__(event, **data)

    def join_turn(self, timeout: float = 10.0) -> None:
        """Wait for the worker turn (tests and shutdown)."""
        if self._turn is not None:
            self._turn.join(timeout)
            self._turn = None

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
        self.busy = True
        self.notice = ""
        self.redraw()
        self._turn = threading.Thread(
            target=self._run_turn, args=(text,), name="willia-tui-turn", daemon=True)
        self._turn.start()

    # ---------------------------------------------------------------- event handling

    def __call__(self, event: str, **data) -> None:
        """Apply one turn event to the display state. UI thread only."""
        if event == "end":
            self.in_flight.clear()
            self._refresh_records()
            self.scroll_offset = 0
            self.redraw()
            return
        if event == "tool_result":
            for item in reversed(self.in_flight):
                if (item.get("event") == "tool_call"
                        and item.get("name") == data.get("name")
                        and "elapsed_ms" not in item):
                    item["elapsed_ms"] = data.get("elapsed_ms")
                    break
        self.in_flight.append({"event": event, **data})
        self._redraw_soon()

    # ---------------------------------------------------------------- geometry

    def _body_size(self) -> tuple[int, int, int]:
        width, height = self.screen.size()
        centre = max(1, width - RAIL_WIDTH)
        input_rows = 1 if self.mode == Mode.INSERT or self.command is not None else 0
        return width, max(0, height - 1 - input_rows), centre

    def _transcript(self, centre: int) -> list[Line]:
        """The durable transcript, wrapped once per change and then sliced."""
        key = (self.chat.log.count(), centre, self.theme, self.show_notes, len(self.records))
        if self._cache_key != key:
            self._cache = render(self.records, (), centre, -1, self.theme,
                                 show_notes=self.show_notes)
            self._cache_key = key
        return self._cache

    def _max_offset(self) -> int:
        _width, body_height, centre = self._body_size()
        return max(0, len(self._transcript(centre)) - body_height)

    def _move(self, amount: int) -> None:
        self.scroll_offset = max(0, min(self._max_offset(), self.scroll_offset + amount))

    # ---------------------------------------------------------------- insert editing

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

    # ---------------------------------------------------------------- commands and keys

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
            elif command == ":notes":
                self.show_notes = not self.show_notes
                self.notice = "memory shown" if self.show_notes else "memory hidden"
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
        elif key == "HOME":
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

    # ---------------------------------------------------------------- drawing

    def _rail_lines(self, height: int) -> list[Line]:
        lines: list[Line] = []
        for label, value, style in self.rail_facts:
            if label.startswith("#"):
                lines.append(Line(fit(label[1:].upper(), RAIL_WIDTH - 1), "dim"))
                continue
            available = RAIL_WIDTH - 2
            label_width = min(9, available)
            value_width = max(0, available - label_width - 1)
            text = (fit(str(label), label_width) + " "
                    + fit(str(value), value_width, pad=False))
            lines.append(Line(fit(text, RAIL_WIDTH - 1), style))
        return lines[:height]

    def _frame(self) -> list[Line]:
        width, height = self.screen.size()
        _full_width, body_height, centre = self._body_size()
        durable = self._transcript(centre)
        # The in-flight tail is rebuilt each frame: it is small and it is what is moving.
        flight = render((), self.in_flight, centre, -1, self.theme) if self.in_flight else []
        transcript = viewport(durable + flight, body_height, self.scroll_offset)
        rail = self._rail_lines(body_height)
        rows: list[Line] = []
        for index in range(body_height):
            left = rail[index] if index < len(rail) else Line(" " * (RAIL_WIDTH - 1), "panel")
            right = transcript[index] if index < len(transcript) else Line("", "body")
            left_spans = left.spans or (Span(left.text, left.style),)
            right_spans = right.spans or (Span(right.text, right.style),)
            spans = (*left_spans, Span("│", "rule"), *right_spans)
            rows.append(Line("".join(span.text for span in spans), "body", spans))

        if self.mode == Mode.INSERT or self.command is not None:
            prompt = (self.command if self.command is not None
                      else "> " + self.buffer.split("\n")[-1])
            rows.append(Line(fit(prompt, width, pad=True), "you"))
        rows.append(Line(fit(self._status(), width, pad=True), self._status_style()))
        return rows[:height]

    def _status(self) -> str:
        if self.notice:
            return self.notice
        state = "compacting" if self.compacting else ("streaming" if self.busy else "transcript")
        prefix = "MEMORY" if self.show_notes else ""
        return f"{self.mode.value} · {state}" + (f" · {prefix}" if prefix else "")

    def _status_style(self) -> str:
        if self.notice:
            return "strong"
        if self.busy or self.compacting:
            return "amber"
        return "dim"

    def _redraw_soon(self) -> None:
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

    # ---------------------------------------------------------------- main loop

    def run(self) -> None:
        with self.screen:
            self.redraw()
            try:
                while self.running:
                    if self._drain_events():
                        self._redraw_soon()
                    elif self._rail_due():
                        self._refresh_rail()
                        self._redraw_soon()
                    poll = getattr(self.screen, "poll_key", None)
                    key = poll(0.05) if poll is not None else self.screen.read_key()
                    if key is None:
                        continue
                    self.handle_key(key)
                    self.redraw()
            finally:
                self.running = False
                self.join_turn(5.0)
