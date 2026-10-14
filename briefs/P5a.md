# P5a brief - the TUI shell: alternate screen, transcript, modes, a real turn

Read first: **`docs/TUI.md`** (the design, the keymap, the slices) and `sketches/005-rail-data-hover/index.html`
(the approved layout and the exact palette). Then `willia/chat.py` (the turn loop and `_on_delta`),
`willia/cli.py`, `willia/store.py` (records and `Log.range`), `willia/config.py`.

`docs/TUI.md` is the contract. This brief does not re-describe it; it fixes the boundaries and the
acceptance for **slice P5a only**.

## What P5a is, and what it is not

**In:** a new `willia/tui/` package that takes over the terminal, renders the transcript from the log,
reads keys in two modes, streams a real turn, scrolls, shows the static rail, and is reachable as
`willia --tui`. Plus the one hook `willia/chat.py` needs so a display can see the stream.

**Out — do not build these in this pass:** pane focus (P5b), folding, the hint line, the `?` overlay,
yank or any clipboard code, `:theme` and any command other than `:q` and `:help` (P5c/P5d). The rail
renders; it is not focusable yet.

## Deliverables

1. **`willia/chat.py` — one optional sink.** `Chat.turn(texts, *, sink=None)`. With `sink=None` the
   behaviour and **stdout must be byte-identical to today** (the REPL, the probes and the existing
   tests prove it). With a sink, the turn reports to it instead of printing: a model delta (with its
   kind, `"content"` or `"reasoning"`), each tool call with its arguments, each tool result with the
   wall-clock milliseconds the dispatch took (`time.monotonic` around it), the two `notice` paths that
   print today (the empty-reply retry line and the `ClientError` line), and the end of the turn.
   Choose the mechanics; the requirement is the unchanged default and the four facts above.
2. **`willia/tui/theme.py`** — the three palettes as data, each with exactly the same 14 tokens, plus
   truecolour to 256/8 degradation. Terminals have no alpha, so the hairline tokens are the **resolved
   solids** given below. `:theme` arrives in P5d; the module ships now so the palette is data, not
   literals in the renderer.
3. **`willia/tui/screen.py`** — the terminal layer: raw mode (`termios`/`tty`), the alternate buffer,
   hide/show cursor, size, `SIGWINCH`, key decoding (printable, `Enter`, `Esc`, `Tab`, `Backspace`,
   `Ctrl-*`, and the CSI sequences for arrows, `Home`, `End`, `PgUp`, `PgDn`), and a full repaint. Every
   write goes through one injected writer so tests can assert the exact byte stream. **The restore path
   is the critical part:** alternate buffer off, cursor shown, raw mode off, on `:q`, `Ctrl-C`, an
   unhandled exception and `SIGTERM`.
4. **`willia/tui/render.py`** — a **pure** function: `(records, in_flight, width, height, theme) ->
   lines`, where a line carries its text and its style token. No terminal, no tty, no clock. Per
   record kind, from the 005 sketch: `user` in the `you` colour; `will` as prose; `note` dim; `work`
   with the `[Name]` tag in amber; `tool` as a packet line (`→ name args`, name in the agent colour,
   arguments dim); `echo` as up to three dim lines then a `… n more` marker. Wrap to the pane width
   using `unicodedata.east_asian_width` for double-width characters; treat a record's text as whole
   (the log already splits long text).
5. **`willia/tui/app.py`** — the loop and the modes: `NORMAL` and `INSERT` per `docs/TUI.md` §2, the
   scroll offset, history, and a redraw on every event and keystroke. `INSERT`: `i`/`Enter` to enter,
   `Enter` sends, `Ctrl-j` inserts a newline, `Ctrl-u` clears the line, `Ctrl-w` deletes a word,
   `Up`/`Down` walk history, `Esc` returns to normal. `NORMAL`: `h j k l`, `Ctrl-d`/`Ctrl-u`, `gg`, `G`,
   `:` for a one-line command prompt with `:q` and `:help` only. The app renders the log; after a turn
   it re-reads it, so a `work` record that arrived mid-conversation appears on its own.
6. **`willia/tui/__init__.py`** — `run(chat)` as the entry point, plus the rail's data gathering. The
   rail's facts must be a **list of (label, value, style) tuples built from a mapping**, so a later
   slice can add the Codex account and its resets by adding a source rather than touching layout. For
   P5a fill it from: the tree levels and their node counts, the total node count, the view's byte size
   against 64–128 KB with the marker position, `settled` and the unbuilt count, the queue depth, the
   newest id, the session id, the last call's cache percentage from the meter, the running job count,
   and the OpenCode Go windows with their reset countdowns (from `willia/usage.py`, which already
   fetches them). Not the Codex line: its source is a later slice.
7. **`willia/cli.py`** — a `--tui` flag beside the existing modes, and an honest refusal when stdout is
   not a terminal (the REPL stays the default; the flip is a later decision).
8. **Tests** — all offline, no tty: `tests/test_tui_render.py` (each record kind, wrapping, width,
   double-width characters, scroll offsets, and that all three palettes define the same token set),
   `tests/test_tui_keys.py` (mode transitions, motions, the insert-mode editing rules, history,
   `:q`/`:help`), `tests/test_tui_screen.py` (with a fake writer: the alt-screen enter and leave
   sequences, the restore on an exception, colour degradation for 256 and 8, and that `sink=None` on
   `Chat.turn` still produces today's stdout exactly).

## The three palettes, exactly (terminals have no alpha: the hairline tokens are resolved solids)

| token | blue | green | mixed |
|---|---|---|---|
| `bg` | `#06090F` | `#050A09` | `#06090F` |
| `panel` | `#0A101B` | `#081412` | `#0A101B` |
| `rule` | `#1D2631` | `#192C24` | `#1E2834` |
| `rule_strong` | `#374C5D` | `#305747` | `#374C5D` |
| `body` | `#DDE7F5` | `#DCEFE6` | `#DDE7F5` |
| `dim` | `#7E8DA6` | `#7B948B` | `#7E8DA6` |
| `reason` | `#8E9DB6` | `#8AA69C` | `#8E9DB6` |
| `agent` | `#8FDCFF` | `#7BEBBE` | `#8FDCFF` |
| `data` | `#8FDCFF` | `#7BEBBE` | `#7BEBBE` |
| `amber` | `#FFC069` | `#EFCC77` | `#FFC069` |
| `red` | `#FF6E73` | `#FF6E73` | `#FF6E73` |
| `ok` | `#7FEBC8` | `#9FD4FF` | `#7BEBBE` |
| `you` | `#EDF3FB` | `#EDF3FB` | `#EDF3FB` |
| `strong` | `#F2F7FE` | `#F2FBF6` | `#F2F7FE` |

These are the values tuned by measurement against Illan's own terminal; do not "improve" them, and do
not quantise the truecolour path.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only the files named above. Do not touch `willia/toolkit.py`, `willia/prompts.py`,
  `willia/client.py` (beyond nothing at all), `willia/vision.py`, `willia/web.py`, `willia/fs.py`, or
  any doc.
- **No new dependency.** Standard library only: `termios`, `tty`, `signal`, `unicodedata`, `os`.
  No curses, no textual, no rich.
- Nothing in the system prompt, the tool array, the compaction envelope or the log format changes.
- The TUI writes nothing but the terminal: no new files, no config writes in this slice.
- A tool or a turn never raises into the loop; the TUI must not either — a broken draw must not kill
  the chat.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then paste `render.py`'s signature and the rail's fact-building code, list the exact files you changed,
and state plainly anything in this brief you could not do.
