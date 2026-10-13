import copy
import json
import time

import pytest

from willia import jobs
from willia.chat import Chat
from willia.client import Reply
from willia.config import Config
from willia.dispatch import dispatch
from willia.store import Log


class FakeClient:
    def __init__(self):
        self.requests = []
        self.last_usage = {}
        self.on_turn = None

    def turn(self, messages, tools, *, on_delta=None):
        self.requests.append(copy.deepcopy(messages))
        if self.on_turn is not None:
            self.on_turn(len(self.requests))
        return Reply("done", "", [], {}, "stop")

    def summarize(self, request):
        return "summary"


@pytest.fixture
def chat(tmp_path):
    client = FakeClient()
    opened = Chat.open(Config(root=tmp_path), client=client)
    if opened._drain is not None:
        opened._drain.join(2)
    yield opened
    opened.close()


def run(chat, code, *, name="worker", timeout_s=10):
    return jobs.spawn(
        chat=chat, name=name, agent="codex", brief="Do the small task.",
        directory=chat.root, timeout_s=timeout_s,
        command=["python3", "-c", code],
    )


def join(job, timeout=5):
    assert job.thread is not None
    job.thread.join(timeout)
    assert not job.thread.is_alive()


def work_records(chat):
    return [
        record for record in chat.log.range(0, chat.log.count() - 1)
        if record is not None and record.kind == "work"
    ]


def dispatch_args(chat):
    return dict(
        log=chat.log, tree=chat.tree, view=chat.view, root=chat.root,
        node_bytes=chat.config.node_bytes,
    )


def test_success_returns_immediately_and_publishes_one_work_record(chat):
    started = time.monotonic()
    job = run(chat, "print('the report')")
    assert time.monotonic() - started < 1
    join(job)

    assert (job.dir / "brief.md").read_text() == "Do the small task."
    assert job.log_path.read_text() == "the report\n"
    assert job.report_path.read_text() == "the report\n"
    records = work_records(chat)
    assert len(records) == 1
    assert records[0].text == f"[{job.label}] the report"


def test_nonzero_exit_publishes_failure_and_log_tail(chat):
    job = run(chat, "import sys; print('last detail', file=sys.stderr); sys.exit(3)")
    join(job)
    records = work_records(chat)
    assert len(records) == 1
    assert records[0].text.startswith(f"[{job.label}] failed: exit 3")
    assert "last detail" in records[0].text


def test_empty_output_is_a_named_failure(chat):
    job = run(chat, "pass")
    join(job)
    records = work_records(chat)
    assert len(records) == 1
    assert records[0].text == f"[{job.label}] failed: no report"


def test_timeout_kills_process_group_and_finishes_quickly(chat):
    started = time.monotonic()
    job = run(chat, "import time; time.sleep(30)", timeout_s=1)
    join(job, timeout=8)
    assert time.monotonic() - started < 10
    assert job.timed_out is True
    assert job.process.poll() is not None
    records = work_records(chat)
    assert len(records) == 1
    assert records[0].text.startswith(f"[{job.label}] failed: timeout after 1s")


def test_child_chat_holds_brief_log_report_and_zoom_opens_it(chat):
    job = run(chat, "print('child report')", name="Child")
    join(job)
    child_root = chat.root / "agents" / job.label
    assert (child_root / "view.json").is_file()
    with Log(child_root, read_only=True) as child_log:
        records = child_log.range(0, child_log.count() - 1)
    assert [record.kind for record in records] == ["user", "echo", "will"]
    assert records[0].text == "Do the small task."
    assert records[1].text == "child report\n"
    assert records[2].text == "child report"

    result = json.loads(dispatch("zoom", {"id": job.label}, **dispatch_args(chat)))
    assert result["name"] == job.label
    assert result["scope"] == job.label
    assert "child report" in result["chat"]


def test_delivery_reaches_one_later_request_without_user_log_duplication(chat):
    client = chat.client
    holder = {}

    def finish_during_first_turn(number):
        if number == 1:
            holder["job"] = run(chat, "print('delivered report')", name="Delivery")
            join(holder["job"])

    client.on_turn = finish_during_first_turn
    chat.turn(["first question"])
    client.on_turn = None
    chat.turn(["second question"])
    chat.turn(["third question"])

    delivered = f"[{holder['job'].label}] delivered report"
    request_contents = [
        message["content"] for request in client.requests for message in request
        if message["role"] == "user"
    ]
    assert request_contents.count(delivered) == 1
    users = [
        record.text for record in chat.log.range(0, chat.log.count() - 1)
        if record is not None and record.kind == "user"
    ]
    assert delivered not in users
    assert len(work_records(chat)) == 1


def test_requested_name_collision_gets_numeric_suffix(chat):
    first = run(chat, "print('one')", name="Same")
    second = run(chat, "print('two')", name="Same")
    assert first.label == "Same"
    assert second.label == "Same-2"
    join(first)
    join(second)


def test_dispatch_missing_command_binary_creates_no_job_directory(chat):
    before = list(chat.config.jobs_dir.iterdir())
    result = json.loads(dispatch(
        "delegate_codex", {"task": "brief", "name": "Missing"},
        chat=chat, command=["/definitely/not/a/delegate"],
        **dispatch_args(chat),
    ))
    assert "not found" in result["error"]
    assert list(chat.config.jobs_dir.iterdir()) == before


def test_dispatch_validates_frozen_schema_and_bad_directory(chat):
    base = dispatch_args(chat) | {"chat": chat, "command": ["python3", "-c", "print('ok')"]}
    assert json.loads(dispatch("delegate_codex", {"task": ""}, **base)) == {
        "error": "task must be a nonempty string"}
    for bad in ("gpt-4-legacy", "gpt-6-sol"):
        assert "model must be one of" in json.loads(dispatch(
            "delegate_codex", {"task": "x", "model": bad}, **base))["error"]
    # The enum names the account's real catalog (gpt-5.5 / gpt-5.6-sol / gpt-6-astra);
    # a name inside it must spawn, not be refused.
    accepted = json.loads(dispatch(
        "delegate_codex", {"task": "x", "model": "gpt-5.6-sol", "name": "Accepted"}, **base))
    assert accepted.get("status") == "started", accepted
    assert "does not exist" in json.loads(dispatch(
        "delegate_codex", {"task": "x", "dir": str(chat.root / "absent")},
        **base,
    ))["error"]


def test_status_lists_live_jobs_and_startup_orphans(chat):
    orphan = chat.config.jobs_dir / "old-20260101T000000Z"
    orphan.mkdir()
    chat._startup_orphans = jobs.orphaned(chat)
    job = run(chat, "import time; time.sleep(30)", name="Live", timeout_s=1)
    status = next(line for line in chat.status() if line.startswith("Jobs:"))
    assert "Live (codex, running" in status
    assert orphan.name in status
    join(job, timeout=8)


def test_frozen_commands_have_exact_argument_order(tmp_path, monkeypatch):
    brief = tmp_path / "brief.md"
    brief.write_text("the brief")
    report = tmp_path / "report.md"
    monkeypatch.setattr(jobs, "_codex_binary", lambda: tmp_path / "codex")
    assert jobs._command(
        "codex", brief_path=brief, report_path=report, directory=tmp_path,
    ) == [
        str(tmp_path / "codex"), "exec", "-m", "gpt-5.6-sol",
        "-c", 'model_reasoning_effort="high"', "--approve-for-me",
        "--skip-git-repo-check",
        "-C", str(tmp_path), "-o", str(report), "the brief",
    ]
    # A chosen model passes through unchanged: the schema enum already refused
    # every spelling outside the catalog, so nothing is translated here.
    assert jobs._command(
        "codex", brief_path=brief, report_path=report, directory=tmp_path,
        model="gpt-6-astra",
    )[3] == "gpt-6-astra"
    monkeypatch.setattr(jobs.shutil, "which", lambda name: "/bin/hermes")
    assert jobs._command(
        "hermes", brief_path=brief, report_path=report, directory=tmp_path,
    ) == [
        "/bin/hermes", "chat", "--oneshot", "--query-file", str(brief),
        "--format", "text", "--in", str(tmp_path),
    ]
