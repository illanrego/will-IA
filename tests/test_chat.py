import copy
import json
import queue
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from willia.chat import Chat
from willia.client import Reply, ToolCall
from willia.config import Config
from willia.store import Log, LogLockedError
from willia.tree import Tree
from willia.view import View, ViewStateUnavailable


def reply(content="", calls=(), reasoning=""):
    return Reply(content, reasoning, list(calls), {"prompt_tokens": 9}, "stop")


class FakeClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.summaries = []
        self.last_usage = {}
        self.on_round = None

    def turn(self, messages, tools, *, on_delta=None):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        if self.on_round:
            self.on_round(len(self.requests))
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        self.last_usage = result.usage
        if on_delta:
            on_delta("reasoning", result.reasoning)
            on_delta("content", result.content)
        return result

    def summarize(self, request):
        self.summaries.append(request)
        return "s" * 512


@pytest.fixture
def opened(tmp_path):
    chats = []

    def open_chat(client=None, **options):
        chat = Chat.open(replace(Config(root=tmp_path), **options), client=client or FakeClient())
        chats.append(chat)
        return chat

    yield open_chat
    for chat in chats:
        chat.close()


def test_render_before_log_frozen_view_and_tool_wire(opened):
    raw = '{ "id" : 0 }'
    client = FakeClient(reply(calls=[ToolCall("call-1", "zoom", raw)]), reply("answer"))
    chat = opened(client)
    chat.turn(["new question"])
    first, second = [request for request, _ in client.requests]
    assert first[1] == {"role": "assistant", "content": "<chat>\n</chat>"}
    assert "new question" not in first[1]["content"]
    assert first[1]["content"].encode() == second[1]["content"].encode()
    assert second[3] == {"role": "assistant", "content": "", "tool_calls": [
        {"id": "call-1", "type": "function", "function": {"name": "zoom", "arguments": raw}}]}
    assert second[4]["tool_call_id"] == "call-1"
    assert json.loads(second[4]["content"])["text"] == "new question"
    assert [chat.log.get(i).kind for i in range(chat.log.count())] == ["user", "tool", "echo", "will"]
    assert client.requests[0][1] == client.requests[1][1] == chat.tools
    assert first[0]["content"] == chat.system == chat.compactor.system


def test_long_user_paste_is_lossless(opened):
    client = FakeClient(reply("done"))
    chat = opened(client)
    text = "é long paste\n" * 150
    chat.turn([text])
    users = [r.text for r in chat.log.range(0, chat.log.count() - 1) if r.kind == "user"]
    assert len(users) > 1
    assert "".join(users) == text
    assert [m["content"] for m in client.requests[0][0] if m["role"] == "user"] == users
    assert all(len(("user: " + chunk).encode()) <= 512 for chunk in users)


def test_inbox_is_drained_between_rounds_in_order(opened):
    client = FakeClient(reply(calls=[ToolCall("a", "date", {"id": 0})]), reply("done"))
    chat = opened(client)
    chat.inbox = queue.Queue()

    def enqueue(round_number):
        if round_number == 1:
            chat.inbox.put("later one")
            chat.inbox.put("later two")
    client.on_round = enqueue
    chat.turn(["first"])
    messages = client.requests[1][0]
    assert messages[-2:] == [{"role": "user", "content": "later one"},
                             {"role": "user", "content": "later two"}]
    assert [r.text for r in chat.log.range(0, 9) if r.kind == "user"] == ["first", "later one", "later two"]


def test_fresh_start_and_backup(opened):
    chat = opened()
    root = chat.config.root
    assert (root / "prompt.md").read_text()
    assert (root / "view.json").is_file()
    assert not list(root.rglob("*journal*"))
    assert all((root / d).is_dir() for d in ("main", "tree", "assets", "agents", "jobs", "backups", "logs"))
    assert "startup" in (root / "logs" / "willia.log").read_text().lower()
    chat.end_turn()
    assert json.loads((root / "backups/view.json").read_text()) == json.loads((root / "view.json").read_text())


@pytest.mark.parametrize("days", [1, 3])
def test_startup_reconciles_all_day_files(tmp_path, days, monkeypatch):
    View(Tree(tmp_path)).save()
    with Log(tmp_path) as log:
        for day in range(1, days + 1):
            class Clock:
                @staticmethod
                def now(tz):
                    return datetime(2026, 1, day, tzinfo=timezone.utc)
            monkeypatch.setattr("willia.store.datetime", Clock)
            log.append("user", "message " + str(day))
    chat = Chat.open(Config(root=tmp_path), client=FakeClient())
    try:
        assert chat.view._end() == chat.log.count() == days
        assert all(chat.tree.get(0, i) for i in range(days))
    finally:
        chat.close()


def test_startup_reseeds_missing_long_node_with_shared_anchor(tmp_path):
    with Log(tmp_path) as log:
        log.append("echo", "x" * 1000)
    view = View(Tree(tmp_path))
    view.add_root(0)
    view.save()
    client = FakeClient()
    chat = Chat.open(Config(root=tmp_path), client=client)
    try:
        assert chat.tree.get(0, 0) is not None
        assert client.summaries[0].system == chat.system
        assert client.summaries[0].tools == chat.tools
    finally:
        chat.close()


def test_missing_view_writes_nothing_even_with_unsealed_log(tmp_path):
    with Log(tmp_path) as log:
        log.append("user", "saved")
    path = next((tmp_path / "main").glob("*.jsonl"))
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    dirs = set(tmp_path.rglob("*"))
    with pytest.raises(ViewStateUnavailable, match="willia --restore-view") as error:
        Chat.open(Config(root=tmp_path), client=FakeClient())
    assert "nothing was written" in str(error.value).lower()
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert set(tmp_path.rglob("*")) == dirs


def test_locked_chat_raises_clear_error(opened):
    chat = opened()
    with pytest.raises(LogLockedError, match="locked"):
        Chat.open(chat.config, client=FakeClient())


def test_settle_never_uses_model_and_thoughts_are_not_logged(opened, monkeypatch, capsys):
    client = FakeClient(reply(reasoning="private"), reply(reasoning="still private"))
    chat = opened(client)
    calls = []
    monkeypatch.setattr(chat.compactor, "settle", lambda **kw: calls.append(kw))
    chat.turn(["question"])
    assert calls == [{"max_nodes": 64, "timeout_s": 20.0, "model_calls": False}]
    assert chat.log.count() == 1
    assert "private" not in chat.view.render()
    assert "prompt_tokens=9" in capsys.readouterr().out


def test_next_turn_rebuilds_request_and_keeps_prompt(opened):
    client = FakeClient(reply("first answer"), reply("second answer"))
    chat = opened(client)
    chat.turn(["first"])
    chat.turn(["second"])
    messages = client.requests[1][0]
    assert len(messages) == 3
    assert messages[-1] == {"role": "user", "content": "second"}
    assert messages[0] == client.requests[0][0][0]


def test_failed_api_call_preserves_input_and_publishes_view(opened, capsys):
    from willia.client import ClientError

    chat = opened(FakeClient(ClientError(500, "unavailable")))
    chat.turn(["remember despite failure"])
    assert chat.log.count() == 1
    assert chat.log.get(0).text == "remember despite failure"
    assert "unavailable" in capsys.readouterr().out
    assert json.loads(chat.config.view_backup_file.read_text()) == json.loads(
        chat.config.view_file.read_text())


def test_existing_prompt_and_session_survive_reopen(tmp_path):
    config = Config(root=tmp_path)
    config.prompt_file.write_text("My fixed instructions", encoding="utf-8")
    chat = Chat.open(config, client=FakeClient())
    session, system = chat.session, chat.system
    chat.close()
    reopened = Chat.open(config, client=FakeClient())
    try:
        assert reopened.session == session
        assert reopened.system == system
        assert config.prompt_file.read_text() == "My fixed instructions"
    finally:
        reopened.close()


def test_end_turn_pump_has_admission_deadline_and_saves_new_nodes(opened, monkeypatch):
    chat = opened()
    calls = []

    def pending(**kwargs):
        assert chat.config.view_backup_file.exists()
        calls.append(kwargs)
        chat.tree.put(0, 0, "user: queued")
        return 1

    chat.log.append("user", "queued")
    chat.view.add_root(0)
    monkeypatch.setattr(chat.compactor, "run_pending", pending)
    monkeypatch.setattr("willia.chat.time.monotonic", lambda: 100.0)
    chat.end_turn()
    assert calls == [{"limit": 8, "deadline": 120.0, "model_calls": True}]
    assert Tree(chat.root, read_only=True).get(0, 0).text == "user: queued"
