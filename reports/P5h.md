Implemented the 005 fidelity pass in [render.py](/home/illan/Documents/coding/willia/willia/tui/render.py:310) and [app.py](/home/illan/Documents/coding/willia/willia/tui/app.py:731):

- Added collapsed block rhythm and stage padding.
- Preserved answer paragraph breaks.
- Added dim list markers and hanging indentation.
- Added letterspaced rail headers with narrow fallback.
- Applied per-span rail tones for bars, counts, gauges, numeric/text values, parentheses, countdowns, and `·` suffixes.
- Preserved merged streams, clipping, yanking, keymap, themes, and idle behavior.
- Used no git commands.

Tests added across the permitted test files.

Full-suite tail from the exact requested command:

```text
........................................................................ [ 74%]
........................................................................ [ 93%]
.........................                                                [100%]
385 passed, 3 warnings in 11.82s
```

The warnings concern the existing delegate-thread/log-close and invalid-record tests; there were no failures.

Frame from `uv run --no-project python probes/frame-text.py`:

```text
======================================================================================================================
 0 |M E M O R Y                  │                                                                                        
 1 |l0        ████████████ 7     │TOOL · delegate_codex                                                                   
 2 |l1        ███████      4     │task "Create the ledger module, wire it into the CLI, prove it with a focused test, and…
 3 |l2        ███          2     │                                                                                        
 4 |nodes     13                 │────────────────────────────────────────────────────────────────────────────────────────
 5 |                             │RESULT                                                                                  
 6 |─────────────────────────────││ {"status": "started", "name": "Fix-CLI", "agent": "codex", "report_path":             
 7 |V I E W                      ││ "/home/illan/.willia/jobs/Fix-CLI-20261014T080000Z/report.md"}                        
 8 |bytes     1,204 B            │                                                                                        
 9 |64K-128K  ─●───────────      │────────────────────────────────────────────────────────────────────────────────────────
10 |state     settled · 0 unbuilt│WILLIA                                                                                  
11 |queue     0                  │Delegated to Codex as Fix-CLI; its report arrives on its own. Meanwhile the metering    
12 |newest    6                  │path needs a look, because the last commit 2026-10-14 touched it and the usage.jsonl    
13 |                             │writer has not been exercised since. The branch feat/meter-split carries the fix, and   
14 |─────────────────────────────│willia --usage reads it back.                                                           
15 |F A C T S                    │                                                                                        
16 |session   8e2621d5           │────────────────────────────────────────────────────────────────────────────────────────
17 |cache     95.3%              │RESULT                                                                                  
18 |jobs      1                  ││ {"exit": 0, "stderr": ""}                                                             
19 |go        3 / 14 / 24%       │                                                                                        
20 |go ↺      3h44m / 4d17h      │────────────────────────────────────────────────────────────────────────────────────────
21 |codex     12 / 18%           │WORK · [Fix-CLI]                                                                        
22 |codex ↺   3h51m / 6d9h       │flag order was reversed in cli.py; patch applied, suite green.                          
23 |model     ds-v4.1-flash      │Ran: uv run pytest -q -> 12 passed. Nothing outside the repo was touched.               
24 |                             │                                                                                        
25 |                             │────────────────────────────────────────────────────────────────────────────────────────
26 |                             │ILLAN                                                                                   
27 |                             │good. now check the metering path too.                                                  
28 |                             │                                                                                        
29 |NORMAL · transcript · You. Logged as a user record — the kind the compaction rubric ranks highest.                    
======================================================================================================================
```

Nothing requested was left undone.