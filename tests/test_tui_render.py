import json
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import willia.tui as tui
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
    label = "ILLAN" if kind == "user" else "WILLIA"
    label_style = "you" if kind == "user" else "body"
    assert [(line.text, line.style) for line in lines] == [
        ("─" * 40, "rule"), (label, label_style), (text, style),
    ]


def test_every_record_is_its_own_block_without_blank_separator_lines():
    """Even adjacent same-kind chunks are individually framed because each is a log record."""
    split = [record("user", f"part-{i}", i) for i in range(3)]
    lines = render(split, [], 40, -1, "blue")
    assert [line.text for line in lines] == [
        "─" * 40, "ILLAN", "part-0",
        "─" * 40, "ILLAN", "part-1",
        "─" * 40, "ILLAN", "part-2",
    ]
    assert "" not in [line.text for line in lines]


def test_imported_memory_is_hidden_unless_asked_for():
    """134 note records must not bury the conversation; :notes reveals framed notes."""
    assert render([record("note", "reference")], [], 40, 20, "blue") == []
    shown = render([record("note", "reference")], [], 40, 20, "blue", show_notes=True)
    assert [(line.text, line.style) for line in shown] == [
        ("─" * 40, "rule"), ("NOTE", "dim"), ("reference", "dim"),
    ]


@pytest.mark.parametrize(("kind", "text", "label", "show_notes"), [
    ("user", "question", "ILLAN", False),
    ("will", "answer", "WILLIA", False),
    ("tool", json.dumps({"name": "terminal", "arguments": {"command": "pwd"}}),
     "TOOL · terminal", False),
    ("echo", "result", "RESULT", False),
    ("work", "[Fix-CLI] repaired it", "WORK · [Fix-CLI]", False),
    ("note", "reference", "NOTE", True),
    ("reasoning", "consider", "THINK", False),
])
def test_rule_label_content_block_for_each_record_kind(kind, text, label, show_notes):
    lines = render([record(kind, text)], [], 80, -1, "blue", show_notes=show_notes)
    assert lines[0].text == "─" * 80
    assert lines[0].style == "rule"
    assert lines[1].text == label
    assert lines[2].text


def test_work_tool_and_echo_records_have_the_approved_styles_and_shapes():
    tool = json.dumps({"name": "terminal", "arguments": {"command": "pwd"}})
    lines = render([
        record("work", "[Fix-CLI] repaired it", 0),
        record("tool", tool, 1),
        record("echo", "one\ntwo\nthree\nfour\nfive", 2),
    ], [], 80, 20, "blue")
    assert [(line.text, line.style) for line in lines[:3]] == [
        ("─" * 80, "rule"), ("WORK · [Fix-CLI]", "amber"), ("repaired it", "dim"),
    ]
    assert lines[4].text == "TOOL · terminal"
    assert lines[4].style == "agent"
    assert lines[5].text == 'command "pwd"'
    assert [line.text for line in lines[-4:]] == ["one", "two", "three", "… 2 more lines"]
    assert all(line.style == "dim" for line in lines[-4:])


def test_a_long_tool_argument_stays_one_line():
    """A delegate brief runs to hundreds of words; the packet must not flood the screen."""
    brief = "do the thing and prove it " * 40
    tool = json.dumps({"name": "delegate_codex", "arguments": {"task": brief}})
    lines = render([record("tool", tool)], [], 60, -1, "blue")
    assert len(lines) == 3, f"a framed tool call rendered as {len(lines)} lines"
    assert lines[1].text == "TOOL · delegate_codex"
    assert cell_width(lines[2].text) <= 60
    assert lines[2].text.endswith("…")
    assert lines[2].text.startswith('task "do the thing')


@pytest.mark.parametrize(("text", "trailer"), [
    ("one\ntwo\nthree\nfour", "… 1 more line"),
    ("one\ntwo\nthree\nfour\nfive", "… 2 more lines"),
])
def test_clip_counts_are_exact_and_grammatical(text, trailer):
    lines = render([record("echo", text)], [], 80, -1, "blue")
    assert [line.text for line in lines[2:5]] == ["one", "two", "three"]
    assert lines[5].text == trailer


def test_clipped_work_links_an_existing_report_from_the_delegate_result(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("full report", encoding="utf-8")
    result = json.dumps({"name": "Fix-CLI", "report_path": str(report)})
    lines = render([
        record("echo", result, 0),
        record("work", "[Fix-CLI] one\ntwo\nthree\nfour", 1),
    ], [], 200, -1, "blue", report_paths={"Fix-CLI": str(report)})
    label = next(index for index, line in enumerate(lines)
                 if line.text == "WORK · [Fix-CLI]")
    assert lines[label + 4].text == f"… 1 more line - full report: {report}"


def test_wrap_uses_terminal_cells_for_double_width_characters():
    lines = wrap("ab界cd", 4, "body")
    assert [line.text for line in lines] == ["ab界", "cd"]
    assert [cell_width(line.text) for line in lines] == [4, 2]


def test_width_height_and_scroll_offsets_are_bounded():
    records = [record("will", f"line-{i}", i) for i in range(6)]
    newest = render(records, [], 6, 2, "blue")
    all_lines = render(records, [], 6, -1, "blue")
    assert [line.text for line in newest] == ["WILLIA", "line-5"]
    assert [line.text for line in viewport(all_lines, 2, 2)] == ["line-4", "─" * 6]
    assert viewport(all_lines, 2, 99) == all_lines[:2]


def test_in_flight_reasoning_and_content_are_visually_distinct():
    lines = render([], [
        {"event": "delta", "kind": "reasoning", "text": "consider"},
        {"event": "delta", "kind": "content", "text": "answer"},
    ], 40, 20, "mixed")
    assert [line.text for line in lines[:2]] == ["─" * 40, "WILLIA"]
    assert lines[2].text == "│ consider"
    assert [span.style for span in lines[2].spans] == ["rule_strong", "reason"]
    assert lines[2].record_kind == "reasoning"
    assert lines[3].style == "body"


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
    facts = build_rail_facts(
        chat,
        {"rolling": {"percent": 3, "resetsAt": "2026-10-14T04:00:00Z"}},
        {
            "primary": {"label": "5h", "percent": 12, "resets_in_s": 14_900},
            "secondary": {"label": "7d", "percent": 18, "resets_in_s": 551_849},
        },
        now=datetime(2026, 10, 14, tzinfo=timezone.utc),
    )
    assert all(isinstance(fact, tuple) and len(fact) == 3 for fact in facts)
    mapped = {label: value for label, value, _style in facts}
    assert mapped["l0"] == "████████████ 1"
    assert mapped["nodes"] == "1"
    assert mapped["session"] == "12345678"
    assert mapped["go"] == "3%"
    assert mapped["go ↺"] == "4h0m"
    assert mapped["codex"] == "12% / 18%"
    assert mapped["codex ↺"] == "4h8m / 6d9h"
    assert mapped["here"] == "0"
    labels = [label for label, _value, _style in facts]
    assert labels[labels.index("go"):labels.index("codex ↺") + 1] == [
        "go", "go ↺", "codex", "codex ↺",
    ]


def test_rail_ladder_bars_are_proportional_and_keep_one_cell_for_a_single_node(tmp_path):
    counts = {0: 12, 1: 6, 2: 1}
    nodes = {
        (level, index): TreeLine(level, index, f"line {level}:{index}", 8)
        for level, count in counts.items() for index in range(count)
    }
    tree = SimpleNamespace(nodes=lambda: nodes, get=lambda *key: nodes.get(tuple(key)))
    chat = SimpleNamespace(
        _engine=nullcontext, tree=tree,
        view=SimpleNamespace(render=lambda: "", settled=lambda: True, lines=lambda: []),
        compactor=SimpleNamespace(_pending=[]),
        config=SimpleNamespace(
            view_min_bytes=64_000, view_max_bytes=128_000,
            model=SimpleNamespace(model="deepseek-v4.1-flash"),
        ),
        root=tmp_path, session="1234567890", log=SimpleNamespace(count=lambda: 19),
    )
    facts = build_rail_facts(chat, now=datetime(2026, 10, 14, tzinfo=timezone.utc))
    mapped = {label: value for label, value, _style in facts}
    assert [mapped[f"l{level}"][:12].count("█") for level in counts] == [12, 6, 1]
    assert [mapped[f"l{level}"].split()[-1] for level in counts] == ["12", "6", "1"]
    assert mapped["nodes"] == "19"


def test_tui_starts_both_usage_fetches_only_on_daemon_threads(monkeypatch):
    threads = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon
            threads.append(self)

        def start(self):
            return None

    class FakeApp:
        def __init__(self, chat, screen, *, rail_source, theme):
            self.rail_source = rail_source

        def run(self):
            return None

    monkeypatch.setattr(tui.threading, "Thread", FakeThread)
    monkeypatch.setattr(tui, "Screen", lambda: object())
    monkeypatch.setattr(tui, "App", FakeApp)
    monkeypatch.setattr(
        tui.usage, "subscription_windows",
        lambda _config: pytest.fail("Go network fetch ran on the startup path"),
    )
    monkeypatch.setattr(
        tui.usage, "codex_windows",
        lambda: pytest.fail("Codex network fetch ran on the startup path"),
    )
    chat = SimpleNamespace(config=SimpleNamespace(tui=SimpleNamespace(theme="blue")))

    tui.run(chat)

    assert [thread.name for thread in threads] == [
        "willia-tui-go-usage", "willia-tui-codex-usage",
    ]
    assert all(thread.daemon for thread in threads)
