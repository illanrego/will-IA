# P5b–P5d brief: focus and hints, then yank and help, then themes

Read first: **`docs/TUI.md`** (the design, the keymap in section 2, the technical choices in section
3, the slices in section 4), `sketches/005-rail-data-hover/index.html` (the approved layout **and the
`data-tip` explanations**, which are the source text for the hint line and the help overlay), and the
current code: `willia/tui/{app,render,screen,theme,__init__}.py`, `willia/cli.py`, `willia/config.py`,
`tests/test_tui_*.py`.

This brief carries **three slices, in this order**. Do them in order and make sure each is complete
and the suite is green before moving to the next. If you cannot finish all three, finish P5b
completely, stop, and say plainly in your report what is missing — a partial slice reported honestly
is worth more than three half-done ones.

## What already exists (do not rebuild it)

The shell is in and measured: alternate screen with the terminal always restored, a pure renderer
whose durable transcript is cached and sliced per frame, a rail built from layout-neutral
`(label, value, style)` tuples through a **non-blocking** engine snapshot, two modes, key scrolling,
one-clipped-line tool packets, `Ctrl-b` to collapse the rail, three palettes as data, `willia --tui`,
and the turn running on a worker thread that reports through a queue. Nothing in this brief may
regress any of that, and in particular an **idle screen must keep writing nothing** (asserted in
`probes/p5a-tui-proof.py`).

## P5b — pane focus and the hint line

1. **Focus.** Two panes: `transcript` and `rail`. `Tab` cycles; `Ctrl-w h/j/k/l` moves directly as
   well (h/j/k/l follow the pane layout: left/right between panes, up/down inside a pane). The
   focused pane is visually marked — use `rule_strong` on its separator or a `you`-coloured marker,
   and name it in the status line.
2. **Rail focus.** `j`/`k` move a highlighted row (the row itself in `strong`, on `panel`); the
   selection must survive a refresh. `Enter` folds a group's rows (the `#`-prefixed headers keep
   their own collapse state) and `Esc` unfolds. Collapsed groups show their header plus a count.
3. **Transcript focus.** `Enter`/`Esc` fold the focused record to one line and back. A long paste is
   several records of one kind, so folding acts on the record under the cursor only — and the
   renderer already supports a collapsed line (`record_lines(..., collapsed=True)`).
4. **The hint line.** The bottom line, in this order: `MODE`, the focused pane, the state
   (`compacting` / `streaming` when applicable), and **the explanation of whatever is focused**,
   taken from a new `willia/tui/hints.py`. Its `HINTS` mapping is keyed by the rail's fact labels
   (`memory`, `view`, `queue`, `here`, `session`, `cache`, `jobs`, `go`, `codex`, `model`, and each
   `l0`…`l7`) and by record kind (`user`, `will`, `reasoning`, `tool`, `echo`, `work`, `note`). Carry
   the texts over from the sketch's `data-tip` attributes **verbatim where they apply**, and write
   the rest in the same register: second person, plain, no jargon, one sentence where one suffices.
   An unknown key shows nothing rather than a placeholder. Truncate the hint to the row with `fit`
   and never let it wrap the status line.
5. **A progress readout for the drain.** The rail's `state` row already carries `settled · N
   unbuilt`; make sure that number is what the user sees while the tree is catching up, and put the
   pending count in the `queue` row. This is the only number that shows compaction progress and it
   must not be hidden by the fold.

**Acceptance for P5b (the session will run these, but they must be true):** `Tab` switches panes and
the status line says which; the focused rail row is marked; `Enter` folds the focused thing and
`Esc` unfolds it; the hint line shows the focused thing's explanation and changes when focus moves;
the suite stays green with `redraw()` still skipping identical frames.

## P5c — yank, clipboard, and the help overlay

1. **Yank.** `y` yanks the focused line, `Y` the whole record it belongs to, and `v` starts a visual
   range (movement extends it, `v` or `Esc` cancels) whose `y` copies every line in the range. The
   text is the **record's own text from the log**, not the rendered line, so what lands on the
   clipboard is what was actually said. The status line confirms with the byte count for a moment.
2. **Clipboard.** OSC 52 (`ESC ] 52 ; c ; <base64 of the utf-8 text> BEL`) written to the terminal —
   that is what a TUI can do with no dependency and it works through tmux with `set-clipboard
   external`, which is what this machine has. Additionally, when `$WAYLAND_DISPLAY` or `$DISPLAY` is
   set and `wl-copy` or `xclip` is on PATH, pipe the same text to it as a belt-and-braces fallback.
   Never block on the fallback: a bounded timeout, and a failure is silent (the status line already
   reported the yank). Base64 of the payload only — no secrets beyond what was on screen.
3. **The `?` overlay.** `?` (and `:help`) opens a centred panel listing the keys in the design's
   table plus the `HINTS` texts for the record kinds, scrollable with `j`/`k`, closed with `Esc`,
   `q` or `?`. It replaces the frame, it does not disturb the transcript's scroll offset, and it is
   drawn with the same helpers as everything else (no second renderer).

**Acceptance for P5c:** a yank writes a well-formed OSC 52 sequence carrying the base64 of the
record's own text (assertable against an injected writer); the range yank copies exactly the lines in
the range; `?` opens and closes without changing `scroll_offset`; a clipboard failure never raises.

## P5d — themes

`TuiConfig` in `willia/config.py` with `theme: str = "blue"` (add `tui` to `load`'s `known` set), and
`:theme blue|green|mixed` switches live, repainting immediately and confirming in the status line. An
unknown name leaves the theme alone and says so. The palette table already defines all three with
identical token sets; do not add a fourth and do not change the existing values.

**Acceptance for P5d:** `:theme green` changes the SGR sequences a draw emits; the config default is
honoured; an unknown name is refused without changing the theme. Four counts of the token set must
stay identical.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/tui/*.py`, `willia/config.py`, `willia/cli.py` (only if a flag is needed),
  `tests/test_tui_*.py`, and `docs/TUI.md` **only** to record anything the design left open. Do not
  touch `willia/toolkit.py`, `willia/prompts.py`, `willia/chat.py` (beyond nothing), `willia/web.py`,
  `willia/vision.py`, `willia/fs.py`, or any other doc.
- **No new dependency.** Standard library only.
- The system prompt, the tool array, the compaction envelope and the log format do not change.
- A broken draw must never kill the chat, and must never be silent (`draw_error` is already wired to
  the status line).
- Keep the existing tests passing; where a test's expectation genuinely changes, update it and say so.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then list the files you changed, paste the `HINTS` mapping's keys, and state plainly anything you
could not do.
