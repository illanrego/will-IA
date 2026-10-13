import shutil

import pytest

from willia import cli
from willia.client import Reply
from willia.store import Log
from willia.tree import Tree
from willia.view import View


class FakeClient:
    last_usage = {}

    def turn(self, messages, tools, *, on_delta=None):
        return Reply("done", "", [], {}, "stop")

    def summarize(self, request):
        return "summary"


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / ".willia"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("WILLIA_HOME", str(root))
    monkeypatch.delenv("WILLIA_CONFIG", raising=False)
    monkeypatch.setattr("willia.chat.Client", lambda *_: FakeClient())
    return root


def make_state(root, records, covered, *, built=None):
    tree = Tree(root)
    view = View(tree)
    with Log(root) as log:
        for i in range(records):
            log.append("user", f"record {i}")
    for i in range(records if built is None else built):
        tree.put(0, i, f"user: record {i}")
    tree.save()
    for i in range(covered):
        view.add_root(i)
    view.save()
    return tree, view


def test_restore_adopts_real_backup_and_advances_missing_roots(home, capsys):
    _, view = make_state(home, records=4, covered=2)
    backup = home / "backups" / "view.json"
    backup.parent.mkdir(parents=True)
    shutil.copyfile(home / "view.json", backup)
    view.add_root(2)
    view.add_root(3)
    view.save()

    assert cli.main(["--restore-view"]) == 0

    restored = View(Tree(home, read_only=True), records=4)
    assert restored._end() == 4
    assert "covered_end=2 records=4 roots_added=2" in capsys.readouterr().out


def test_restore_refuses_backup_beyond_log_without_writing_view(home, capsys):
    tree, view = make_state(home, records=1, covered=1)
    before = (home / "view.json").read_bytes()
    tree.put(0, 1, "user: future")
    tree.save()
    view.add_root(1)
    view.save()
    backup = home / "backups" / "view.json"
    backup.parent.mkdir(parents=True)
    shutil.copyfile(home / "view.json", backup)
    (home / "view.json").write_bytes(before)

    assert cli.main(["--restore-view"]) != 0
    assert "covers 2 records" in capsys.readouterr().err
    assert (home / "view.json").read_bytes() == before


def test_restore_refuses_unbuilt_pair_without_writing_view(home, capsys):
    _, _ = make_state(home, records=1, covered=1, built=0)
    path = home / "view.json"
    before = path.read_bytes()
    backup = home / "backups" / "view.json"
    backup.parent.mkdir(parents=True)
    shutil.copyfile(path, backup)

    assert cli.main(["--restore-view"]) != 0
    assert "no built tree node" in capsys.readouterr().err
    assert path.read_bytes() == before


@pytest.mark.parametrize("corrupt", [False, True])
def test_restore_refuses_absent_or_corrupt_backup_without_writing_view(
        home, corrupt, capsys):
    make_state(home, records=0, covered=0)
    path = home / "view.json"
    before = path.read_bytes()
    if corrupt:
        backup = home / "backups" / "view.json"
        backup.parent.mkdir(parents=True)
        backup.write_text("{not json", encoding="utf-8")

    assert cli.main(["--restore-view"]) != 0
    error = capsys.readouterr().err.lower()
    assert ("corrupt" if corrupt else "absent") in error
    assert path.read_bytes() == before
