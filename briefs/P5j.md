# brief: stop the flicker, and give the input a bounded field with a steady block cursor

Illan: *"it's still flashing when I'm typing and when its giving output, which is distracting. also we
still need some minor treatment on the UI - take hermes as an example: the field I type is clearly
bounded and we have the indicator of where am I in the input text field (this green block, that
sometimes blink, I'd like one that doesn't blink)."*

Read first: `willia/tui/screen.py` (the paint path and the alternate-screen handling),
`willia/tui/app.py` (the frame, the insert-mode editing, the status line), `willia/tui/render.py`,
`willia/tui/theme.py` (the existing tokens - do not add or rename one), and `probes/p5a-tui-proof.py`
(the pty driver that already measures idle silence).

## 1. The flicker: every paint is unsynchronised

Measured: `ESC[?2026` appears **nowhere** in `willia/tui/`. The paint is
`HOME + ERASE_BELOW + background + the frame`, written as one buffer, with no synchronised-update
block around it. The terminal is therefore free to display the frame halfway through - erase shown,
rewrite not yet done - which is the flash he sees on every keystroke and on every streamed chunk.
Alacritty supports the sequence and tmux passes it through.

- Wrap **every** paint in `ESC[?2026h` ... `ESC[?2026l`. Both the full frame and any partial write.
  If the terminal ignores the sequence it is a no-op, so no detection is needed and no capability
  check should be attempted.
- Keep the existing properties: nothing is written when the frame is unchanged, and an idle TUI
  writes **zero** bytes. The sync block must not be emitted for a paint that writes nothing.
- Do not add a timer, a frame-rate cap or a repaint loop to work around this. The cause is the
  missing sync, not the frequency.
- If (and only if) the sync alone still leaves visible tearing on a real terminal, additionally write
  **only the rows whose content changed**, in order, instead of the whole frame - but only as a
  second step, and say so in your report.

## 2. The input gets a bounded field

Today the compose area is a bare line above the status row. Illan wants it **clearly bounded**, as
Hermes' is:

- A field with a visible top edge - a rule in the theme's `rule` token across the transcript's width -
  and a prompt marker at its left (a single character, `❯` unless the code base already uses something
  better), in the `agent` token when the field is focused and `dim` when it is not.
- The text inside it in the `you` token while it is his own input, wrapped if it is long, with the
  field growing by whole rows as needed and never pushing the status row off the screen.
- The field is present in insert mode and while a turn streams; in normal mode it collapses to the
  single status row (do not invent a second empty box).
- The mode and the keymap hint stay where they are, under or beside the field - not inside it.
- Reuse the rail's measure for the transcript's width so the field lines up with the blocks above it;
  a two-space indent inside the field reads better than flush text.

## 3. The caret: a steady block, drawn by us

He sees a blinking block; he wants a steady one. Do not try to configure the terminal's cursor - own
it:

- Keep the hardware cursor **hidden** for the whole run (it already is on entry; make sure nothing
  re-shows it, and that the exit path still restores it, including on an exception).
- Draw the caret as a **filled block** at the caret's column inside the input field: the character
  under the caret rendered in reverse video (swap the foreground and background of that one cell), or
  a solid block when the caret sits at the end of the text. It never blinks: it is painted with the
  frame and stays painted.
- It must follow the caret through insert-mode editing: after a character, after backspace, after
  `Ctrl-w`, after a `Ctrl-j` newline, after moving with the arrows or `Ctrl-a`/`Ctrl-e` if those exist,
  and at both ends of the line.
- Wide characters (CJK, emoji) and combining marks must not shift the block by a cell: use the
  renderer's existing cell-width helper, and assert it in a test.
- The block is drawn only when the terminal is at least as wide as the field; a one-column terminal
  must not crash.

## 4. Tests

- **Sync**: every paint that writes anything begins with `ESC[?2026h` and ends with `ESC[?2026l`, and
  a paint that writes nothing emits neither. Assert on the screen's writer, not on a mock's call count.
- **Idle**: the existing proof still holds - zero bytes while idle - and it must still hold with the
  sync block present.
- **The field**: its top rule spans the transcript's width, its marker takes the focus token, it
  grows by rows for long input without moving the status row, and it is absent in normal mode.
- **The caret**: for a given input and caret index, the block lands in the expected column; at the end
  of the text it is a solid block; after backspace and `Ctrl-w` it moves correctly; a wide character
  before the caret does not shift it by a cell; a zero-width terminal does not crash.
- **The hardware cursor**: nothing in any paint path emits the show-cursor sequence, and the exit path
  emits it exactly once - including when the app raises.
- Keep every existing intent green: the merge, the clip counts, the ladder bars, the dim labels, the
  rhythm, the yank, the inspection panels, the frame diffing.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/tui/screen.py`, `willia/tui/app.py`, `willia/tui/render.py`,
  `willia/tui/theme.py` (only if a token is genuinely missing - prefer reuse), and `tests/`.
- **No new dependency.** Standard library only. No palette token added or renamed.
- The keymap, the themes, the tool array, the system prompt, the log format and the rail's content do
  not change. Nothing on the startup path may block.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then, with the pty driver, paste the byte counts for: idle, one keystroke in insert mode, and a
streaming turn - each with the sync block visible in the captured bytes. State plainly anything you
could not do.
