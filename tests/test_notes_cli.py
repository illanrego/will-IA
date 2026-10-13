"""Offline coverage for previewing and importing markdown note operands."""

import json

import pytest

from willia import cli
from willia.chat import Chat
from willia.config import Config
from willia.store import Log
from willia.text import split_for_kind
from willia.tree import Tree
from willia.view import View


class CountingClient:
    def __init__(self):
        self.summarizer_calls = 0
        self.last_usage = {}

    def summarize(self, _request):
        self.summarizer_calls += 1
        return "s" * 20


@pytest.fixture
def notes_home(tmp_path, monkeypatch):
    root = tmp_path / ".willia"
    clients = []

    def client(*_args):
        instance = CountingClient()
        clients.append(instance)
        return instance

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("WILLIA_HOME", str(root))
    monkeypatch.delenv("WILLIA_CONFIG", raising=False)
    monkeypatch.setattr("willia.chat.Client", client)
    return root, clients


def write_config(root, **values):
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(json.dumps(values), encoding="utf-8")


def test_notes_preview_reports_exact_cost_without_writing(notes_home, tmp_path, capsys):
    root, _clients = notes_home
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir()
    first = notes_dir / "a.md"
    second = notes_dir / "b.md"
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    root.mkdir()
    view_file = root / "view.json"
    view_file.write_bytes(b"existing view bytes")
    before = view_file.read_bytes()

    assert cli.main(["--notes", str(notes_dir), "--notes-preview"]) == 0

    output = capsys.readouterr().out
    total_bytes = len(first.read_bytes()) + len(second.read_bytes())
    projected = sum(len(split_for_kind(path.read_text(encoding="utf-8"), 512, "note"))
                    for path in (first, second))
    assert str(first) in output
    assert str(second) in output
    assert f"Total bytes: {total_bytes}" in output
    assert f"Projected records: {projected}" in output
    assert f"Projected compaction merges: ~{projected - 1}" in output
    assert not (root / "main").exists()
    assert view_file.read_bytes() == before


def test_note_directory_selection_is_markdown_sorted_and_optionally_recursive(
        notes_home, tmp_path, capsys):
    notes_dir = tmp_path / "notes"
    nested = notes_dir / "nested"
    nested.mkdir(parents=True)
    first = notes_dir / "a.md"
    last = notes_dir / "z.md"
    nested_note = nested / "m.md"
    ignored = notes_dir / "ignored.txt"
    for path in (first, last, nested_note, ignored):
        path.write_text(path.name, encoding="utf-8")

    assert cli.main(["--notes", str(notes_dir), "--notes-preview"]) == 0
    flat = capsys.readouterr().out
    assert flat.index(str(first)) < flat.index(str(last))
    assert str(nested_note) not in flat
    assert str(ignored) not in flat

    assert cli.main([
        "--notes", str(notes_dir), "--notes-recursive", "--notes-preview",
    ]) == 0
    recursive = capsys.readouterr().out
    assert recursive.index(str(first)) < recursive.index(str(nested_note))
    assert recursive.index(str(nested_note)) < recursive.index(str(last))
    assert str(ignored) not in recursive


def test_missing_and_empty_note_selections_are_refused(notes_home, tmp_path, capsys):
    missing = tmp_path / "missing"
    assert cli.main(["--notes", str(missing), "--notes-preview"]) == 1
    assert str(missing) in capsys.readouterr().err

    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["--notes", str(empty), "--notes-preview"]) == 1
    assert str(empty) in capsys.readouterr().err

    assert cli.main(["--notes"]) == 1
    assert "at least one PATH" in capsys.readouterr().err
    assert cli.main(["--notes-preview"]) == 1
    assert "require --notes" in capsys.readouterr().err


def test_real_note_import_persists_records_tree_view_and_backup(
        notes_home, tmp_path, capsys):
    root, clients = notes_home
    note = tmp_path / "one.md"
    note.write_text("a small durable note", encoding="utf-8")

    assert cli.main(["--notes", str(note)]) == 0
    output = capsys.readouterr().out

    with Log(root, read_only=True) as log:
        records = log.range(0, log.count() - 1)
        record_count = log.count()
    tree = Tree(root, read_only=True)
    view = View(tree, records=record_count)
    assert record_count == 1
    assert all(record.kind == "note" for record in records)
    assert tree.get(0, 0) is not None
    assert view._end() == record_count
    assert view.settled() is True
    assert sum(client.summarizer_calls for client in clients) == 0
    assert (root / "backups" / "view.json").exists()
    assert f"files=1 bytes={len(note.read_bytes())} records_added={record_count}" in output
    assert "Tree nodes by level: 0=1" in output
    assert f"View: bytes={len(view.render().encode('utf-8'))} lines=1 settled=yes" in output
    assert "Pending: 0 unbuilt nodes" in output


def test_repeated_note_operand_appends_again_and_only_merges_call_the_model(
        notes_home, tmp_path, capsys):
    root, clients = notes_home
    write_config(root, node_bytes=20)
    note = tmp_path / "repeat.md"
    note.write_text("abcdefghijklm " * 4, encoding="utf-8")
    records_per_copy = len(split_for_kind(note.read_text(encoding="utf-8"), 20, "note"))
    assert records_per_copy == 4

    assert cli.main(["--notes", str(note), str(note)]) == 0
    output = capsys.readouterr().out

    with Log(root, read_only=True) as log:
        records = log.range(0, log.count() - 1)
    assert len(records) == records_per_copy * 2
    assert all(record.kind == "note" for record in records)
    assert [record.text for record in records[:records_per_copy]] == [
        record.text for record in records[records_per_copy:]
    ]
    assert sum(client.summarizer_calls for client in clients) == len(records) - 1
    assert "already present? no dedup - a second import appends again" in output


def test_note_import_appends_without_changing_earlier_record_bytes(
        notes_home, tmp_path):
    root, _clients = notes_home
    chat = Chat.open(Config.load(), client=CountingClient())
    try:
        chat._log_message({"role": "user", "content": "keep these exact bytes"})
        chat.save()
    finally:
        chat.close()
    main_file = next((root / "main").glob("*.jsonl"))
    prefix = main_file.read_bytes()
    with Log(root, read_only=True) as log:
        earlier = log.get(0)

    note = tmp_path / "later.md"
    note.write_text("later note", encoding="utf-8")
    assert cli.main(["--notes", str(note)]) == 0

    assert main_file.read_bytes().startswith(prefix)
    with Log(root, read_only=True) as log:
        assert log.count() == 2
        assert log.get(0) == earlier
        assert log.get(1).kind == "note"


def test_note_import_respects_the_existing_chat_lock(notes_home, tmp_path, capsys):
    root, _clients = notes_home
    note = tmp_path / "locked.md"
    note.write_text("cannot race the owner", encoding="utf-8")
    chat = Chat.open(Config.load(), client=CountingClient())
    try:
        assert cli.main(["--notes", str(note)]) == 1
        assert "locked" in capsys.readouterr().err.lower()
        assert chat.log.count() == 0
    finally:
        chat.close()
