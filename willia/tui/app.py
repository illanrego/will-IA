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

import json
import logging
from pathlib import Path
import queue
import re
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from enum import Enum

from .. import jobs, usage
from .hints import HINTS
from .render import Line, Span, cell_width, fit, render, viewport, wrap
from .theme import PALETTES


log = logging.getLogger(__name__)


class Mode(str, Enum):
    NORMAL = "NORMAL"
    INSERT = "INSERT"


class Pane(str, Enum):
    TRANSCRIPT = "transcript"
    RAIL = "rail"


HELP = ":view · :tree · :status · :usage · :help"
RAIL_WIDTH = 30

COLON_COMMANDS = (
    ":help", ":notes", ":q", ":status", ":theme", ":tree", ":usage", ":view",
)
INSPECTION_COMMANDS = {":view", ":tree", ":status", ":usage"}

HELP_KEYS = (
    "INSERT",
    "i compose · Enter send · Ctrl-j newline · Ctrl-u clear · Ctrl-w delete word",
    "Up/Down history · Esc normal mode",
    "",
    "NORMAL",
    "h j k l move · Ctrl-d/Ctrl-u half page · gg/G oldest/newest · n/N matches",
    "Tab or Ctrl-w h/j/k/l switch/move panes · Enter/Esc fold/unfold · Ctrl-b rail",
    "",
    "YANK",
    "y focused line · Y whole record · v … y visual range",
    "",
    "SEARCH / in the transcript",
    "COMMAND :view · :tree · :status · :usage · :notes · :help",
    ":theme blue|green|mixed · :q",
    "PANEL Esc/q close · j/k scroll · Ctrl-d/Ctrl-u page · g/G jump",
)

# A stream delta arrives per token; painting the whole frame for each one flickers.
_REDRAW_INTERVAL_S = 1.0 / 30.0
# How often the rail's numbers may be re-read, and how much of the log the transcript wraps.
_RAIL_INTERVAL_S = 0.5
_RECORD_WINDOW = 300


class App:
    def __init__(self, chat, screen, *, rail_facts=(), rail_source=None,
                 usage_source=None, theme="blue", show_notes=False):
        self.chat = chat
        self.screen = screen
        self.theme = theme
        self.show_notes = show_notes
        self.mode = Mode.NORMAL
        self.focus = Pane.TRANSCRIPT
        self.scroll_offset = 0
        self.transcript_cursor = 0
        self.buffer = ""
        self.caret = 0
        self.history: list[str] = []
        self.history_index: int | None = None
        self._history_draft = ""
        self.command: str | None = None
        self._pending_g = False
        self._pending_ctrl_w = False
        self.in_flight: list[dict] = []
        self.records: list = []
        self.notice = ""
        self._notice_until = 0.0
        self.rail_facts = list(rail_facts)
        self.rail_source = rail_source
        self.usage_source = usage_source
        self.running = True
        self.busy = False
        self.compacting = False
        self.rail_visible = True
        self.rail_index = 0
        self.collapsed_groups: set[str] = set()
        self.collapsed_records: set[int] = set()
        self.visual_anchor: int | None = None
        self.help_open = False
        self.help_scroll = 0
        self.panel_name: str | None = None
        self._panel_lines: list[str] = []
        self._panel_position: tuple[int, int, int | None] | None = None
        self._usage_local_lines: list[str] = []
        self._usage_state_seen: object = None
        self._busy_samples = 0
        self._pending_draw = False
        self._frame_key: tuple | None = None
        self.draw_error = ""
        self._turn: threading.Thread | None = None
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._last_draw: float | None = None
        self._last_rail = 0.0
        self._cache: list[Line] = []
        self._cache_key: tuple | None = None
        self._report_paths: dict[str, str] = {}
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
            report_paths: dict[str, str] = {}
            for record in self.records:
                kind = (record.get("kind") if isinstance(record, dict)
                        else getattr(record, "kind", ""))
                value = (record.get("text", "") if isinstance(record, dict)
                         else getattr(record, "text", ""))
                if kind != "echo":
                    continue
                try:
                    packet = json.loads(value)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(packet, dict):
                    continue
                name, path = packet.get("name"), packet.get("report_path")
                if isinstance(name, str) and isinstance(path, str) and Path(path).is_file():
                    report_paths[name] = path
            self._report_paths = report_paths
        except Exception:
            pass

    def _refresh_rail(self, *, blocking: bool = False) -> bool:
        """Re-read the rail; True when the numbers changed, so an idle frame writes nothing."""
        if self.rail_source is None:
            return False
        self._last_rail = time.monotonic()
        try:
            facts = self.rail_source(blocking=blocking)
        except TypeError:
            facts = self.rail_source()
        except Exception:
            return False
        if facts is None:
            self._busy_samples += 1
            # Hysteresis: an engine that frees and retakes the lock between samples must not make
            # the status line flap, because every flap costs a repaint.
            if self._busy_samples >= 2 and not self.compacting:
                self.compacting = True
                return True
            return False
        self._busy_samples = 0
        if self.compacting:
            self.compacting = False
            return True
        selected = self._selected_rail_identity()
        changed = list(facts) != self.rail_facts
        self.rail_facts = list(facts)
        self._restore_rail_selection(selected)
        return changed

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
        self.caret = 0
        self.mode = Mode.NORMAL
        self.scroll_offset = 0
        self.transcript_cursor = 0
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
            self.transcript_cursor = 0
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

    def _rail_width(self) -> int:
        return RAIL_WIDTH if self.rail_visible else 0

    def _body_size(self) -> tuple[int, int, int]:
        width, height = self.screen.size()
        centre = max(1, width - self._rail_width())
        field_rows = len(self._input_field_lines(centre, max(0, height - 1)))
        return width, max(0, height - 1 - field_rows), centre

    def _transcript(self, centre: int) -> list[Line]:
        """The durable transcript, wrapped once per change and then sliced."""
        key = (self.chat.log.count(), centre, self.theme, self.show_notes, len(self.records),
               frozenset(self.collapsed_records), tuple(sorted(self._report_paths.items())))
        if self._cache_key != key:
            self._cache = render(self.records, (), centre, -1, self.theme,
                                 show_notes=self.show_notes,
                                 collapsed_records=self.collapsed_records,
                                 report_paths=self._report_paths)
            self._cache_key = key
        return self._cache

    def _max_offset(self) -> int:
        _width, body_height, centre = self._body_size()
        transcript_height = max(0, body_height - 2)  # 005's top and bottom stage padding
        return max(0, len(self._transcript(centre)) - transcript_height)

    def _move(self, amount: int) -> None:
        lines = self._all_transcript_lines()
        self.transcript_cursor = max(
            0, min(max(0, len(lines) - 1), self.transcript_cursor + amount))
        self.scroll_offset = max(
            0, min(self._max_offset(), self.scroll_offset + amount))

    def _all_transcript_lines(self) -> list[Line]:
        _width, _body_height, centre = self._body_size()
        durable = self._transcript(centre)
        flight = render((), self.in_flight, centre, -1, self.theme) if self.in_flight else []
        return durable + flight

    def _focused_transcript_line(self) -> Line | None:
        lines = self._all_transcript_lines()
        if not lines:
            return None
        return lines[max(0, len(lines) - 1 - min(self.transcript_cursor, len(lines) - 1))]

    def _focused_transcript_index(self) -> int | None:
        lines = self._all_transcript_lines()
        if not lines:
            return None
        return max(0, len(lines) - 1 - min(self.transcript_cursor, len(lines) - 1))

    def _fold_transcript(self, collapsed: bool) -> None:
        line = self._focused_transcript_line()
        if line is None or line.record_id is None:
            return
        record_id = line.record_id
        if collapsed:
            self.collapsed_records.add(record_id)
        else:
            self.collapsed_records.discard(record_id)
        self._cache_key = None
        lines = self._all_transcript_lines()
        positions = [index for index, item in enumerate(lines) if item.record_id == record_id]
        if positions:
            self.transcript_cursor = max(0, len(lines) - 1 - positions[-1])
            self.scroll_offset = min(self._max_offset(), self.transcript_cursor)

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
                self.caret = len(self.buffer)
                return
            self.history_index = max(0, index)
        self.buffer = self.history[self.history_index]
        self.caret = len(self.buffer)

    def _delete_word(self) -> None:
        caret = max(0, min(self.caret, len(self.buffer)))
        start = caret
        while start and self.buffer[start - 1].isspace():
            start -= 1
        while start and not self.buffer[start - 1].isspace():
            start -= 1
        self.buffer = self.buffer[:start] + self.buffer[caret:]
        self.caret = start

    def _insert(self, text: str) -> None:
        caret = max(0, min(self.caret, len(self.buffer)))
        self.buffer = self.buffer[:caret] + text + self.buffer[caret:]
        self.caret = caret + len(text)

    # ---------------------------------------------------------------- commands and keys

    def _set_notice(self, text: str, seconds: float = 1.5) -> None:
        self.notice = text
        self._notice_until = time.monotonic() + seconds

    def _notice_expired(self) -> bool:
        if self.notice and self._notice_until and time.monotonic() >= self._notice_until:
            self.notice = ""
            self._notice_until = 0.0
            return True
        return False

    @staticmethod
    def _record_text(record) -> str:
        return str(record.get("text", "") if isinstance(record, dict)
                   else getattr(record, "text", ""))

    def _whole_record_text(self, record_id: int | None) -> str | None:
        if record_id is None:
            return None
        for record in self.records:
            current_id = (record.get("i") if isinstance(record, dict)
                          else getattr(record, "i", None))
            if current_id == record_id:
                return self._record_text(record)
        return None

    def _copy(self, text: str | None) -> None:
        if text is None:
            return
        try:
            copier = getattr(self.screen, "copy", None)
            if callable(copier):
                copier(text)
        except Exception:
            pass
        self._set_notice(f"yanked {len(text.encode('utf-8'))} bytes")

    def _visual_text(self) -> str | None:
        current = self._focused_transcript_index()
        if self.visual_anchor is None or current is None:
            return None
        lines = self._all_transcript_lines()
        lo, hi = sorted((self.visual_anchor, current))
        selected: list[str] = []
        previous = object()
        for line in lines[lo:hi + 1]:
            if line.sources:
                for source in line.sources:
                    identity = (source.record_id, source.index, source.text)
                    if identity == previous:
                        continue
                    selected.append((source.joiner if selected else "") + source.text)
                    previous = identity
                continue
            if line.record_id is None or line.source_text is None:
                continue
            identity = (line.record_id, line.source_index, line.source_text)
            if identity == previous:
                continue
            selected.append(("\n" if selected else "") + line.source_text)
            previous = identity
        return "".join(selected)

    def _yank(self, whole: bool = False) -> None:
        line = self._focused_transcript_line()
        if line is None or line.record_id is None:
            return
        if self.visual_anchor is not None:
            text = self._visual_text()
            self.visual_anchor = None
        elif whole:
            text = self._whole_record_text(line.record_id)
        else:
            if line.sources:
                chunks = []
                previous = object()
                for source in line.sources:
                    identity = (source.record_id, source.index, source.text)
                    if identity == previous:
                        continue
                    chunks.append((source.joiner if chunks else "") + source.text)
                    previous = identity
                text = "".join(chunks)
            else:
                text = line.source_text
        self._copy(text)

    def _help_content(self, width: int | None = None) -> list[str]:
        raw = ["WILLIA HELP", "", *HELP_KEYS, "", "RECORDS"]
        for kind in ("user", "will", "reasoning", "tool", "echo", "work", "note"):
            raw.append(f"{kind:<10} {HINTS[kind]}")
        return self._wrap_panel_lines(raw, width)

    def _wrap_panel_lines(self, raw: list[str], width: int | None = None) -> list[str]:
        if width is None:
            screen_width, _height = self.screen.size()
            width = max(1, min(80, screen_width - 4) - 2)
        lines: list[str] = []
        for value in raw:
            lines.extend(line.text for line in wrap(value, width, "body"))
        return lines

    @staticmethod
    def _coverage(lines) -> tuple[str, list[str]]:
        ranges = [
            (line.i << line.l, ((line.i + 1) << line.l) - 1)
            for line in lines
        ]
        if not ranges:
            return "none", []
        whole = f"{ranges[0][0]}-{ranges[-1][1]}"
        pointed = [str(start) if start == end else f"{start}-{end}" for start, end in ranges]
        return whole, pointed

    def _with_engine_snapshot(self, title: str, builder) -> list[str]:
        """Run one read-only engine snapshot, or report its busy state immediately."""
        try:
            engine_try = getattr(self.chat, "engine_try", None)
            manager = engine_try() if callable(engine_try) else self.chat._engine()
            with manager as taken:
                if taken is False:
                    return [title, "", "compacting"]
                return builder()
        except Exception as exc:
            return [title, "", f"unavailable ({type(exc).__name__}: {exc})"]

    def _view_inspection(self) -> list[str]:
        def build() -> list[str]:
            text = self.chat.view.render()
            view_lines = self.chat.view.lines()
            coverage, _pointed = self._coverage(view_lines)
            state = "settled" if self.chat.view.settled() else "building"
            header = (
                f"WILLIA VIEW · {len(text.encode('utf-8')):,} B · "
                f"records {coverage} · {state}"
            )
            return [header, "", *text.splitlines()]

        return self._with_engine_snapshot("WILLIA VIEW", build)

    def _tree_inspection(self) -> list[str]:
        def build() -> list[str]:
            nodes = self.chat.tree.nodes()
            levels = Counter(level for level, _index in nodes)
            biggest = max(levels.values(), default=0)
            count_width = max((len(str(count)) for count in levels.values()), default=1)
            raw = ["WILLIA TREE", ""]
            for level in sorted(levels):
                count = levels[level]
                filled = max(1, round(12 * count / biggest)) if count and biggest else 0
                bar = "█" * filled + " " * (12 - filled)
                raw.append(f"l{level:<3} {bar} {count:>{count_width}}")
            raw.append(f"nodes {sum(levels.values())}")
            view_lines = self.chat.view.lines()
            raw.extend(["", "ROOTS"])
            if view_lines:
                for line in view_lines:
                    start, end = line.i << line.l, ((line.i + 1) << line.l) - 1
                    records = str(start) if start == end else f"{start}-{end}"
                    raw.append(f"l{line.l}:{line.i} · records {records} · {line.size:,} B")
            else:
                raw.append("none")
            coverage, pointed = self._coverage(view_lines)
            unbuilt = sum(
                self.chat.tree.get(line.l, line.i) is None for line in view_lines
            )
            settled = self.chat.view.settled()
            raw.extend([
                "", "COVERAGE", f"records {coverage}",
                "points " + (", ".join(pointed) if pointed else "none"),
                ("settled" if settled else "building") + f" · {unbuilt} unbuilt",
            ])
            return raw

        return self._with_engine_snapshot("WILLIA TREE", build)

    def _record_kinds(self) -> tuple[int, Counter]:
        count = self.chat.log.count()
        if hasattr(self.chat.log, "get"):
            records = (self.chat.log.get(index) for index in range(count))
        else:
            records = iter(self.chat.log.range(0, count - 1))
        kinds: Counter = Counter()
        for record in records:
            if record is None:
                kinds["refused"] += 1
                continue
            kind = record.get("kind") if isinstance(record, dict) else getattr(record, "kind", "")
            kinds[str(kind or "unknown")] += 1
        return count, kinds

    def _compactor_state(self, *, settled: bool, queued: int) -> str:
        drain = getattr(self.chat, "_drain", None)
        work_remains = bool(queued) or not settled
        if drain is not None and drain.is_alive():
            return "summarizing"
        if getattr(self.chat, "_stuck_reported", False) and work_remains:
            return "stuck"
        return "queued" if work_remains else "idle"

    def _jobs_line(self) -> str:
        try:
            return jobs.status_line(
                self.chat, list(getattr(self.chat, "_startup_orphans", ())))
        except Exception:
            return "Jobs: unavailable"

    def _status_inspection(self) -> list[str]:
        def build() -> list[str]:
            count, kinds = self._record_kinds()
            view_text = self.chat.view.render()
            view_lines = self.chat.view.lines()
            coverage, _pointed = self._coverage(view_lines)
            settled = self.chat.view.settled()
            view_unbuilt = sum(
                self.chat.tree.get(line.l, line.i) is None for line in view_lines
            )
            queued_nodes = getattr(self.chat.compactor, "_queued", None)
            unbuilt = len(queued_nodes) if queued_nodes is not None else view_unbuilt
            queue_depth = len(getattr(self.chat.compactor, "_pending", ()))
            state = self._compactor_state(settled=settled, queued=unbuilt)
            raw = [
                "WILLIA STATUS", "",
                f"Session: {str(self.chat.session)[:8]}",
                f"Records: {count}",
            ]
            raw.extend(f"  {kind}: {kinds[kind]}" for kind in sorted(kinds))
            raw.extend([
                f"View: {len(view_text.encode('utf-8')):,} B · records {coverage}",
                f"Tree nodes: {len(self.chat.tree.nodes())}",
                f"Settled: {'yes' if settled else 'no'}",
                f"Unbuilt nodes: {unbuilt}",
                f"Compaction: {state} · queue {queue_depth}",
                self._jobs_line(),
            ])
            return raw

        return self._with_engine_snapshot("WILLIA STATUS", build)

    def _usage_local(self) -> list[str]:
        root = getattr(self.chat, "root", None)
        path = usage.usage_file(root) if root is not None else None
        entries = usage.read(path) if path is not None else []
        summary = usage.totals(entries)
        raw = ["WILLIA USAGE", "", f"Usage log: {path or 'unavailable'}",
               f"Calls: {summary['calls']}"]
        raw.extend(f"{name}: {summary[name]}" for name in usage.BUCKETS)
        for kind in sorted(summary["by_kind"]):
            bucket = summary["by_kind"][kind]
            raw.append(
                f"{kind}: calls={bucket['calls']} input={bucket['input_tokens']} "
                f"output={bucket['output_tokens']} cache_read={bucket['cache_read_tokens']} "
                f"cache_write={bucket['cache_write_tokens']} "
                f"reasoning={bucket['reasoning_tokens']}"
            )
        if entries:
            raw.append(f"Latest call: {entries[-1].get('at')} ({entries[-1].get('kind')})")
        return raw

    def _usage_state(self) -> dict:
        if not callable(self.usage_source):
            return {"go_status": "unavailable", "go_windows": {},
                    "codex_status": "unavailable", "codex_windows": {}}
        try:
            state = self.usage_source()
        except Exception:
            state = None
        return state if isinstance(state, dict) else {
            "go_status": "unavailable", "go_windows": {},
            "codex_status": "unavailable", "codex_windows": {},
        }

    @staticmethod
    def _window_reset(value) -> str:
        try:
            target = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            return usage.countdown((target - datetime.now(timezone.utc)).total_seconds())
        except ValueError:
            return "?"

    def _usage_accounts(self) -> list[str]:
        state = self._usage_state()
        raw = ["go:"]
        go_status = state.get("go_status")
        windows = state.get("go_windows")
        if go_status == "loading":
            raw.append("Windows: loading")
        elif go_status != "ready" or not isinstance(windows, dict):
            error = state.get("go_error")
            raw.append("Windows: unavailable" + (f" ({error})" if error else ""))
        else:
            reported = [name for name in usage.WINDOWS if isinstance(windows.get(name), dict)]
            if not reported:
                raw.append("Windows: none reported for this plan")
            for name in reported:
                window = windows[name]
                reset_at = window.get("resetsAt")
                raw.append(
                    f"{name}: {window.get('percent')}% resets {reset_at} "
                    f"({self._window_reset(reset_at)})"
                )

        codex_status = state.get("codex_status")
        codex = state.get("codex_windows")
        if codex_status == "loading":
            raw.append("codex: loading")
        elif codex_status != "ready" or not isinstance(codex, dict):
            error = state.get("codex_error")
            raw.append("codex: unavailable" + (f" ({error})" if error else ""))
        else:
            raw.append(f"codex: plan={codex.get('plan') or 'unknown'}")
            for name in ("primary", "secondary"):
                window = codex.get(name)
                if not isinstance(window, dict):
                    continue
                label = window.get("label") or name
                percent = window.get("percent")
                percent_text = f"{percent:g}%" if isinstance(percent, (int, float)) else "?"
                raw.append(
                    f"{label}: {percent_text} resets "
                    f"{usage.countdown(window.get('resets_in_s'))}"
                )
            if codex.get("reset_credits") is not None:
                raw.append(f"reset credits: {codex['reset_credits']}")
        return raw

    def _inspection_raw(self) -> list[str]:
        if self.panel_name == "usage":
            return [*self._usage_local_lines, *self._usage_accounts()]
        return self._panel_lines

    def _panel_content(self, width: int | None = None) -> list[str]:
        if self.panel_name == "help":
            return self._help_content(width)
        return self._wrap_panel_lines(self._inspection_raw(), width)

    def _open_panel(self, name: str, lines: list[str] | None = None) -> None:
        if not self.help_open:
            self._panel_position = (
                self.scroll_offset, self.transcript_cursor, self.visual_anchor)
        self.help_open = True
        self.panel_name = name
        self.help_scroll = 0
        self._panel_lines = list(lines or ())

    def _close_panel(self) -> None:
        self.help_open = False
        self.panel_name = None
        self.help_scroll = 0
        if self._panel_position is not None:
            self.scroll_offset, self.transcript_cursor, self.visual_anchor = self._panel_position
        self._panel_position = None

    def _open_inspection(self, command: str) -> None:
        name = command.removeprefix(":")
        if command == ":view":
            lines = self._view_inspection()
        elif command == ":tree":
            lines = self._tree_inspection()
        elif command == ":status":
            lines = self._status_inspection()
        else:
            self._usage_local_lines = self._usage_local()
            lines = []
        self._open_panel(name, lines)
        self._usage_state_seen = self._usage_state() if command == ":usage" else None

    def _help_max_scroll(self) -> int:
        _width, height = self.screen.size()
        content = self._panel_content()
        visible = max(1, min(height - 4, len(content)))
        return max(0, len(content) - visible)

    def _help_key(self, key: str) -> None:
        if key in {"ESC", "q"} or (key == "?" and self.panel_name == "help"):
            self._close_panel()
        elif key in {"j", "DOWN"}:
            self.help_scroll = min(self._help_max_scroll(), self.help_scroll + 1)
        elif key in {"k", "UP"}:
            self.help_scroll = max(0, self.help_scroll - 1)
        elif key in {"CTRL_D", "PGDN"}:
            _width, height = self.screen.size()
            self.help_scroll = min(
                self._help_max_scroll(), self.help_scroll + max(1, (height - 4) // 2))
        elif key in {"CTRL_U", "PGUP"}:
            _width, height = self.screen.size()
            self.help_scroll = max(0, self.help_scroll - max(1, (height - 4) // 2))
        elif key in {"g", "HOME"}:
            self.help_scroll = 0
        elif key in {"G", "END"}:
            self.help_scroll = self._help_max_scroll()

    @staticmethod
    def _rail_identity(fact, occurrence: int) -> tuple[str, int]:
        return str(fact[0]), occurrence

    def _visible_rail_facts(self):
        visible = []
        index = 0
        while index < len(self.rail_facts):
            fact = self.rail_facts[index]
            label = str(fact[0])
            if not label.startswith("#"):
                visible.append(fact)
                index += 1
                continue
            end = index + 1
            while end < len(self.rail_facts) and not str(self.rail_facts[end][0]).startswith("#"):
                end += 1
            if label in self.collapsed_groups:
                hidden = [item for item in self.rail_facts[index + 1:end]
                          if str(item[0]) != "state"]
                visible.append((label, str(len(hidden)), fact[2]))
                visible.extend(item for item in self.rail_facts[index + 1:end]
                               if str(item[0]) == "state")
            else:
                visible.extend(self.rail_facts[index:end])
            index = end
        return visible

    def _selected_rail_identity(self) -> tuple[str, int] | None:
        facts = self._visible_rail_facts()
        if not facts:
            return None
        index = min(self.rail_index, len(facts) - 1)
        label = str(facts[index][0])
        occurrence = sum(1 for fact in facts[:index] if str(fact[0]) == label)
        return self._rail_identity(facts[index], occurrence)

    def _restore_rail_selection(self, identity: tuple[str, int] | None) -> None:
        facts = self._visible_rail_facts()
        if not facts:
            self.rail_index = 0
            return
        if identity is not None:
            occurrence = 0
            for index, fact in enumerate(facts):
                label = str(fact[0])
                if label == identity[0]:
                    if occurrence == identity[1]:
                        self.rail_index = index
                        return
                    occurrence += 1
        self.rail_index = min(self.rail_index, len(facts) - 1)

    def _move_rail(self, amount: int) -> None:
        facts = self._visible_rail_facts()
        if facts:
            self.rail_index = max(0, min(len(facts) - 1, self.rail_index + amount))

    def _rail_group(self) -> str | None:
        facts = self._visible_rail_facts()
        if not facts:
            return None
        selected = str(facts[min(self.rail_index, len(facts) - 1)][0])
        if selected.startswith("#"):
            return selected
        original_index = next((index for index, fact in enumerate(self.rail_facts)
                               if str(fact[0]) == selected), -1)
        for index in range(original_index, -1, -1):
            label = str(self.rail_facts[index][0])
            if label.startswith("#"):
                return label
        return None

    def _fold_rail(self, collapsed: bool) -> None:
        group = self._rail_group()
        if group is None:
            return
        if collapsed:
            self.collapsed_groups.add(group)
            for index, fact in enumerate(self._visible_rail_facts()):
                if str(fact[0]) == group:
                    self.rail_index = index
                    break
        else:
            self.collapsed_groups.discard(group)

    def _switch_pane(self, pane: Pane | None = None) -> None:
        if not self.rail_visible:
            self.focus = Pane.TRANSCRIPT
            return
        self.focus = pane or (
            Pane.RAIL if self.focus == Pane.TRANSCRIPT else Pane.TRANSCRIPT)

    def _ctrl_w_key(self, key: str) -> None:
        self._pending_ctrl_w = False
        if key in {"h", "LEFT"}:
            self._switch_pane(Pane.RAIL)
        elif key in {"l", "RIGHT"}:
            self._switch_pane(Pane.TRANSCRIPT)
        elif key in {"j", "DOWN"}:
            self._move_rail(1) if self.focus == Pane.RAIL else self._move(-1)
        elif key in {"k", "UP"}:
            self._move_rail(-1) if self.focus == Pane.RAIL else self._move(1)

    def _command_key(self, key: str) -> None:
        if key == "ESC":
            self.command = None
        elif key == "BACKSPACE":
            self.command = self.command[:-1]
            if not self.command:
                self.command = None
        elif key == "TAB":
            matches = [name for name in COLON_COMMANDS if name.startswith(self.command)]
            if len(matches) == 1:
                self.command = matches[0]
            elif matches:
                prefix = matches[0]
                for match in matches[1:]:
                    prefix = prefix[:next(
                        (index for index, pair in enumerate(zip(prefix, match))
                         if pair[0] != pair[1]), min(len(prefix), len(match)))]
                self.command = prefix
        elif key == "ENTER":
            command, self.command = self.command, None
            if command == ":q":
                self.running = False
            elif command == ":help":
                self._open_panel("help")
            elif command in INSPECTION_COMMANDS:
                self._open_inspection(command)
            elif command == ":notes":
                self.show_notes = not self.show_notes
                self.notice = "memory shown" if self.show_notes else "memory hidden"
            elif command.startswith(":theme "):
                name = command.removeprefix(":theme ").strip()
                if name in PALETTES:
                    self.theme = name
                    self._cache_key = None
                    self._set_notice(f"theme {name}")
                else:
                    self._set_notice(f"unknown theme: {name}")
            else:
                available = ", ".join(COLON_COMMANDS)
                self.notice = f"Unknown command: {command} (available: {available})"
        elif len(key) == 1 and key.isprintable():
            self.command += key

    def handle_key(self, key: str) -> bool:
        if key in {"CTRL_C", "EOF"}:
            self.running = False
            return False
        if self.help_open:
            self._help_key(key)
            return self.running
        if self.command is not None:
            self._command_key(key)
            return self.running
        if self.mode == Mode.INSERT:
            if key == "ESC":
                self.mode = Mode.NORMAL
            elif key == "ENTER":
                self._send()
            elif key == "CTRL_J":
                self._insert("\n")
            elif key == "CTRL_U":
                self.buffer = ""
                self.caret = 0
            elif key == "CTRL_W":
                self._delete_word()
            elif key == "BACKSPACE":
                caret = max(0, min(self.caret, len(self.buffer)))
                if caret:
                    self.buffer = self.buffer[:caret - 1] + self.buffer[caret:]
                    self.caret = caret - 1
            elif key == "UP":
                self._history(-1)
            elif key == "DOWN":
                self._history(1)
            elif len(key) == 1 and key.isprintable():
                self._insert(key)
            return self.running

        if self._pending_ctrl_w:
            self._ctrl_w_key(key)
            return self.running

        if key == "i":
            self.mode = Mode.INSERT
            self.caret = len(self.buffer)
            self.visual_anchor = None
        elif key == "?":
            self._open_panel("help")
        elif key == "v" and self.focus == Pane.TRANSCRIPT:
            if self.visual_anchor is None:
                self.visual_anchor = self._focused_transcript_index()
            else:
                self.visual_anchor = None
        elif key == "y" and self.focus == Pane.TRANSCRIPT:
            self._yank()
        elif key == "Y" and self.focus == Pane.TRANSCRIPT:
            self._yank(whole=True)
        elif key == "TAB":
            self._switch_pane()
        elif key == "CTRL_W":
            self._pending_ctrl_w = True
        elif key == "ENTER":
            if self.focus == Pane.RAIL:
                self._fold_rail(True)
            else:
                self._fold_transcript(True)
        elif key == "ESC":
            if self.visual_anchor is not None:
                self.visual_anchor = None
            elif self.focus == Pane.RAIL:
                self._fold_rail(False)
            else:
                self._fold_transcript(False)
        elif key == "CTRL_B":
            self.rail_visible = not self.rail_visible
            if not self.rail_visible:
                self.focus = Pane.TRANSCRIPT
        elif key == ":":
            self.command = ":"
        elif key in {"j", "DOWN"}:
            self._move_rail(1) if self.focus == Pane.RAIL else self._move(-1)
        elif key in {"k", "UP"}:
            self._move_rail(-1) if self.focus == Pane.RAIL else self._move(1)
        elif key in {"l", "RIGHT"}:
            self._move(-1)
        elif key in {"h", "LEFT"}:
            self._move(1)
        elif key in {"CTRL_D", "PGDN"}:
            _width, body_height, _centre = self._body_size()
            self._move(-max(1, body_height // 2))
        elif key in {"CTRL_U", "PGUP"}:
            _width, body_height, _centre = self._body_size()
            self._move(max(1, body_height // 2))
        elif key in {"G", "END"}:
            self.scroll_offset = 0
            self.transcript_cursor = 0
        elif key == "HOME":
            self.scroll_offset = self._max_offset()
            self.transcript_cursor = max(0, len(self._all_transcript_lines()) - 1)
        elif key == "g":
            if self._pending_g:
                self.scroll_offset = self._max_offset()
                self.transcript_cursor = max(0, len(self._all_transcript_lines()) - 1)
                self._pending_g = False
            else:
                self._pending_g = True
                return self.running
        else:
            self._pending_g = False
        return self.running

    # ---------------------------------------------------------------- drawing

    def _input_visible(self) -> bool:
        return self.mode == Mode.INSERT or self.busy or self.command is not None

    def _input_rows(self, width: int) -> tuple[list[Line], int]:
        """Lay out the editable value and its painted caret in transcript-width rows."""
        value = self.command if self.command is not None else self.buffer
        caret = len(value) if self.command is not None else max(
            0, min(self.caret, len(value)))
        focused = self.mode == Mode.INSERT or self.command is not None
        marker_style = "agent" if focused else "dim"
        prefix = "  ❯ "
        prefix_width = cell_width(prefix)

        if width <= prefix_width:
            marker = fit("  ❯", width)
            return [Line(marker, marker_style, (Span(marker, marker_style),))], 0

        content_width = max(1, width - prefix_width)
        # A cluster keeps zero-width combining marks attached to their base character. The
        # renderer's measured cell width remains the only source of column truth.
        clusters: list[list] = []
        for index, char in enumerate(value):
            if (char != "\n" and cell_width(char) == 0 and clusters
                    and clusters[-1][2] != "\n"):
                clusters[-1][1] = index + 1
                clusters[-1][2] += char
                continue
            clusters.append([index, index + 1, char, cell_width(char)])

        rows: list[list[list]] = [[]]
        positions: dict[int, tuple[int, int]] = {0: (0, 0)}
        cells = 0
        for start, end, text, size in clusters:
            row_index = len(rows) - 1
            if text == "\n":
                positions[start] = (row_index, cells)
                rows.append([])
                cells = 0
                positions[end] = (len(rows) - 1, 0)
                continue
            if cells and cells + size > content_width:
                rows.append([])
                cells = 0
                row_index = len(rows) - 1
            for position in range(start, end):
                positions[position] = (row_index, cells)
            rows[-1].append([start, end, text, size])
            cells += size
            positions[end] = (row_index, cells)

        caret_row, caret_column = positions.get(caret, (len(rows) - 1, cells))
        if focused and caret == len(value) and caret_column >= content_width:
            rows.append([])
            caret_row, caret_column = len(rows) - 1, 0

        lines: list[Line] = []
        for row_index, units in enumerate(rows):
            if row_index == 0:
                spans: list[Span] = [
                    Span("  ", "dim"), Span("❯", marker_style), Span(" ", "dim")]
            else:
                spans = [Span(" " * prefix_width, "dim")]
            caret_drawn = False
            for start, end, text, size in units:
                under_caret = focused and start <= caret < end
                if under_caret and size > 0:
                    spans.append(Span(text, "bg", "you"))
                    caret_drawn = True
                else:
                    spans.append(Span(text, "you"))
            if focused and row_index == caret_row and not caret_drawn:
                spans.append(Span("█", "you"))
            text = "".join(span.text for span in spans)
            deficit = width - cell_width(text)
            if deficit > 0:
                spans.append(Span(" " * deficit, "you"))
                text += " " * deficit
            lines.append(Line(text, "you", tuple(spans)))
        return lines, caret_row

    def _input_field_lines(self, width: int, max_rows: int) -> list[Line]:
        if not self._input_visible() or max_rows <= 0:
            return []
        content, caret_row = self._input_rows(width)
        rule = Line("─" * max(0, width), "rule")
        if max_rows == 1:
            return [rule]
        capacity = max_rows - 1
        if len(content) <= capacity:
            shown = content
        else:
            anchor = caret_row if self.mode == Mode.INSERT or self.command is not None else len(content) - 1
            start = max(0, min(anchor - capacity + 1, len(content) - capacity))
            shown = content[start:start + capacity]
        return [rule, *shown]

    def _field_frame_row(self, line: Line, width: int) -> Line:
        right_spans = line.spans or (Span(line.text, line.style),)
        if self.rail_visible:
            spans = (
                Span(" " * (RAIL_WIDTH - 1), "body", "panel"),
                Span("│", "rule"),
                *right_spans,
            )
        else:
            spans = right_spans
        text = "".join(span.text for span in spans)
        deficit = width - cell_width(text)
        if deficit > 0:
            spans = (*spans, Span(" " * deficit, "body"))
            text += " " * deficit
        return Line(text, line.style, tuple(spans))

    def _help_frame(self) -> list[Line]:
        width, height = self.screen.size()
        panel_width = max(4, min(80, width - 4))
        content = self._panel_content()
        inner_height = max(1, min(height - 4, len(content)))
        self.help_scroll = min(self.help_scroll, max(0, len(content) - inner_height))
        shown = content[self.help_scroll:self.help_scroll + inner_height]
        panel_height = inner_height + 2
        top = max(0, (height - panel_height) // 2)
        left = max(0, (width - panel_width) // 2)
        rows = [Line(" " * width, "body") for _ in range(height)]
        border = "─" * max(0, panel_width - 2)
        panel = ["┌" + border + "┐"]
        panel.extend("│" + fit(value, panel_width - 2) + "│" for value in shown)
        panel.append("└" + border + "┘")
        for index, value in enumerate(panel):
            text = " " * left + value + " " * max(0, width - left - cell_width(value))
            style = "rule_strong" if index in {0, len(panel) - 1} else "body"
            rows[top + index] = Line(
                fit(text, width), style,
                (Span(" " * left, "body"), Span(value, style, "panel"),
                 Span(" " * max(0, width - left - cell_width(value)), "body")),
            )
        return rows

    def _rail_lines(self, height: int) -> list[Line]:
        lines: list[Line] = []
        facts = self._visible_rail_facts()
        raw_levels = {
            str(label): int(value)
            for label, value, _style in facts
            if str(label).startswith("l") and str(label)[1:].isdigit()
            and str(value).isdigit()
        }
        biggest = max(raw_levels.values(), default=0)
        count_width = max((len(str(count)) for count in raw_levels.values()), default=1)
        self.rail_index = min(self.rail_index, max(0, len(facts) - 1))
        section = ""

        def padded_spans(parts: list[Span]) -> tuple[str, tuple[Span, ...]]:
            text = "".join(part.text for part in parts)
            remaining = RAIL_WIDTH - 1 - cell_width(text)
            if remaining > 0:
                parts.append(Span(" " * remaining, "dim"))
                text += " " * remaining
            return fit(text, RAIL_WIDTH - 1), tuple(parts)

        def header_text(value: str, suffix: str = "") -> str:
            spaced = " ".join(value)
            candidate = spaced + suffix
            return candidate if cell_width(candidate) <= RAIL_WIDTH - 1 else value + suffix

        def value_spans(label: str, value: str, token: str) -> list[Span]:
            if label == "64K-128K":
                parts: list[Span] = []
                for char in value:
                    char_token = "data" if char == "●" else (
                        "rule_strong" if char == "─" else "dim")
                    if parts and parts[-1].style == char_token:
                        parts[-1] = Span(parts[-1].text + char, char_token)
                    else:
                        parts.append(Span(char, char_token))
                return parts

            base_token = token
            if section == "#facts":
                if label.endswith("↺"):
                    base_token = "dim"
                elif re.fullmatch(r"[\d.,% /]+", value):
                    base_token = "data"
                else:
                    base_token = "body"
            suffix_at = len(value)
            parenthesis = value.find("(")
            middle_dot = value.find("·")
            if parenthesis >= 0:
                suffix_at = min(suffix_at, parenthesis)
            if middle_dot >= 0:
                suffix_at = min(suffix_at, middle_dot)
            parts = [Span(value[:suffix_at], base_token)] if suffix_at else []
            if suffix_at < len(value):
                parts.append(Span(value[suffix_at:], "dim"))
            return parts

        for index, (label, value, style) in enumerate(facts):
            if label.startswith("#"):
                section = str(label)
                if lines:                      # 005's .sep and its gap between sections
                    # The gap carries the rail's width in spaces: an empty string makes the
                    # composer drop the rail column on that row and the transcript slides left.
                    lines.append(Line(" " * (RAIL_WIDTH - 1), "body"))
                    lines.append(Line("─" * (RAIL_WIDTH - 1), "rule"))
                text = label[1:].upper()
                suffix = ""
                if label in self.collapsed_groups:
                    suffix = f" [{value}]"
                text = header_text(text, suffix)
                shown = fit(text, RAIL_WIDTH - 1)
                token = "strong" if index == self.rail_index and self.focus == Pane.RAIL else "dim"
                spans = (Span(shown, token, "panel"),) if token == "strong" else ()
                lines.append(Line(shown, token, spans))
                continue
            if str(label) in raw_levels:
                count = raw_levels[str(label)]
                filled = max(1, round(12 * count / biggest)) if count and biggest else 0
                label_part = fit(str(label), 9)
                bar = "█" * filled + " " * (12 - filled)
                count_part = f"{count:>{count_width}}"
                shown, spans = padded_spans([
                    Span(label_part + " ", "dim"),
                    Span(bar, "data"),
                    Span(" " + count_part, "dim"),
                ])
                selected = index == self.rail_index and self.focus == Pane.RAIL
                if selected:
                    spans = tuple(Span(span.text, "strong", "panel") for span in spans)
                lines.append(Line(shown, "strong" if selected else "dim", spans))
                continue
            available = RAIL_WIDTH - 1
            label_width = min(9, available)
            value_width = max(0, available - label_width - 1)
            clipped_value = fit(str(value), value_width, ellipsis="…", pad=False)
            shown, spans = padded_spans([
                Span(fit(str(label), label_width) + " ", "dim"),
                *value_spans(str(label), clipped_value, str(style)),
            ])
            selected = index == self.rail_index and self.focus == Pane.RAIL
            if selected:
                spans = tuple(Span(span.text, "strong", "panel") for span in spans)
            lines.append(Line(
                shown, "strong" if selected else style,
                spans,
            ))
        return lines[:height]

    def _frame(self) -> list[Line]:
        if self.help_open:
            return self._help_frame()
        width, height = self.screen.size()
        _full_width, body_height, centre = self._body_size()
        field = self._input_field_lines(centre, max(0, height - 1))
        durable = self._transcript(centre)
        # The in-flight tail is rebuilt each frame: it is small and it is what is moving.
        flight = render((), self.in_flight, centre, -1, self.theme) if self.in_flight else []
        all_transcript = durable + flight
        transcript_height = max(0, body_height - 2)  # one blank row above and below the stage
        transcript = viewport(all_transcript, transcript_height, self.scroll_offset)
        if transcript and not transcript[0].text:
            transcript = transcript[1:]             # collapse a block margin into stage padding
        transcript_start = max(
            0, len(all_transcript) - self.scroll_offset - transcript_height)
        rail = self._rail_lines(body_height)
        rows: list[Line] = []
        for index in range(body_height):
            transcript_index = index - 1
            right = (transcript[transcript_index]
                     if 0 <= transcript_index < len(transcript) else Line("", "body"))
            right_spans = right.spans or (Span(right.text, right.style),)
            if self.visual_anchor is not None and 0 <= transcript_index < len(transcript):
                current = self._focused_transcript_index()
                if current is not None:
                    lo, hi = sorted((self.visual_anchor, current))
                    if lo <= transcript_start + transcript_index <= hi:
                        right_spans = tuple(Span(span.text, span.style, "panel")
                                            for span in right_spans)
            if self.rail_visible:
                left = rail[index] if index < len(rail) else Line(" " * (RAIL_WIDTH - 1), "panel")
                left_spans = left.spans or (Span(left.text, left.style),)
                separator = "rule_strong" if self.focus == Pane.TRANSCRIPT else "rule"
                spans = (*left_spans, Span("│", separator), *right_spans)
            else:
                spans = right_spans
            text = "".join(span.text for span in spans)
            # Pad to the full width: the repaint homes instead of clearing, so nothing stale may
            # survive underneath a shorter row.
            deficit = width - cell_width(text)
            if deficit > 0:
                spans = (*spans, Span(" " * deficit, "body"))
                text += " " * deficit
            rows.append(Line(text, "body", spans))

        rows.extend(self._field_frame_row(line, width) for line in field)
        rows.append(Line(fit(self._status(), width, pad=True), self._status_style()))
        return rows[:height]

    def _status(self) -> str:
        if self.draw_error:
            return f"DRAW FAILED · {self.draw_error}"
        parts = [self.mode.value, self.focus.value]
        if self.compacting:
            parts.append("compacting")
        elif self.busy:
            parts.append("streaming")
        explanation = self.notice or self._focused_hint()
        if explanation:
            parts.append(explanation)
        return " · ".join(parts)

    def _focused_hint(self) -> str:
        if self.focus == Pane.RAIL:
            facts = self._visible_rail_facts()
            if not facts:
                return ""
            key = str(facts[min(self.rail_index, len(facts) - 1)][0]).lstrip("#")
        else:
            line = self._focused_transcript_line()
            key = line.record_kind if line is not None else None
        return HINTS.get(key, "")

    def _status_style(self) -> str:
        if self.draw_error:
            return "red"
        if self.notice:
            return "strong"
        if self.busy or self.compacting:
            return "amber"
        return "dim"

    def _redraw_soon(self) -> None:
        """One paint per tick at most, and remember that a paint is still owed."""
        now = time.monotonic()
        if self._last_draw is None or now - self._last_draw >= _REDRAW_INTERVAL_S:
            self.redraw()
        else:
            self._pending_draw = True

    def redraw(self, *, force: bool = False) -> None:
        """Paint only when the frame differs from the last one: an idle TUI must write nothing."""
        try:
            lines = self._frame()
            key = (self.theme, tuple(lines))
            self.screen.resized = False
            if not force and key == self._frame_key:
                self._pending_draw = False
                return
            self.screen.draw(lines, self.theme)
            self._frame_key = key
            self._pending_draw = False
            self._last_draw = time.monotonic()
            self.draw_error = ""
        except Exception as exc:
            # A broken draw must not kill the chat, and it must not be silent either: a swallowed
            # NameError once left the screen blank with nothing anywhere. It shows in the status.
            self.draw_error = f"{type(exc).__name__}: {exc}"
            log.warning("TUI draw failed: %s", exc)

    # ---------------------------------------------------------------- main loop

    def run(self) -> None:
        with self.screen:
            self.redraw(force=True)
            try:
                while self.running:
                    changed = self._drain_events()
                    if self._rail_due() and self._refresh_rail():
                        changed = True
                    if self.help_open and self.panel_name == "usage":
                        usage_state = self._usage_state()
                        if usage_state != self._usage_state_seen:
                            self._usage_state_seen = usage_state
                            changed = True
                    poll = getattr(self.screen, "poll_key", None)
                    key = poll(0.05) if poll is not None else self.screen.read_key()
                    if key is not None:
                        self.handle_key(key)
                        changed = True
                    if self._notice_expired():
                        changed = True
                    if changed or self._pending_draw:
                        self._redraw_soon()
            finally:
                self.running = False
                self.join_turn(5.0)
