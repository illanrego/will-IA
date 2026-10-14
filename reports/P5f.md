Implemented the framed TUI revision in:

- [render.py](/home/illan/Documents/coding/willia/willia/tui/render.py)
- [app.py](/home/illan/Documents/coding/willia/willia/tui/app.py)
- [test_tui_render.py](/home/illan/Documents/coding/willia/tests/test_tui_render.py)
- [test_tui_keys.py](/home/illan/Documents/coding/willia/tests/test_tui_keys.py)

Changes include continuous `will`/`user`/`reasoning` blocks, preserved yank provenance, 005 tone assignments, answer-only markdown-lite, and `RESULT` rule gutters. No palette, dependency, log-format, keymap, startup-path, or unrelated file changes were made. No git commands were used.

Full-suite tail:

```text
........................................................................ [ 96%]
..............                                                           [100%]
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
374 passed, 3 warnings in 11.24s
```

The warnings were one background job attempting to append after its test log closed and two intentional invalid-record warnings.

Frame probe:

```text
======================================================================================================================
 0 |MEMORY                       │────────────────────────────────────────────────────────────────────────────────────────
 1 |l0        ████████████ 7     │ILLAN
 2 |l1        ███████      4     │the posting CLI broke after the batch — check it and fix it.
 3 |l2        ███          2     │────────────────────────────────────────────────────────────────────────────────────────
 4 |nodes     13                 │TOOL · delegate_codex
 5 |VIEW                         │task "Create the ledger module, wire it into the CLI, prove it with a focused test, and…
 6 |bytes     1,204 B            │────────────────────────────────────────────────────────────────────────────────────────
 7 |64K-128K  ─●───────────      │RESULT
 8 |state     settled · 0 unbuilt││ {"status": "started", "name": "Fix-CLI", "agent": "codex", "report_path": "/home/illan
 9 |queue     0                  ││ /.willia/jobs/Fix-CLI-20261014T080000Z/report.md"}
10 |newest    6                  │────────────────────────────────────────────────────────────────────────────────────────
11 |FACTS                        │WILLIA
12 |session   8e2621d5           │Delegated to Codex as Fix-CLI; its report arrives on its own. Meanwhile the metering pat
13 |cache     95.3%              │h needs a look, because the last commit 2026-10-14 touched it and the usage.jsonl writer
14 |jobs      1                  │ has not been exercised since. The branch feat/meter-split carries the fix, and willia -
15 |go        3 / 14 / 24%       │-usage reads it back.
16 |go ↺      3h44m / 4d17h      │────────────────────────────────────────────────────────────────────────────────────────
17 |codex     12 / 18%           │RESULT
18 |codex ↺   3h51m / 6d9h       ││ {"exit": 0, "stderr": ""}
19 |model     ds-v4.1-flash      │────────────────────────────────────────────────────────────────────────────────────────
20 |                             │WORK · [Fix-CLI]
21 |                             │flag order was reversed in cli.py; patch applied, suite green.
22 |                             │Ran: uv run pytest -q -> 12 passed. Nothing outside the repo was touched.
23 |                             │────────────────────────────────────────────────────────────────────────────────────────
24 |                             │ILLAN
25 |                             │good. now check the metering path too.
26 |
27 |
28 |
29 |NORMAL · transcript · You. Logged as a user record — the kind the compaction rubric ranks highest.
======================================================================================================================
styles per row: ['body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'dim']
```

Nothing requested was left undone.