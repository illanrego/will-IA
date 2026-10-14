import json
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from willia.store import Record
from willia.tree import Line as TreeLine
from willia.tui import build_rail_facts
from willia.tui.render import cell_width, render, viewport, wrap
from willia.tui.theme import PALETTES, TOKENS


def record(kind, text, i=0):
    return Record(i, kind, text, len(text.encode()), "2026-10-14T00:00:00+00:00")


@pytest.mark.parametrize(("kind", "text", "style"), [
    ("user", "question", "you"),
    ("will", "answer", "body"),
])
def test_plain_record_kinds(kind, text, style):
    lines = render([record(kind, text)], [], 40, 20, "blue")
    assert [(line.text, line.style) for line in lines] == [(text, style)]


def test_conversation_blocks_are_separated_but_a_split_message_is_not():
    """A blank line marks a change of speaker; a long paste split into records stays whole."""
    split = [record("user", f"part-{i}", i) for i in range(3)]
    assert [line.text for line in render(split, [], 40, -1, "blue")] == [
        "part-0", "part-1", "part-2"]
    mixed = [record("user", "hello", 0), record("will", "hi", 1)]
    assert [line.text for line in render(mixed, [], 40, -1, "blue")] == ["hello", "", "hi"]


def test_imported_memory_is_hidden_unless_asked_for():
    """134 note records must not bury the conversation; :notes reveals them, one line each."""
    assert render([record("note", "reference")], [], 40, 20, "blue") == []
    shown = render([record("note", "reference")], [], 40, 20, "blue", show_notes=True)
    assert len(shown) == 1
    assert shown[0].text.startswith("note · reference")
    assert shown[0].style == "dim"


def test_work_tool_and_echo_records_have_the_approved_shapes():
    tool = json.dumps({"name": "terminal", "arguments": {"command": "pwd"}})
    lines = render([
        record("work", "[Fix-CLI] repaired it", 0),
        record("tool", tool, 1),
        record("echo", "one\ntwo\nthree\nfour\nfive", 2),
    ], [], 80, 20, "blue")
    assert lines[0].text == "[Fix-CLI] repaired it"
    assert [span.style for span in lines[0].spans] == ["amber", "dim"]
    assert lines[1].text.startswith("→ terminal ")
    assert {span.style for span in lines[1].spans} == {"agent", "dim"}
    assert [line.text for line in lines[-3:]] == ["one", "two", "… 3 more"]
    assert all(line.style == "dim" for line in lines[-3:])


def test_a_long_tool_argument_stays_one_line():
    """A delegate brief runs to hundreds of words; the packet must not flood the screen."""
    brief = "do the thing and prove it " * 40
    tool = json.dumps({"name": "delegate_codex", "arguments": {"task": brief}})
    lines = render([record("tool", tool)], [], 60, -1, "blue")
    assert len(lines) == 1, f"a tool call rendered as {len(lines)} lines"
    assert cell_width(lines[0].text) <= 60
    assert lines[0].text.endswith("…")
    assert lines[0].text.startswith("→ delegate_codex ")


def test_wrap_uses_terminal_cells_for_double_width_characters():
    lines = wrap("ab界cd", 4, "body")
    assert [line.text for line in lines] == ["ab界", "cd"]
    assert [cell_width(line.text) for line in lines] == [4, 2]


def test_width_height_and_scroll_offsets_are_bounded():
    records = [record("will", f"line-{i}", i) for i in range(6)]
    newest = render(records, [], 6, 2, "blue")
    all_lines = render(records, [], 6, -1, "blue")
    assert [line.text for line in newest] == ["line-4", "line-5"]
    assert [line.text for line in viewport(all_lines, 2, 2)] == ["line-2", "line-3"]
    assert viewport(all_lines, 2, 99) == all_lines[:2]


def test_in_flight_reasoning_and_content_are_visually_distinct():
    lines = render([], [
        {"event": "delta", "kind": "reasoning", "text": "consider"},
        {"event": "delta", "kind": "content", "text": "answer"},
    ], 40, 20, "mixed")
    assert lines[0].text == "│ consider"
    assert [span.style for span in lines[0].spans] == ["rule_strong", "reason"]
    assert lines[1].style == "body"


def test_all_palettes_define_exactly_the_same_fourteen_tokens():
    expected = set(TOKENS)
    assert len(expected) == 14
    assert set(PALETTES) == {"blue", "green", "mixed"}
    assert all(set(values) == expected for values in PALETTES.values())


def test_the_rail_snapshot_never_waits_for_the_engine():
    """A drain wave holds the engine lock for a whole pass; the rail must not queue behind it."""
    class BusyChat:
        def engine_free(self):
            return False

        def _engine(self):
            raise AssertionError("a non-blocking snapshot must not take the engine lock")

    assert build_rail_facts(BusyChat(), {}, blocking=False) is None


def test_rail_facts_are_tuples_built_from_live_sources(tmp_path):
    node = TreeLine(0, 0, "user: hello", 11)
    tree = SimpleNamespace(nodes=lambda: {(0, 0): node}, get=lambda *key: node)
    view = SimpleNamespace(
        render=lambda: "<chat>\n0+1|user: hello\n</chat>",
        settled=lambda: True,
        lines=lambda: [node],
    )
    chat = SimpleNamespace(
        _engine=nullcontext, tree=tree, view=view,
        compactor=SimpleNamespace(_pending=[]),
        config=SimpleNamespace(
            view_min_bytes=64_000, view_max_bytes=128_000,
            model=SimpleNamespace(model="deepseek-v4.1-flash"),
        ),
        root=tmp_path, session="1234567890",
        log=SimpleNamespace(count=lambda: 1),
    )
    facts = build_rail_facts(chat, {
        "rolling": {"percent": 3, "resetsAt": "2026-10-14T04:00:00Z"},
    }, now=datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert all(isinstance(fact, tuple) and len(fact) == 3 for fact in facts)
    mapped = {label: value for label, value, _style in facts}
    assert mapped["l0"] == "1"
    assert mapped["nodes"] == "1"
    assert mapped["session"] == "12345678"
    assert mapped["go"] == "3%"
    assert mapped["resets"] == "4h0m"
    assert mapped["here"] == "0"
    assert "codex" not in mapped
