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
    assert chat.sent == ["one "]
    assert app.mode == Mode.NORMAL


def test_ctrl_u_and_history_up_down():
    chat = FakeChat()
    app = App(chat, FakeScreen())
    press(app, "i", "f", "i", "r", "s", "t", "ENTER")
    press(app, "i", "s", "e", "c", "o", "n", "d", "ENTER")
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
    assert draws == []
    for index in range(500):
        app("delta", kind="content", text=str(index))
    burst = len(draws)
    assert burst < 10, f"500 deltas painted {burst} times"
    app("end", usage={})
    assert len(draws) == burst + 1, "the end of a turn must always paint"


def test_cli_refuses_tui_when_stdout_is_not_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr(cli.Config, "load", lambda: object())
    monkeypatch.setattr(cli.Chat, "open", lambda _config: pytest.fail("chat was opened"))
    assert cli.main(["--tui"]) == 1
    assert "stdout" in capsys.readouterr().err.lower()
