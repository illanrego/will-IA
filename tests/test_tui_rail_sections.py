"""The rail's sections are separated by a hairline, as 005's .sep has them."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path.home() / "Documents/coding/willia"))

import willia.tui.app as app_module                       # noqa: E402
from willia.tui.app import RAIL_WIDTH, App                # noqa: E402
from willia.tui.render import Line                        # noqa: E402


class FakeChat:
    def __init__(self):
        self.log = type("L", (), {"count": staticmethod(lambda: 1)})()


class FakeScreen:
    resized = False

    def size(self):
        return 100, 30

    def draw(self, lines, theme):
        pass


FACTS = [
    ("#memory", "", "dim"), ("l0", "3", "data"), ("nodes", "3", "data"),
    ("#view", "", "dim"), ("bytes", "10 B", "data"),
    ("#facts", "", "dim"), ("session", "abc", "body"),
]


def test_each_section_after_the_first_is_introduced_by_a_hairline():
    app = App(FakeChat(), FakeScreen(), rail_facts=FACTS)
    app.focus = app.focus.__class__.RAIL
    lines = app._rail_lines(30)
    texts = [line.text for line in lines]
    seps = [i for i, text in enumerate(texts) if text and set(text) == {"─"}]
    # MEMORY, VIEW and FACTS: the first needs no separator, the other two do.
    assert len(seps) == 2, texts
    assert texts[seps[0] - 1].strip() == ""  # 005's gap, padded to the rail's width
    assert all(len(texts[i]) == RAIL_WIDTH - 1 for i in seps)
    # headers are padded to the rail's width, so compare their stripped text
    headers = [i for i, text in enumerate(texts)
               if text.strip() in {"M E M O R Y", "V I E W", "F A C T S"}]
    assert len(headers) == 3, texts
    for sep in seps:
        assert min(h for h in headers if h > sep) == sep + 1, texts


def test_header_letterspacing_falls_back_to_the_complete_word_when_narrow(monkeypatch):
    monkeypatch.setattr(app_module, "RAIL_WIDTH", 8)
    app = App(FakeChat(), FakeScreen(), rail_facts=[("#memory", "", "dim")])
    assert app._rail_lines(2)[0].text.strip() == "MEMORY"


def test_ladder_count_and_fact_suffixes_have_005s_individual_tones():
    app = App(FakeChat(), FakeScreen(), rail_facts=[
        ("#memory", "", "dim"), ("l0", "3", "data"), ("nodes", "3", "data"),
        ("#view", "", "dim"), ("64K-128K", "──●──", "data"),
        ("state", "settled · 0 unbuilt", "ok"),
        ("#facts", "", "dim"), ("jobs", "1", "body"),
        ("model", "willia (fast)", "body"), ("go ↺", "3h44m", "body"),
    ])
    lines = app._rail_lines(30)

    level = next(line for line in lines if line.text.startswith("l0"))
    assert any(span.style == "data" and "█" in span.text for span in level.spans)
    assert level.spans[-2].style == "dim"

    gauge = next(line for line in lines if line.text.startswith("64K-128K"))
    assert any(span.style == "rule_strong" and "─" in span.text for span in gauge.spans)
    assert any(span.style == "data" and "●" in span.text for span in gauge.spans)

    state = next(line for line in lines if line.text.startswith("state"))
    assert any(span.style == "ok" and "settled" in span.text for span in state.spans)
    assert any(span.style == "dim" and "· 0 unbuilt" in span.text for span in state.spans)

    jobs = next(line for line in lines if line.text.startswith("jobs"))
    assert any(span.style == "data" and "1" in span.text for span in jobs.spans)
    model = next(line for line in lines if line.text.startswith("model"))
    assert any(span.style == "body" and "willia " in span.text for span in model.spans)
    assert any(span.style == "dim" and "(fast)" in span.text for span in model.spans)
    reset = next(line for line in lines if line.text.startswith("go ↺"))
    assert any(span.style == "dim" and "3h44m" in span.text for span in reset.spans)
