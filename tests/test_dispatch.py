import json

import pytest

from willia.dispatch import dispatch
from willia.store import Log
from willia.tree import Tree
from willia.view import View


@pytest.fixture
def chat(tmp_path):
    with Log(tmp_path) as log:
        tree = Tree(tmp_path)
        view = View(tree)
        for text in ("first", "second"):
            i = log.append("user", text)
            tree.put(0, i, "user: " + text)
            view.add_root(i)
        tree.put(1, 0, "both")
        tree.save()
        view.save()
        yield dict(log=log, tree=tree, view=view, root=tmp_path, node_bytes=512)


def call(chat, name, arguments):
    return json.loads(dispatch(name, arguments, **chat))


def test_navigation_payloads(chat):
    assert call(chat, "zoom", {"id": 0}) == {
        "id": 0, "n": 1, "kind": "user", "scope": None, "text": "first", "media": []}
    assert call(chat, "zoom", {"id": 0, "n": 2}) == {
        "id": 0, "n": 2, "scope": None, "halves": [
            {"id": 0, "n": 1, "text": "user: first"},
            {"id": 1, "n": 1, "text": "user: second"}]}
    assert call(chat, "date", {"id": 0}) == {
        "id": 0, "date": chat["log"].get(0).date, "scope": None}


@pytest.mark.parametrize("name,args,error", [
    ("zoom", {"id": -1}, "id must be a string or nonnegative integer; n must be a positive integer"),
    ("zoom", {"id": 0, "n": 3}, "n must be a power of two"),
    ("zoom", {"id": 1, "n": 2}, "id must be a multiple of n"),
    ("zoom", {"id": 9}, "message does not exist"),
    ("zoom", {"id": 0, "n": 4}, "span does not exist"),
    ("zoom", {"id": "../bad"}, "unknown subagent name"),
    ("zoom", {"id": "missing"}, "subagent chat does not exist"),
    ("date", {"id": "a"}, "id must be a nonnegative integer"),
    ("date", {"id": 9}, "message does not exist"),
    ("zoom", {"id": "a", "scope": "b"}, "a string id opens its own chat; do not pass scope with it"),
    ("zoom", {"id": "a", "scope": ""}, "scope must be a nonempty subagent name"),
    ("zoom", {"id": 0, "scope": None}, "scope must be a nonempty subagent name"),
    ("date", {"id": 0, "scope": 3}, "scope must be a nonempty subagent name"),
    ("date", {"id": 0, "scope": "../bad"}, "unknown scope: '../bad'"),
    ("zoom", {"id": 0, "scope": "missing"}, "scope 'missing' has no chat"),
])
def test_errors(chat, name, args, error):
    assert call(chat, name, args) == {"error": error}


@pytest.mark.parametrize("name", ["delegate_codex", "delegate_hermes", "web_search", "web_extract", "vision"])
def test_unimplemented(chat, name):
    assert call(chat, name, {}) == {"error": "not implemented yet: " + name}


def test_unknown_and_bad_arguments(chat):
    assert call(chat, "nope", {}) == {"error": "unknown tool: nope"}
    assert "error" in call(chat, "zoom", "not json")
    assert "error" in call(chat, "zoom", [])
    assert call(chat, "zoom", '{"id": 0}')["text"] == "first"


def test_unbuilt_span(chat):
    chat["tree"] = Tree(chat["root"] / "empty")
    assert call(chat, "zoom", {"id": 0, "n": 2}) == {"error": "span is not summarized yet"}


def test_scoped_reads_are_read_only_even_with_child_locked(chat):
    root = chat["root"] / "agents" / "Child"
    with Log(root) as log:
        log.append("user", "child")
        tree = Tree(root)
        view = View(tree)
        view.add_root(0)
        view.save()
        path = next((root / "main").glob("*.jsonl"))
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        assert call(chat, "zoom", {"id": 0, "scope": "Child"})["text"] == "child"
        assert call(chat, "date", {"id": 0, "scope": "Child"})["scope"] == "Child"
        assert call(chat, "zoom", {"id": "Child"})["scope"] == "Child"
        assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        path.write_text("broken\n{}\n")
        assert call(chat, "zoom", {"id": 0, "scope": "Child"})["error"].startswith(
            "scope 'Child' cannot be read: ")


def test_tool_exception_is_json(chat, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("tool broke")
    monkeypatch.setattr("willia.tools.zoom", fail)
    assert call(chat, "zoom", {"id": 0}) == {"error": "tool broke"}
