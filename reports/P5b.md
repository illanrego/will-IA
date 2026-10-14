Implemented P5b, P5c, and P5d completely.

Highlights:

- Pane focus, persistent rail selection, rail/record folding, contextual hint line, and protected compaction progress.
- Raw-log yanks for lines, records, and visual ranges via OSC 52 plus bounded `wl-copy`/`xclip` fallback.
- Scrollable `?`/`:help` overlay without changing transcript position.
- Configurable `tui.theme`, with live blue/green/mixed switching and unknown-theme refusal.
- Idle redraw suppression remains intact.

Final suite tail:

```text
........................................................................ [ 83%]
........................................................                 [100%]
344 passed, 3 warnings in 12.32s
```

The warnings were one background-job/log-close race warning and two deliberate invalid-record warnings from store tests.

P5a regression proof:

```text
--- bytes while idle for 3s: 0 (must be 0)
--- after a keypress that changes the frame: 10683 bytes (must be > 0)

=== RESULT
    PASS - the TUI drew, streamed a real turn, scrolled and restored
```

Changed files:

- [app.py](/home/illan/Documents/coding/willia/willia/tui/app.py)
- [clipboard.py](/home/illan/Documents/coding/willia/willia/tui/clipboard.py)
- [hints.py](/home/illan/Documents/coding/willia/willia/tui/hints.py)
- [render.py](/home/illan/Documents/coding/willia/willia/tui/render.py)
- [screen.py](/home/illan/Documents/coding/willia/willia/tui/screen.py)
- [__init__.py](/home/illan/Documents/coding/willia/willia/tui/__init__.py)
- [config.py](/home/illan/Documents/coding/willia/willia/config.py)
- [test_tui_keys.py](/home/illan/Documents/coding/willia/tests/test_tui_keys.py)
- [test_tui_render.py](/home/illan/Documents/coding/willia/tests/test_tui_render.py)
- [test_tui_screen.py](/home/illan/Documents/coding/willia/tests/test_tui_screen.py)

`HINTS` keys:

```text
memory, l0, l1, l2, l3, l4, l5, l6, l7, view, queue, here,
session, cache, jobs, go, codex, model, user, will, reasoning,
tool, echo, work, note
```

Nothing from the brief remains incomplete. No git commands were used.