import base64
import copy

import pytest

from willia.chat import Chat
from willia.client import Reply
from willia.config import Config
from willia.tui.clipboard import copy_text
from willia.tui.screen import (
    ALT_OFF, ALT_ON, CURSOR_HIDE, CURSOR_SHOW, SYNC_OFF, SYNC_ON, Screen, decode_key,
)
from willia.tui.theme import ansi_colour


class FakeClient:
    def __init__(self):
        self.last_usage = {}

    def turn(self, messages, tools, *, on_delta=None):
        reply = Reply("answer", "thinking", [], {"prompt_tokens": 9}, "stop")
        self.last_usage = copy.deepcopy(reply.usage)
        if on_delta:
            on_delta("reasoning", reply.reasoning)
            on_delta("content", reply.content)
        return reply

    def summarize(self, request):
        return "s" * 512


def test_alt_screen_enter_leave_and_exception_restore():
    writes = []
    with pytest.raises(RuntimeError):
        with Screen(input_fd=-1, writer=writes.append, depth=24):
            raise RuntimeError("boom")
    output = "".join(writes)
    assert ALT_ON + CURSOR_HIDE in output
    assert ALT_OFF + CURSOR_SHOW in output
    assert output.index(ALT_ON) < output.index(ALT_OFF)
    assert output.count(CURSOR_SHOW) == 1


def test_every_nonempty_paint_is_synchronised_and_empty_paint_writes_nothing():
    writes = []
    screen = Screen(input_fd=-1, writer=writes.append, depth=24)

    screen.draw(["one", "two"])

    assert len(writes) == 1
    assert writes[0].startswith(SYNC_ON)
    assert writes[0].endswith(SYNC_OFF)
    assert writes[0].count(SYNC_ON) == writes[0].count(SYNC_OFF) == 1
    assert CURSOR_SHOW not in writes[0]

    before = "".join(writes)
    screen.draw([])
    after = "".join(writes)
    assert after == before
    assert after.count(SYNC_ON) == after.count(SYNC_OFF) == 1


@pytest.mark.parametrize(("raw", "key"), [
    (b"a", "a"), ("界".encode(), "界"), (b"\r", "ENTER"), (b"\n", "CTRL_J"),
    (b"\x1b", "ESC"), (b"\t", "TAB"), (b"\x7f", "BACKSPACE"),
    (b"\x03", "CTRL_C"), (b"\x1b[A", "UP"), (b"\x1b[B", "DOWN"),
    (b"\x1b[H", "HOME"), (b"\x1b[F", "END"),
    (b"\x1b[5~", "PGUP"), (b"\x1b[6~", "PGDN"),
])
def test_key_decoding(raw, key):
    assert decode_key(raw) == key


def test_colour_degradation_has_256_and_8_colour_sequences():
    assert ansi_colour("#8FDCFF", 256).startswith("\x1b[38;5;")
    assert ansi_colour("#8FDCFF", 8) in {f"\x1b[{code}m" for code in range(30, 38)}
    assert ansi_colour("#8FDCFF", 24) == "\x1b[38;2;143;220;255m"


def test_clipboard_writes_osc52_with_base64_of_the_utf8_payload_only():
    writes = []
    text = "what was said — exactly"
    Screen(input_fd=-1, writer=writes.append, depth=24).copy(text)
    expected = base64.b64encode(text.encode("utf-8")).decode("ascii")
    assert writes == [f"\x1b]52;c;{expected}\x07"]


def test_clipboard_fallback_failure_is_silent():
    def fail(*_args, **_kwargs):
        raise OSError("clipboard unavailable")

    copy_text(
        "safe", fail, environ={"WAYLAND_DISPLAY": "wayland-0"},
        which=lambda _name: "/missing/wl-copy", runner=fail,
    )


def test_sink_none_preserves_the_existing_stdout(tmp_path, capsys):
    chat = Chat.open(Config(root=tmp_path), client=FakeClient())
    try:
        chat.turn(["question"], sink=None)
        assert capsys.readouterr().out == (
            "thinkinganswer\n"
            "prompt_tokens=9 cached_tokens=0 reasoning_tokens=0\n"
        )
    finally:
        chat.close()


def test_sink_receives_deltas_and_end_without_stdout(tmp_path, capsys):
    chat = Chat.open(Config(root=tmp_path), client=FakeClient())
    events = []
    try:
        chat.turn(["question"], sink=lambda event, **data: events.append((event, data)))
        assert capsys.readouterr().out == ""
        assert [event for event, _data in events] == ["delta", "delta", "end"]
        assert events[0][1] == {"kind": "reasoning", "text": "thinking"}
    finally:
        chat.close()
