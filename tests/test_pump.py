import copy
import threading
import time
from dataclasses import replace

from willia.chat import Chat
from willia.client import Reply
from willia.config import Config


class FakeClient:
    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.requests = []
        self.last_usage = {}

    def turn(self, messages, tools, *, on_delta=None):
        self.requests.append(copy.deepcopy(messages))
        reply = self.replies.pop(0) if self.replies else Reply("done", "", [], {}, "stop")
        self.last_usage = reply.usage
        return reply

    def summarize(self, request):
        return "summary"


def open_chat(tmp_path, client=None, **changes):
    config = replace(Config(root=tmp_path), **changes)
    chat = Chat.open(config, client=client or FakeClient())
    chat._drain.join(2)
    return chat


def test_turn_and_drain_engine_spans_never_interleave(tmp_path, monkeypatch):
    chat = open_chat(tmp_path)
    spans = []
    active = []
    overlaps = []
    thread_errors = []
    drain_entered = threading.Event()
    # A race inside either thread would surface as a pytest WARNING, not a failure, so
    # record both the overlap and any thread exception and assert them in this thread.
    monkeypatch.setattr(threading, "excepthook",
                        lambda args: thread_errors.append(args.exc_value))

    def span(name):
        if active:
            overlaps.append((name, list(active)))
        active.append(name)
        spans.append((name, "enter"))
        if name == "drain":
            drain_entered.set()
        time.sleep(0.04)
        spans.append((name, "exit"))
        active.pop()

    def pending(**kwargs):
        span("drain" if threading.current_thread().name == "willia-compaction-drain" else "turn")
        return 0

    def settle(**kwargs):
        span("turn")
        return 0

    monkeypatch.setattr(chat.compactor, "run_pending", pending)
    monkeypatch.setattr(chat.compactor, "settle", settle)
    chat.compactor._pending[:] = [(0, 99)]
    chat.compactor._queued.add((0, 99))
    try:
        drain = chat.start_drain()
        assert drain_entered.wait(1)
        turn = threading.Thread(target=chat.turn, args=(["question"],))
        turn.start()
        turn.join(3)
        assert not turn.is_alive()
        drain.join(2)
        if chat._drain is not None:
            chat._drain.join(2)
        assert not active
        assert overlaps == [], "two engine spans overlapped: the lock did not hold"
        assert thread_errors == [], f"a worker raised: {thread_errors!r}"
        assert all(spans[i][1] == ("enter" if i % 2 == 0 else "exit")
                   for i in range(len(spans)))
    finally:
        chat.compactor._pending.clear()
        chat.compactor._queued.clear()
        chat.close()


def test_turn_join_is_capped_when_drain_outlives_it(tmp_path, monkeypatch):
    model = replace(Config().model, drain_join_s=1)
    chat = open_chat(tmp_path, model=model)
    monkeypatch.setattr(chat.compactor, "settle", lambda **kwargs: 0)
    sleeper = threading.Thread(target=lambda: time.sleep(1.3), daemon=True)
    sleeper.start()
    chat._drain = sleeper
    try:
        started = time.monotonic()
        chat.turn(["question"])
        elapsed = time.monotonic() - started
        assert elapsed < 1.25
        assert sleeper.is_alive()
        sleeper.join(2)
        assert not sleeper.is_alive()
    finally:
        chat.close()


def test_turn_join_sees_short_drain_settle_before_render(tmp_path, monkeypatch):
    client = FakeClient()
    chat = open_chat(tmp_path, client=client)
    settled = threading.Event()
    sleeper = threading.Thread(
        target=lambda: (time.sleep(0.05), settled.set()), daemon=True)
    sleeper.start()
    chat._drain = sleeper
    original_render = chat.view.render

    def render():
        marker = "settled" if settled.is_set() else "unsettled"
        return original_render().replace("</chat>", f"{marker}</chat>")

    monkeypatch.setattr(chat.view, "render", render)
    try:
        chat.turn(["question"])
        assert "settled</chat>" in client.requests[0][1]["content"]
        assert "unsettled" not in client.requests[0][1]["content"]
    finally:
        chat.close()


def test_watchdog_drives_pass_and_logs_one_loud_stuck_line(tmp_path, monkeypatch):
    model = replace(Config().model, watchdog_grace_s=0)
    chat = open_chat(tmp_path, model=model)
    calls = []
    monkeypatch.setattr(chat.view, "settled", lambda: False)
    chat.compactor._pending[:] = [(0, 99)]
    chat.compactor._queued.add((0, 99))

    def no_progress(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(chat.compactor, "run_pending", no_progress)
    try:
        assert chat.check_liveness() is True
        assert chat.check_liveness() is True
        assert len(calls) == 2
        log = (tmp_path / "logs" / "willia.log").read_text(encoding="utf-8")
        assert log.count("WATCHDOG STUCK") == 1
        assert "queued=1" in log
        assert "last_error=none" in log
        assert any("Compaction: stuck" == line for line in chat.status())
    finally:
        chat.compactor._pending.clear()
        chat.compactor._queued.clear()
        chat.close()


def test_start_drain_never_runs_two_threads_at_once(tmp_path, monkeypatch):
    chat = open_chat(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def pending(**kwargs):
        entered.set()
        assert release.wait(2)
        return 0

    monkeypatch.setattr(chat.compactor, "run_pending", pending)
    chat.compactor._pending[:] = [(0, 99)]
    chat.compactor._queued.add((0, 99))
    try:
        first = chat.start_drain()
        assert entered.wait(1)
        second = chat.start_drain()
        assert first is second
        assert first.is_alive()
        release.set()
        first.join(2)
    finally:
        release.set()
        chat.compactor._pending.clear()
        chat.compactor._queued.clear()
        chat.close()


def test_three_turns_finish_with_a_settled_live_view(tmp_path):
    replies = [Reply("answer " + "y" * 80, "", [], {}, "stop") for _ in range(3)]
    client = FakeClient(replies)
    model = replace(Config().model, drain_join_s=1, watchdog_grace_s=0)
    chat = open_chat(
        tmp_path, client=client, model=model, node_bytes=64,
        view_min_bytes=0, view_max_bytes=1)
    try:
        for number in range(3):
            chat.turn([f"question {number} " + "x" * 80])
        chat._drain.join(2)
        with chat._engine():
            assert chat.view.settled() is True
            assert chat.compactor._pending == []
            assert chat.compactor._queued == set()
    finally:
        chat.close()
