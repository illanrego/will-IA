import time

import pytest

from willia.store import Record
from willia import cli
from willia.tui.app import App, Mode


class FakeLog:
    def __init__(self, count=20):
        self.records = [
            Record(i, "will", f"record {i}", 8, "2026-10-14T00:00:00Z")
            for i in range(count)
        ]

    def count(self):
        return len(self.records)

    def range(self, lo, hi):
        return self.records[max(0, lo):hi + 1]


class FakeChat:
    def __init__(self):
        self.log = FakeLog()
        self.sent = []

    def turn(self, texts, *, sink=None):
        self.sent.extend(texts)
        sink("delta", kind="reasoning", text="thinking")
        sink("delta", kind="content", text="done")
        sink("end", usage={})


class FakeScreen:
    resized = False

    def size(self):
        return 50, 8

    def draw(self, lines, theme):
        pass


def press(app, *keys):
    for key in keys:
        app.handle_key(key)


def test_insert_mode_editing_send_and_escape():
    chat = FakeChat()
    app = App(chat, FakeScreen())
    press(app, "i", "h", "i", "CTRL_J", "x", "BACKSPACE", "!")
    assert app.mode == Mode.INSERT
    assert app.buffer == "hi\n!"
    app.handle_key("ESC")
    assert app.mode == Mode.NORMAL
    press(app, "ENTER", "CTRL_U", "o", "n", "e", " ", "t", "w", "o", "CTRL_W")
    assert app.buffer == "one "
    app.handle_key("ENTER")
    app.join_turn()
    assert chat.sent == ["one "]
    assert app.mode == Mode.NORMAL


def test_ctrl_u_and_history_up_down():
    chat = FakeChat()
    app = App(chat, FakeScreen())
    press(app, "i", "f", "i", "r", "s", "t", "ENTER")
    press(app, "i", "s", "e", "c", "o", "n", "d", "ENTER")
    app.join_turn()
    app.handle_key("i")
    app.buffer = "draft"
    app.handle_key("UP")
    assert app.buffer == "second"
    app.handle_key("UP")
    assert app.buffer == "first"
    app.handle_key("DOWN")
    assert app.buffer == "second"
    app.handle_key("DOWN")
    assert app.buffer == "draft"
    app.handle_key("CTRL_U")
    assert app.buffer == ""


def test_normal_scroll_motions_gg_and_G():
    app = App(FakeChat(), FakeScreen())
    assert app.scroll_offset == 0
    app.handle_key("k")
    assert app.scroll_offset == 1
    app.handle_key("CTRL_U")
    assert app.scroll_offset > 1
    app.handle_key("g")
    app.handle_key("g")
    assert app.scroll_offset == app._max_offset()
    app.handle_key("j")
    assert app.scroll_offset == app._max_offset() - 1
    app.handle_key("G")
    assert app.scroll_offset == 0
    app.handle_key("CTRL_D")
    assert app.scroll_offset == 0


def test_q_help_and_unknown_commands():
    app = App(FakeChat(), FakeScreen())
    press(app, ":", "h", "e", "l", "p", "ENTER")
    assert ":q" in app.notice
    press(app, ":", "n", "o", "p", "e", "ENTER")
    assert "Unknown command" in app.notice
    press(app, ":", "q", "ENTER")
    assert app.running is False


def test_a_burst_of_stream_deltas_is_coalesced_into_few_draws():
    """One paint per token would flicker; the stream must coalesce, and the end must paint."""
    draws = []

    class CountingScreen(FakeScreen):
        def draw(self, lines, theme):
            draws.append(len(lines))

    app = App(FakeChat(), CountingScreen())
    app.redraw(force=True)
    assert len(draws) == 1, "the first frame must paint"
    for index in range(500):
        app("delta", kind="content", text=str(index))
    burst = len(draws) - 1
    assert burst < 10, f"500 deltas painted {burst} times"
    app.redraw()                      # the coalesced paint lands
    before = len(draws)
    for _ in range(5):
        app.redraw()
    assert len(draws) == before, "an unchanged frame was repainted, which is what flashed"


def test_a_broken_draw_is_visible_and_not_fatal():
    """A draw error must not kill the chat, and must not be silent either."""
    class BrokenScreen(FakeScreen):
        def draw(self, lines, theme):
            raise RuntimeError("no terminal today")

    app = App(FakeChat(), BrokenScreen())
    app.redraw(force=True)
    assert app.running is True
    assert "no terminal today" in app.draw_error
    assert "DRAW FAILED" in app._status()


class SlowChat(FakeChat):
    def turn(self, texts, *, sink=None):
        self.sent.extend(texts)
        time.sleep(0.3)
        sink("delta", kind="content", text="done")
        sink("end", usage={})


def test_a_turn_runs_off_the_ui_thread():
    """Sending must not freeze the UI: the turn runs on a worker and reports through the queue."""
    app = App(SlowChat(), FakeScreen())
    app.handle_key("i")
    app.buffer = "hello"
    started = time.monotonic()
    app.handle_key("ENTER")
    elapsed = time.monotonic() - started
    assert elapsed < 0.2, f"sending blocked the UI for {elapsed:.2f}s"
    assert app.busy is True
    app.join_turn()
    app._drain_events()
    assert app.busy is False


def test_the_transcript_is_cached_until_the_log_changes():
    """A frame must slice a cached render, not re-wrap the log (that was 185 ms per keypress)."""
    app = App(FakeChat(), FakeScreen())
    first = app._transcript(20)
    assert app._transcript(20) is first
    assert app.handle_key("j") in {True, False}
    assert app._transcript(20) is first
    app.chat.log.records.append(Record(20, "will", "new", 3, "2026-10-14T00:00:00Z"))
    assert app._transcript(20) is not first


def test_notes_are_hidden_by_default_and_visible_with_the_command():
    app = App(FakeChat(), FakeScreen())
    app.chat.log.records = [Record(0, "note", "memory", 6, "2026-10-14T00:00:00Z")]
    app._refresh_records()
    assert app._transcript(20) == []
    press(app, ":", "n", "o", "t", "e", "s", "ENTER")
    assert app.show_notes is True
    assert [line.text for line in app._transcript(20)] == ["note · memory"]


def test_ctrl_b_collapses_the_rail_and_gives_the_width_back():
    app = App(FakeChat(), FakeScreen())
    narrow = app._body_size()[2]
    assert app.rail_visible is True
    app.handle_key("CTRL_B")
    assert app.rail_visible is False
    assert app._body_size()[2] > narrow, "collapsing the rail must widen the transcript"
    app.handle_key("CTRL_B")
    assert app.rail_visible is True
    assert app._body_size()[2] == narrow


def test_cli_refuses_tui_when_stdout_is_not_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr(cli.Config, "load", lambda: object())
    monkeypatch.setattr(cli.Chat, "open", lambda _config: pytest.fail("chat was opened"))
    assert cli.main(["--tui"]) == 1
    assert "stdout" in capsys.readouterr().err.lower()
