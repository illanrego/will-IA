import json
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import willia.tui as tui
from willia.store import Record
from willia.tree import Line as TreeLine
from willia.tui import build_rail_facts
from willia.tui.render import Span, cell_width, render, viewport, wrap
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
    expected = [("─" * 40, "rule"), (label, "dim"), (text, style)]
    if kind == "user":
        expected.insert(0, ("", "body"))
    assert [(line.text, line.style) for line in lines] == expected


def test_consecutive_stream_records_are_one_continuous_block():
    split = [record("will", f"part-{i}", i) for i in range(6)]
    lines = render(split, [], 40, -1, "blue")
    assert [line.text for line in lines] == [
        "─" * 40, "WILLIA", "part-0part-1part-2part-3part-4part-5",
    ]
    assert sum(line.style == "rule" for line in lines) == 1
    assert "" not in [line.text for line in lines]


def test_consecutive_tool_records_remain_separate_blocks():
    tools = [record("tool", json.dumps({"name": name, "arguments": {}}), i)
             for i, name in enumerate(("first", "second"))]
    lines = render(tools, [], 40, -1, "blue")
    assert [line.text for line in lines if line.text.startswith("TOOL")] == [
        "TOOL · first", "TOOL · second",
    ]
    assert sum(line.style == "rule" for line in lines) == 2


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
    rule = next(index for index, line in enumerate(lines) if line.style == "rule")
    assert lines[rule].text == "─" * 80
    assert lines[rule + 1].text == label
    assert lines[rule + 2].text


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
    tool_label = next(index for index, line in enumerate(lines)
                      if line.text == "TOOL · terminal")
    assert lines[tool_label].style == "agent"
    assert lines[tool_label + 1].text == 'command "pwd"'
    assert [line.text for line in lines[-4:]] == [
        "│ one", "│ two", "│ three", "│ … 2 more lines",
    ]
    assert all(line.style == "dim" for line in lines[-4:])
    assert all(line.spans[0] == Span("│ ", "rule") for line in lines[-4:])


def test_a_long_tool_argument_stays_one_line():
    """A delegate brief runs to hundreds of words; the packet must not flood the screen."""
    brief = "do the thing and prove it " * 40
    tool = json.dumps({"name": "delegate_codex", "arguments": {"task": brief}})
    lines = render([record("tool", tool)], [], 60, -1, "blue")
    assert len(lines) == 4, f"a framed tool call rendered as {len(lines)} lines"
    assert lines[2].text == "TOOL · delegate_codex"
    assert cell_width(lines[3].text) <= 60
    assert lines[3].text.endswith("…")
    assert lines[3].text.startswith('task "do the thing')


@pytest.mark.parametrize(("text", "trailer"), [
    ("one\ntwo\nthree\nfour", "… 1 more line"),
    ("one\ntwo\nthree\nfour\nfive", "… 2 more lines"),
])
def test_clip_counts_are_exact_and_grammatical(text, trailer):
    lines = render([record("echo", text)], [], 80, -1, "blue")
    label = next(index for index, line in enumerate(lines) if line.text == "RESULT")
    assert [line.text for line in lines[label + 1:label + 4]] == [
        "│ one", "│ two", "│ three"]
    assert lines[label + 4].text == f"│ {trailer}"


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
    assert [line.text for line in newest] == ["line-4", "line-5"]
    assert [line.text for line in viewport(all_lines, 2, 2)] == ["line-2", "line-3"]
    assert viewport(all_lines, 2, 99) == all_lines[:2]


def test_005_transcript_tones_and_answer_markdown_are_applied():
    tool = json.dumps({"name": "terminal", "arguments": {"command": "pwd"}})
    lines = render([
        record("user", "question", 0),
        record("will", "plain **bold words** and `value`", 1),
        record("reasoning", "consider", 2),
        record("tool", tool, 3),
        record("echo", "result", 4),
        record("work", "[Fix] repaired it", 5),
        record("note", "reference", 6),
    ], [], 80, -1, "blue", show_notes=True)
    labels = {line.text: line for line in lines if line.text in {
        "ILLAN", "WILLIA", "THINK", "TOOL · terminal", "RESULT",
        "WORK · [Fix]", "NOTE",
    }}
    assert {name: labels[name].style for name in ("ILLAN", "WILLIA", "THINK", "RESULT", "NOTE")} == {
        name: "dim" for name in ("ILLAN", "WILLIA", "THINK", "RESULT", "NOTE")
    }
    assert labels["TOOL · terminal"].style == "agent"
    assert labels["WORK · [Fix]"].style == "amber"
    assert next(line for line in lines if line.text == "question").style == "you"
    answer = next(line for line in lines if line.text == "plain bold words and value")
    assert answer.style == "body"
    assert [(span.text, span.style) for span in answer.spans] == [
        ("plain ", "body"), ("bold words", "strong"), (" and ", "body"),
        ("value", "data"),
    ]
    result = next(line for line in lines if line.text == "│ result")
    assert [(span.text, span.style) for span in result.spans] == [
        ("│ ", "rule"), ("result", "dim"),
    ]


def test_answer_markdown_wraps_spans_but_keeps_raw_source_text():
    raw = "before **strong across the wrap** and `data` after"
    lines = render([record("will", raw)], [], 12, -1, "blue")[2:]
    assert "".join(line.text for line in lines) == (
        "before strong across the wrap and data after"
    )
    assert any(span.style == "strong" for line in lines for span in line.spans)
    assert any(span.style == "data" for line in lines for span in line.spans)
    assert all(line.source_text == raw for line in lines)


def test_unpaired_answer_markers_stay_literal():
    lines = render([record("will", "a lone * and `tick")], [], 80, -1, "blue")
    assert lines[2].text == "a lone * and `tick"


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


def test_005_vertical_rhythm_is_exact_and_collapsed_between_block_kinds():
    tool = lambda name, i: record(  # noqa: E731 - compact fixture reads like the transcript
        "tool", json.dumps({"name": name, "arguments": {}}), i)
    lines = render([
        record("user", "ask", 0),
        record("reasoning", "consider", 1),
        record("will", "answer", 2),
        tool("first", 3), tool("second", 4),
        record("echo", "output", 5),
        record("work", "[Job] done", 6),
        record("user", "follow-up", 7),
    ], [], 60, -1, "blue")
    texts = [line.text for line in lines]
    labels = ["ILLAN", "THINK", "WILLIA", "TOOL · first", "TOOL · second",
              "RESULT", "WORK · [Job]", "ILLAN"]
    positions = []
    cursor = 0
    for label in labels:
        position = texts.index(label, cursor)
        positions.append(position)
        cursor = position + 1

    assert texts[0] == ""                       # stage top padding / user margin collapse
    for pair_index, (previous, current) in enumerate(zip(positions, positions[1:])):
        between = texts[previous + 2:current - 1]
        if pair_index in {0, 3}:
            assert "" not in between             # no user tail; packets pack tight
        else:
            assert between.count("") == 1         # every requested block margin is one row
    assert not any(left == right == "" for left, right in zip(texts, texts[1:]))
    assert texts[-1] != ""                       # no synthetic trailing transcript row


def test_answer_paragraph_break_and_list_hanging_indent_survive_wrapping():
    text = "First paragraph.\n\n- alpha beta gamma delta\n1. ordered item wraps too"
    lines = render([record("will", text)], [], 14, -1, "blue")
    content = lines[2:]
    assert "" in [line.text for line in content]
    bullet = next(index for index, line in enumerate(content)
                  if line.text.startswith("- "))
    assert content[bullet].spans[0] == Span("- ", "dim")
    assert content[bullet].spans[1].style == "body"
    assert content[bullet + 1].text.startswith("  ")
    assert content[bullet + 1].text[2:].startswith("gamma")
    assert content[bullet + 1].spans[0] == Span("  ", "dim")
    ordered = next(index for index, line in enumerate(content)
                   if line.text.startswith("1. "))
    assert content[ordered].spans[0] == Span("1. ", "dim")
    assert content[ordered + 1].text.startswith("   ")


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
