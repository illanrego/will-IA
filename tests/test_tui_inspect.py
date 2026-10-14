from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from willia import usage
from willia.store import Record
from willia.tree import Line
from willia.tui.app import App


class StubScreen:
    resized = False

    def size(self):
        return 64, 9

    def draw(self, lines, theme):
        pass


class StubLog:
    def __init__(self):
        self.records = [
            Record(0, "user", "hello", 5, "2026-10-14T00:00:00Z"),
            Record(1, "will", "answer", 6, "2026-10-14T00:00:01Z"),
            Record(2, "tool", "{}", 2, "2026-10-14T00:00:02Z"),
        ]

    def count(self):
        return len(self.records)

    def get(self, index):
        return self.records[index]

    def range(self, lo, hi):
        return self.records[max(0, lo):hi + 1]


class StubTree:
    def __init__(self):
        self._nodes = {
            (0, 0): Line(0, 0, "user: hello", 11),
            (0, 1): Line(0, 1, "will: answer", 12),
            (0, 2): Line(0, 2, "tool: {}", 8),
            (1, 0): Line(1, 0, "first pair", 10),
        }

    def nodes(self):
        return dict(self._nodes)

    def get(self, level, index):
        return self._nodes.get((level, index))


class StubView:
    def __init__(self, tree):
        self.tree = tree
        self._lines = [tree.get(1, 0), tree.get(0, 2)]

    def lines(self):
        return list(self._lines)

    def settled(self):
        return True

    def render(self):
        body = ["<chat>"]
        body.extend(f"line {index}: model memory" for index in range(12))
        body.append("</chat>")
        return "\n".join(body)


class StubChat:
    def __init__(self, root):
        self.root = root
        self.session = "1234567890abcdef"
        self.log = StubLog()
        self.tree = StubTree()
        self.view = StubView(self.tree)
        self.compactor = SimpleNamespace(_pending=[])
        self._drain = None
        self._stuck_reported = False
        self._lock = threading.Lock()

    @contextmanager
    def engine_try(self):
        taken = self._lock.acquire(blocking=False)
        try:
            yield taken
        finally:
            if taken:
                self._lock.release()

    @contextmanager
    def _engine(self):
        with self._lock:
            yield


def press_command(app, name):
    for key in name:
        app.handle_key(key)
    app.handle_key("ENTER")


def usage_source():
    return {
        "go_status": "ready",
        "go_windows": {
            "rolling": {"percent": 12.5, "resetsAt": "2026-10-14T20:00:00Z"},
        },
        "codex_status": "ready",
        "codex_windows": {
            "plan": "plus",
            "primary": {"label": "5h", "percent": 18, "resets_in_s": 900},
        },
    }


@pytest.fixture
def inspect_app(tmp_path):
    path = usage.usage_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("\n".join([
        json.dumps({
            "at": "2026-10-14T00:00:00Z", "kind": "turn",
            "input_tokens": 100, "output_tokens": 10, "cache_read_tokens": 80,
            "cache_write_tokens": 2, "reasoning_tokens": 3,
        }),
        json.dumps({
            "at": "2026-10-14T00:01:00Z", "kind": "compaction",
            "input_tokens": 40, "output_tokens": 4, "cache_read_tokens": 30,
            "cache_write_tokens": 1, "reasoning_tokens": 0,
        }),
    ]) + "\n", encoding="utf-8")
    return App(StubChat(tmp_path), StubScreen(), usage_source=usage_source)


@pytest.mark.parametrize(("command", "expected"), [
    (":view", ("WILLIA VIEW", " B", "records 0-2", "<chat>", "model memory")),
    (":tree", ("WILLIA TREE", "l0", "l1", "nodes 4", "ROOTS", "settled")),
    (":status", ("WILLIA STATUS", "Records: 3", "user: 1", "tool: 1", "Tree nodes: 4")),
    (":usage", ("WILLIA USAGE", "Calls: 2", "turn: calls=1", "compaction: calls=1",
                "rolling: 12.5%", "codex: plan=plus")),
])
def test_each_inspection_command_opens_the_shared_panel(inspect_app, command, expected):
    press_command(inspect_app, command)
    text = "\n".join(inspect_app._inspection_raw())
    assert inspect_app.help_open is True
    assert inspect_app.panel_name == command[1:]
    assert all(value in text for value in expected)


@pytest.mark.parametrize("close_key", ["q", "ESC"])
def test_panel_scroll_and_close_restore_exact_transcript_position_and_selection(
        inspect_app, close_key):
    inspect_app.scroll_offset = 2
    inspect_app.transcript_cursor = 2
    inspect_app.visual_anchor = 1
    before = (inspect_app.scroll_offset, inspect_app.transcript_cursor,
              inspect_app.visual_anchor)
    press_command(inspect_app, ":view")
    inspect_app.handle_key("j")
    assert inspect_app.help_scroll == 1
    inspect_app.handle_key("G")
    assert inspect_app.help_scroll == inspect_app._help_max_scroll()
    inspect_app.handle_key(close_key)
    assert inspect_app.help_open is False
    assert (inspect_app.scroll_offset, inspect_app.transcript_cursor,
            inspect_app.visual_anchor) == before


@pytest.mark.parametrize("command", [":view", ":tree", ":status"])
def test_locked_engine_reports_compacting_without_blocking(inspect_app, command):
    with inspect_app.chat._engine():
        started = time.monotonic()
        press_command(inspect_app, command)
        elapsed = time.monotonic() - started
    assert elapsed < 0.1
    assert "compacting" in "\n".join(inspect_app._inspection_raw())


def tree_bytes(root):
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def test_inspection_commands_write_neither_log_nor_any_file(inspect_app):
    before_count = inspect_app.chat.log.count()
    before_files = tree_bytes(inspect_app.chat.root)
    for command in (":view", ":tree", ":status", ":usage"):
        press_command(inspect_app, command)
        inspect_app.handle_key("q")
        assert inspect_app.chat.log.count() == before_count
        assert tree_bytes(inspect_app.chat.root) == before_files


def test_usage_panel_opens_before_account_windows_arrive(inspect_app):
    state = {
        "go_status": "loading", "go_windows": {},
        "codex_status": "loading", "codex_windows": {},
    }
    inspect_app.usage_source = lambda: dict(state)
    press_command(inspect_app, ":usage")
    initial = "\n".join(inspect_app._inspection_raw())
    assert "Calls: 2" in initial
    assert "Windows: loading" in initial
    assert "codex: loading" in initial

    state.update(usage_source())
    filled = "\n".join(inspect_app._inspection_raw())
    assert "rolling: 12.5%" in filled
    assert "5h: 18%" in filled
