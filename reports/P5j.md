Implemented the flicker, bounded input field, and steady software caret changes.

- Every non-empty paint is wrapped in `ESC[?2026h` / `ESC[?2026l`; empty paints write nothing. See [screen.py](/home/illan/Documents/coding/willia/willia/tui/screen.py:181).
- Added the transcript-aligned compose field, top rule, focus-aware `❯`, wrapped input, height limiting, and persistent streaming field. See [app.py](/home/illan/Documents/coding/willia/willia/tui/app.py:1030).
- Added cursor-indexed editing and a steady reverse-video/solid-block caret using renderer cell widths for CJK, emoji, and combining marks.
- Hardware cursor remains hidden during painting and is restored exactly once on exit or exception.
- Preserved the existing keymap, frame diffing, themes, tokens, and dependencies.
- Added coverage in [test_tui_screen.py](/home/illan/Documents/coding/willia/tests/test_tui_screen.py:44) and [test_tui_keys.py](/home/illan/Documents/coding/willia/tests/test_tui_keys.py:89).

Full-suite tail:

```text
.....................................................................    [100%]
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
429 passed, 3 warnings in 16.32s
/home/illan/.local/share/uv/python/cpython-3.14.7-linux-x86_64-gnu/lib/python3.14/tempfile.py:484: ResourceWarning: Implicitly cleaning up <HTTPError 401: 'no'>
```

The three warnings were a background job writing after its test log closed and two intentional invalid-record warnings; no tests failed.

Final PTY segment proof:

```text
insert key x: 12145 bytes; sync_on=1; sync_off=1; first_sync=True; last_sync=True
streaming turn: 24622 bytes; sync_on=2; sync_off=2; first_sync=True; last_sync=True
stream marker visible: True
idle after settle: 0 bytes; sync_on=0; sync_off=0; first_sync=False; last_sync=False
restored: True
```

The idle segment correctly contains no sync sequence because it writes zero bytes.

One limitation: the stock PTY driver’s mid-stream `zz` assertion failed once while the exact-token reply completed in 0 seconds. Its other checks—including idle silence, streaming/logging, no full clears, and terminal restoration—passed. The separate PTY segment capture above verified insert and streaming paints directly.

I did not add changed-row painting because synchronized updates are now correctly emitted; visible tearing still needs confirmation in the real Alacritty/tmux session. No git commands were run.