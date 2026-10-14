# brief: inspection commands inside the TUI

Illan: *"what about the commands inside tui? is there no way to see view etc?"* There is not. From
inside the TUI he can switch palettes, toggle notes, open the help overlay and quit; he cannot see
the view, the tree, or the chat's full state without leaving. The `?` overlay already proves the
machinery: a read-only panel that scrolls and closes without disturbing the transcript.

Add four `:` commands, each opening that same overlay with real data.

Read first: `willia/tui/app.py` (the `:` command handling, the help overlay, the non-blocking engine
peek, the rail snapshot), `willia/tui/render.py`, `willia/tui/__init__.py` (`build_rail_facts`),
`willia/cli.py` (`_print_usage`, and wherever the state block is printed), `willia/view.py`,
`willia/tree.py`, `scripts/session-report.py`, `docs/TUI.md`.

## The four commands

- **`:view`** - what the model actually receives. The header shows the byte count, the compaction
  range it covers (first and last record id) and whether it is settled; the body is the view's own
  text (`<chat>` ... `</chat>`), wrapped, scrollable. This is the single most interesting screen in
  the program: it is what the constant-size window contains.
- **`:tree`** - the summary tree: the per-level counts with their bars and the node total, then the
  roots, then the coverage (which record ids the view points at, and the count still unbuilt, as
  `settled` does in the rail).
- **`:status`** - the same facts the CLI's `--status` prints: the session, the record count by kind,
  the view's bytes and coverage, the tree's node count, whether it is settled, the unbuilt count, the
  compactor's state and any jobs.
- **`:usage`** - the meter: the local totals (calls, input, output, cache read/write, reasoning, split
  by turn and compaction) and both accounts' windows with their reset countdowns, exactly as
  `willia --usage` shows them.

## How they must behave

- **One overlay, four feeds.** Reuse the help overlay's panel: a bordered read-only region, `j`/`k`
  and `Ctrl-d`/`Ctrl-u` scroll it, `g`/`G` jump, `q` or `Esc` closes it and **restores the
  transcript's exact scroll offset and selection**, exactly as the help panel already does.
- **Never write the log.** These are inspection only: no record is appended, no view is rebuilt, no
  file is created. `:view` and `:tree` read through the same non-blocking path the rail uses; if the
  engine is mid-drain the panel must say `compacting` rather than block - a blocking read here would
  freeze the UI, which is the bug class this program has already paid for twice.
- **`:usage` must not stall.** The account windows come from a network fetch. Reuse whatever the
  rail's startup fetch does - the panel opens immediately with the local totals and fills the windows
  in when they arrive, or shows `unavailable`. Nothing on this path may block the event loop.
- **A colon command stays a colon command.** The command line, its completion and its refusal of an
  unknown name must keep working; add the four names to whatever list the refusal prints.
- The keymap, the rail, the frame, the prompt, the tool array and the log format do not change.

## Tests

- Each command opens the panel with the expected content against a stub chat: `:view` shows the
  view's own text and its byte count; `:tree` shows the level counts; `:status` shows the record
  kinds; `:usage` shows the totals.
- Scrolling moves, `q`/`Esc` closes, and the transcript's offset and selection come back unchanged
  (assert before and after).
- A locked engine shows `compacting` and does not block: assert the call returns while the stub's
  engine context manager is held.
- Inspection writes nothing: assert the log's record count and the file set are unchanged after each
  command.
- An unknown `:` name is still refused, and the four new names are accepted.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/tui/app.py`, `willia/tui/render.py`, `willia/tui/__init__.py`,
  `tests/test_tui_keys.py`, and a new `tests/test_tui_inspect.py`.
- **No new dependency**, no palette or theme change, no new files outside those test files.
- Nothing on the startup path may block; an idle TUI still writes zero bytes.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then paste the panel text each of the four commands produces against the stub chat, and state plainly
anything you could not do.
