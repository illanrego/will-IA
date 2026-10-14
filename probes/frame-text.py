"""Render a frame as text, so the layout can be judged without a terminal."""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path.home() / "Documents/coding/willia"))

from willia.store import Record                       # noqa: E402
from willia.tui.app import App                        # noqa: E402


class FakeLog:
    def __init__(self, records):
        self.records = records

    def count(self):
        return len(self.records)

    def range(self, lo, hi):
        return self.records[max(0, lo):hi + 1]


class FakeChat:
    def __init__(self, records):
        self.log = FakeLog(records)

    def turn(self, texts, *, sink=None):
        pass


class NullScreen:
    resized = False

    def size(self):
        return 118, 30

    def draw(self, lines, theme):
        pass


def rec(i, kind, text):
    return Record(i, kind, text, len(text.encode()), "2026-10-14T00:00:00+00:00")


BRIEF = ("Create the ledger module, wire it into the CLI, prove it with a focused test, and "
         "report the exact command you ran and its output. Do not commit anything.")
RECORDS = [
    rec(0, "note", "identity: Illan, IT professional; rules and context"),
    rec(1, "user", "the posting CLI broke after the batch — check it and fix it."),
    rec(2, "tool", json.dumps({"name": "delegate_codex",
                               "arguments": {"task": BRIEF, "model": "gpt-5.6-sol",
                                             "name": "Fix-CLI"}})),
    rec(3, "echo", '{"status": "started", "name": "Fix-CLI", "agent": "codex", '
                   '"report_path": "/home/illan/.willia/jobs/Fix-CLI-20261014T080000Z/report.md"}'),
    # One answer, flushed by the client mid-word - the six-record run in the live chat.
    rec(4, "will", "Delegated to Codex as Fix-CLI; its report arrives on its own. Meanwhile the "
                   "metering path needs a look, because the last commit **2026-10-14** touched it "
                   "and the `usage.jsonl` writer has not been exercised since. The branch "),
    rec(5, "will", "`feat/meter-split` carries the fix, and `willia --usage` reads it back."),
    rec(6, "echo", '{"exit": 0, "stderr": ""}'),
    rec(7, "work", "[Fix-CLI] flag order was reversed in cli.py; patch applied, suite green.\n"
                   "Ran: uv run pytest -q -> 12 passed. Nothing outside the repo was touched."),
    rec(8, "user", "good. now check the metering path too."),
]

app = App(FakeChat(RECORDS), NullScreen(), rail_facts=[
    ("#memory", "", "dim"), ("l0", "7", "data"), ("l1", "4", "data"), ("l2", "2", "data"),
    ("nodes", "13", "data"), ("#view", "", "dim"), ("bytes", "1,204 B", "data"),
    ("64K-128K", "─●───────────", "data"), ("state", "settled · 0 unbuilt", "ok"),
    ("queue", "0", "data"), ("newest", "6", "body"), ("#facts", "", "dim"),
    ("session", "8e2621d5", "body"), ("cache", "95.3%", "data"), ("jobs", "1", "body"),
    ("go", "3 / 14 / 24%", "data"), ("go ↺", "3h44m / 4d17h", "body"),
    ("codex", "12 / 18%", "data"), ("codex ↺", "3h51m / 6d9h", "body"),
    ("model", "ds-v4.1-flash", "body"),
])

print("=" * 118)
for index, line in enumerate(app._frame()):
    print(f"{index:2} |{line.text}")
print("=" * 118)
print("styles per row:", [line.style for line in app._frame()])
