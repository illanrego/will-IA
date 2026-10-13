import io
import threading

import pytest

from willia import cli, repl
from willia.chat import Chat
from willia.client import Reply, ToolCall
from willia.config import Config
from willia.store import Log


class FakeClient:
    last_usage = {}

    def turn(self, messages, tools, *, on_delta=None):
        return Reply("done", "", [], {}, "stop")

    def summarize(self, request):
        return "s" * 512


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("WILLIA_HOME", str(tmp_path / ".willia"))
    monkeypatch.delenv("WILLIA_CONFIG", raising=False)
    monkeypatch.setattr("willia.chat.Client", lambda *_: FakeClient())
    return tmp_path


def test_status_on_fresh_root(home, capsys):
    assert cli.main(["--status"]) == 0
    output = capsys.readouterr().out.lower()
    for field in ("root", "session", "records", "view bytes", "unbuilt nodes", "children", "last usage"):
        assert field in output
    assert str(home / ".willia") in output


def test_new_archives_whole_root(home, monkeypatch):
    chat = Chat.open(Config.load(), client=FakeClient())
    chat.turn(["keep me"])
    chat.close()
    monkeypatch.setattr("sys.stdin", io.StringIO("/quit\n"))
    assert cli.main(["--new"]) == 0
    archives = list((home / ".willia-archive").iterdir())
    assert len(archives) == 1
    assert (archives[0] / "prompt.md").exists()
    with Log(archives[0], read_only=True) as old:
        assert old.count() == 2
    with Log(home / ".willia", read_only=True) as new:
        assert new.count() == 0


def test_help_and_unknown_flags_write_nothing(home, capsys):
    assert cli.main(["--help"]) == 0
    assert "usage:" in capsys.readouterr().out.lower()
    assert cli.main(["--unknown"]) != 0
    assert "usage:" in capsys.readouterr().err.lower()
    assert cli.main(["--restore-view"]) != 0
    assert cli.main(["--sta"]) != 0
    assert not (home / ".willia").exists()


def test_locked_new_is_refused(home, capsys):
    chat = Chat.open(Config.load(), client=FakeClient())
    try:
        assert cli.main(["--new"]) != 0
        assert "locked" in capsys.readouterr().err.lower()
        assert not (home / ".willia-archive").exists()
    finally:
        chat.close()


def test_repl_buffers_pastes_commands_and_eof(home, monkeypatch, capsys):
    chat = Chat.open(Config.load(), client=FakeClient())
    monkeypatch.setattr("sys.stdin", io.StringIO(
        "/help\n/status\n\nfirst\\\nsecond\n/status\n\nlast\n"))
    try:
        repl.run(chat)
        with Log(chat.config.root, read_only=True) as log:
            users = [r.text for r in log.range(0, log.count() - 1) if r.kind == "user"]
        assert users == ["first\nsecond\n/status", "last"]
        assert "goodbye" in capsys.readouterr().out.lower()
    finally:
        chat.close()


def test_repl_reader_feeds_running_turn_without_touching_memory(home, monkeypatch):
    requested = threading.Event()
    supplied = threading.Event()

    class Input:
        def __iter__(self):
            yield "first\n"
            yield "\n"
            assert requested.wait(3)
            yield "during\n"
            yield "\n"
            supplied.set()
            yield "/quit\n"

    class Client(FakeClient):
        def __init__(self):
            self.requests = []

        def turn(self, messages, tools, *, on_delta=None):
            self.requests.append(list(messages))
            if len(self.requests) == 1:
                requested.set()
                assert supplied.wait(3)
                return Reply("", "", [ToolCall("a", "date", {"id": 0})], {}, "tool_calls")
            return super().turn(messages, tools, on_delta=on_delta)

    client = Client()
    chat = Chat.open(Config.load(), client=client)
    owner = threading.get_ident()
    append = chat.log.append

    def checked_append(*args):
        assert threading.get_ident() == owner
        return append(*args)
    monkeypatch.setattr(chat.log, "append", checked_append)
    monkeypatch.setattr("sys.stdin", Input())
    try:
        repl.run(chat)
        assert client.requests[1][-1] == {"role": "user", "content": "during"}
    finally:
        chat.close()
