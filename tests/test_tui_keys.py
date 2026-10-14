import time
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from willia.store import Record
from willia.tree import Line as TreeLine
from willia import cli
from willia.config import Config
from willia.tui import build_rail_facts
from willia.tui.app import App, Mode, Pane
from willia.tui.render import cell_width
from willia.tui.screen import Screen

RAIL_LABEL_CELLS = 9


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
    press(app, "i", "CTRL_U", "o", "n", "e", " ", "t", "w", "o", "CTRL_W")
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


def test_focus_rail_selection_fold_and_contextual_hint():
    facts = [
        ("#memory", "", "dim"), ("l0", "20", "data"), ("l1", "10", "data"),
        ("#view", "", "dim"), ("state", "settled · 2 unbuilt", "amber"),
        ("queue", "2", "data"),
    ]
    app = App(FakeChat(), FakeScreen(), rail_facts=facts)
    assert app.focus == Pane.TRANSCRIPT
    assert "transcript" in app._status()
    app.handle_key("TAB")
    assert app.focus == Pane.RAIL
    assert "memory tree" in app._status()
    app.handle_key("j")
    assert app.rail_index == 1
    assert "One line per message" in app._status()
    app.handle_key("ENTER")
    assert "#memory" in app.collapsed_groups
    assert [fact[0] for fact in app._visible_rail_facts()] == [
        "#memory", "#view", "state", "queue"]
    app.handle_key("ESC")
    assert "#memory" not in app.collapsed_groups


def test_transcript_fold_targets_only_the_record_under_the_cursor():
    chat = FakeChat()
    chat.log.records = [
        Record(0, "user", "first line\nsecond line", 22, "2026-10-14T00:00:00Z"),
        Record(1, "user", "separate record\nwith tail", 25, "2026-10-14T00:00:00Z"),
    ]
    app = App(chat, FakeScreen())
    assert app._focused_transcript_line().record_id == 1
    app.handle_key("ENTER")
    assert app.collapsed_records == {1}
    lines = app._transcript(app._body_size()[2])
    assert [line.text for line in lines] == [
        "─" * 20, "ILLAN", "first line", "second line",
        "─" * 20, "ILLAN", "separate record",
    ]
    app.handle_key("ESC")
    assert app.collapsed_records == set()


def test_ctrl_w_moves_directly_between_panes_and_within_the_rail():
    app = App(FakeChat(), FakeScreen(), rail_facts=[
        ("#memory", "", "dim"), ("l0", "20", "data")])
    press(app, "CTRL_W", "h")
    assert app.focus == Pane.RAIL
    press(app, "CTRL_W", "j")
    assert app.rail_index == 1
    press(app, "CTRL_W", "l")
    assert app.focus == Pane.TRANSCRIPT


def test_q_help_and_unknown_commands():
    app = App(FakeChat(), FakeScreen())
    press(app, ":", "h", "e", "l", "p", "ENTER")
    assert app.help_open is True
    app.handle_key("q")
    assert app.help_open is False
    press(app, ":", "n", "o", "p", "e", "ENTER")
    assert "Unknown command" in app.notice
    press(app, ":", "q", "ENTER")
    assert app.running is False


def test_line_record_and_visual_range_yanks_use_log_text():
    class CopyScreen(FakeScreen):
        def __init__(self):
            self.copied = []

        def copy(self, text):
            self.copied.append(text)

    chat = FakeChat()
    chat.log.records = [Record(
        0, "user", "alpha\nbeta\ngamma", 16, "2026-10-14T00:00:00Z")]
    screen = CopyScreen()
    app = App(chat, screen)

    app.handle_key("y")
    assert screen.copied[-1] == "gamma"
    app.handle_key("Y")
    assert screen.copied[-1] == "alpha\nbeta\ngamma"
    press(app, "v", "k", "y")
    assert screen.copied[-1] == "beta\ngamma"
    assert app.visual_anchor is None
    assert app.notice == "yanked 10 bytes"


def test_help_overlay_scrolls_and_closes_without_touching_transcript_scroll():
    app = App(FakeChat(), FakeScreen())
    app.handle_key("k")
    before = app.scroll_offset
    app.handle_key("?")
    assert app.help_open is True
    app.handle_key("j")
    assert app.help_scroll == 1
    assert app.scroll_offset == before
    app.handle_key("ESC")
    assert app.help_open is False
    assert app.scroll_offset == before


def test_theme_command_repaints_with_new_sgr_and_refuses_unknown_names():
    class ColourScreen(FakeScreen):
        def __init__(self):
            self.writes = []

        def draw(self, lines, theme):
            Screen(input_fd=-1, writer=self.writes.append, depth=24).draw(lines, theme)

    screen = ColourScreen()
    app = App(FakeChat(), screen)
    app.redraw(force=True)
    blue = screen.writes[-1]
    press(app, ":", "t", "h", "e", "m", "e", " ", "g", "r", "e", "e", "n", "ENTER")
    app.redraw()
    green = screen.writes[-1]
    assert app.theme == "green"
    assert blue != green
    assert "\x1b[48;2;5;10;9m" in green

    press(app, ":", "t", "h", "e", "m", "e", " ", "n", "o", "p", "e", "ENTER")
    assert app.theme == "green"
    assert app.notice == "unknown theme: nope"


def test_tui_theme_config_defaults_to_blue_and_loads_a_choice(tmp_path):
    assert Config.load(tmp_path / "missing.json").tui.theme == "blue"
    path = tmp_path / "config.json"
    path.write_text('{"tui":{"theme":"mixed"}}', encoding="utf-8")
    assert Config.load(path).tui.theme == "mixed"


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
    assert [line.text for line in app._transcript(20)] == ["─" * 20, "NOTE", "memory"]


def test_every_rail_row_explains_itself(tmp_path):
    """A mute row is a dead end: every label the rail actually produces needs a hint."""
    node = TreeLine(0, 0, "user: hello", 11)
    tree = SimpleNamespace(nodes=lambda: {(0, 0): node}, get=lambda *key: node)
    view = SimpleNamespace(render=lambda: "<chat>\n0+1|user: hello\n</chat>",
                           settled=lambda: True, lines=lambda: [node])
    chat = SimpleNamespace(
        _engine=nullcontext, tree=tree, view=view,
        compactor=SimpleNamespace(_pending=[]),
        config=SimpleNamespace(view_min_bytes=64_000, view_max_bytes=128_000,
                               model=SimpleNamespace(model="deepseek-v4.1-flash")),
        root=tmp_path, session="1234567890", log=SimpleNamespace(count=lambda: 1),
    )
    # Built by the real builder: a row added or renamed there cannot ship without a hint, or with
    # a label the rail's column would truncate.
    facts = build_rail_facts(
        chat,
        {"rolling": {"percent": 3, "resetsAt": "2026-10-14T04:00:00Z"}},
        {"primary": {"label": "5h", "percent": 12, "resets_in_s": 900},
         "secondary": {"label": "7d", "percent": 18, "resets_in_s": 900}},
        now=datetime(2026, 10, 14, tzinfo=timezone.utc),
    )
    app = App(FakeChat(), FakeScreen(), rail_facts=facts)
    app.handle_key("TAB")
    assert app.focus.value == "rail"
    mute, wide = [], []
    for _ in range(len(facts) + 2):
        identity = app._selected_rail_identity()
        label = identity[0] if identity else ""
        if not app._focused_hint():
            mute.append(label)
        if label and not label.startswith("#") and cell_width(label) > RAIL_LABEL_CELLS:
            wide.append(label)
        app.handle_key("j")
    assert not mute, f"rail rows with no explanation: {mute}"
    assert not wide, f"rail labels wider than the {RAIL_LABEL_CELLS}-cell column: {wide}"


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
