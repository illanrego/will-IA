Implemented the framed 005-style transcript and proportional rail bars.

Key changes:

- Every record now renders as rule → exact label → content.
- Tool arguments are formatted as quoted key/value pairs and hard-clipped to one line.
- Results and work reports retain at most three wrapped content lines with exact singular/plural overflow counts.
- Existing delegate report paths appear in clipped work trailers.
- Reasoning remains inside the `WILLIA` stream block with its original gutter and colours.
- Level bars use 12 cells, proportional rounding, and a one-cell minimum.
- Rail values now use the full available width; `settled · 0 unbuilt` is no longer chopped.
- Idle frame comparison, transcript caching, homing repaint, keys, yank behaviour, themes, and startup background fetches remain intact.

Implementation: [render.py](/home/illan/Documents/coding/willia/willia/tui/render.py:144), [app.py](/home/illan/Documents/coding/willia/willia/tui/app.py:123), [__init__.py](/home/illan/Documents/coding/willia/willia/tui/__init__.py:65)

Tests: [test_tui_render.py](/home/illan/Documents/coding/willia/tests/test_tui_render.py:20), [test_tui_keys.py](/home/illan/Documents/coding/willia/tests/test_tui_keys.py:138)

The assertions that changed meaning were:

- Flat records and blank separators now assert framed blocks.
- Notes remain hidden by default but render as full framed records when enabled.
- The tool one-line invariant now applies to its argument content beneath the frame.
- Viewport and fold expectations include rules and labels.
- Rail count assertions now include proportional bars.
- Reasoning assertions now locate the unchanged gutter inside its `WILLIA` block.

Full-suite tail:

```text
........................................................................ [ 78%]
........................................................................ [ 97%]
.........                                                                [100%]
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
369 passed, 3 warnings in 12.73s
```

The three warnings were from the existing delegate-thread closed-log case and the intentional invalid-record tests. An initial full run had one timing-only pump failure; it passed in isolation, and the complete rerun above passed.

Final frame:

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
 8 |state     settled · 0 unbuilt│{"status": "started", "name": "Fix-CLI", "agent": "codex", "report_path": "/home/illan/.
 9 |queue     0                  │willia/jobs/Fix-CLI-20261014T080000Z/report.md"}
10 |newest    6                  │────────────────────────────────────────────────────────────────────────────────────────
11 |FACTS                        │WILLIA
12 |session   8e2621d5           │Delegated to Codex as Fix-CLI; its report will arrive on its own.
13 |cache     95.3%              │────────────────────────────────────────────────────────────────────────────────────────
14 |jobs      1                  │WORK · [Fix-CLI]
15 |go        3 / 14 / 24%       │flag order was reversed in cli.py; patch applied, suite green.
16 |go ↺      3h44m / 4d17h      │Ran: uv run pytest -q -> 12 passed. Nothing outside the repo was touched.
17 |codex     12 / 18%           │────────────────────────────────────────────────────────────────────────────────────────
18 |codex ↺   3h51m / 6d9h       │ILLAN
19 |model     ds-v4.1-flash      │good. now check the metering path too.
20 |                             │
21 |                             │
22 |                             │
23 |                             │
24 |                             │
25 |                             │
26 |                             │
27 |                             │
28 |                             │
29 |NORMAL · transcript · You. Logged as a user record — the kind the compaction rubric ranks highest.
======================================================================================================================
styles per row: ['body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'body', 'dim']
```

Nothing requested was left undone. No git commands were run.