Implemented P5a within the requested boundaries. No Git commands were used.

Highlights:

- Optional fail-safe `Chat.turn(..., sink=None)` event sink with deltas, tool calls/results and timing, notices, and turn completion.
- Pure transcript renderer with Unicode cell-width wrapping.
- Exact three palettes with truecolour, 256-colour, and 8-colour paths.
- Raw-mode alternate-screen lifecycle, key decoding, resize handling, and guaranteed restoration.
- NORMAL/INSERT modes, editing, history, commands, and scrolling.
- Static 30-column rail backed by live mappings.
- `willia --tui` with non-terminal stdout refusal.
- Offline TUI test coverage.

Test tail:

```text
........................................................................ [ 88%]
......................................                                   [100%]
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
326 passed, 3 warnings in 11.11s
```

The warnings are the existing delegate-thread shutdown race and two intentional invalid-record warnings. One preceding full run hit the existing timing-sensitive pump threshold at 1.275s versus 1.25s; the immediate complete rerun above passed.

Renderer signature:

```python
def render(records, in_flight, width, height, theme) -> list[Line]:
```

Rail fact construction:

```python
sources = {
    "#memory": ("", "dim"),
    **{f"l{level}": (str(levels[level]), "data") for level in sorted(levels)},
    "nodes": (str(total), "data"),
    "#view": ("", "dim"),
    "bytes": (f"{view_bytes:,} B", "data"),
    "64K-128K": (gauge, "data"),
    "state": (("settled" if settled else "building") + f" · {unbuilt} unbuilt",
              "ok" if settled and not unbuilt else "amber"),
    "queue": (str(queue_depth), "data"),
    "newest": (str(chat.log.count() - 1) if chat.log.count() else "none", "body"),
    "#facts": ("", "dim"),
    "session": (chat.session[:8], "body"),
    "cache": (cache, "data"),
    "jobs": (str(len(jobs.running(chat))), "body"),
    "go": (go, "data"),
    "resets": (reset, "body"),
    "model": (chat.config.model.model, "body"),
}
facts = [(label, value, style) for label, (value, style) in sources.items()]
```

Changed files:

- [willia/chat.py](/home/illan/Documents/coding/willia/willia/chat.py:166)
- [willia/cli.py](/home/illan/Documents/coding/willia/willia/cli.py:274)
- [willia/tui/__init__.py](/home/illan/Documents/coding/willia/willia/tui/__init__.py:36)
- [willia/tui/app.py](/home/illan/Documents/coding/willia/willia/tui/app.py:28)
- [willia/tui/render.py](/home/illan/Documents/coding/willia/willia/tui/render.py:186)
- [willia/tui/screen.py](/home/illan/Documents/coding/willia/willia/tui/screen.py:53)
- [willia/tui/theme.py](/home/illan/Documents/coding/willia/willia/tui/theme.py:14)
- [tests/test_tui_render.py](/home/illan/Documents/coding/willia/tests/test_tui_render.py)
- [tests/test_tui_keys.py](/home/illan/Documents/coding/willia/tests/test_tui_keys.py)
- [tests/test_tui_screen.py](/home/illan/Documents/coding/willia/tests/test_tui_screen.py)

Nothing from the brief was intentionally omitted. Per the offline/no-TTY acceptance boundary, I did not perform a live terminal or API conversation.