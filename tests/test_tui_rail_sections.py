"""The rail's sections are separated by a hairline, as 005's .sep has them."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path.home() / "Documents/coding/willia"))

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
    headers = [i for i, text in enumerate(texts) if text.strip() in {"MEMORY", "VIEW", "FACTS"}]
    assert len(headers) == 3, texts
    for sep in seps:
        assert min(h for h in headers if h > sep) == sep + 1, texts
