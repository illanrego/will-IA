# brief: close the gap between the TUI and 005, detail by detail

Illan's ask: *"maybe you could delegate to codex to make it more like the 005 html? cause its a lot
of little details like spacing etc (beyond of course the colour issue)."*

So this is a **fidelity pass** against the reference, not a redesign. The structure is already
approved and must not change: one rule + one dim label + one content per block, streaming records
merged into a single block, the ladder's bars, the hint line, the keymap, the themes. What is
missing is 005's rhythm and its remaining tones.

Read `sketches/005-rail-data-hover/index.html` — in particular the `/* ---------- the turn ---------- */`
block and the rail's (`.k`, `.lvl`, `.gauge`, `.fact`) rules — and compare it against the frame your
change produces (`uv run --no-project python probes/frame-text.py`).

## 1. The vertical rhythm (the big one)

005 has no full-width rules between the centre's blocks: it has **margins**. The TUI has rules
(approved — keep them) but no rhythm at all, which is why it still reads as a wall. Give it 005's
spacing, translated into rows:

| 005 | the TUI |
| --- | --- |
| `.stage { padding: 24px 30px }` | one blank row above the first block and below the last |
| `.say.you { margin: 4px 0 20px }` | one blank row before the rule of exactly one block: his message |
| `.think { margin: 0 0 18px }` | one blank row after the reasoning block |
| `.answer { margin: 0 0 20px }` | one blank row after the answer block |
| `.packets { gap: 3px; margin: 12px 0 18px }` | consecutive tool packets pack tight: no blank rows between them, one blank row before the first and after the last |
| `.out { margin: 0 0 20px; padding-left: 23px }` | the output block keeps its `│ ` gutter and gets one blank row after it |
| `.work { margin: 0 0 20px }` | one blank row after |
| `.fact`, `.lvl` (the rail) | the rail keeps the section hairline; no other blank rows |

Rules: **never two blank rows in a row** (collapse them), never a blank row between a rule and its
own label, and never a trailing blank row at the end of the transcript. The frame must still fill
the pane at 30 rows without an off-by-one at the bottom.

## 2. The answer's paragraphs and lists

005 gives paragraphs their own margins and renders lists as lists. In the TUI, a blank line inside
an answer should survive as **one** blank row (never collapse an author's paragraph break), and a
line starting with `- ` or `* ` or a digit followed by `. ` should render with the marker in `dim`
and the text in the body tone, wrapped with hanging indentation of two cells so the second line
lines up under the first character of the text, not under the marker.

## 3. The rail's remaining tones

From the rail's CSS, the details that are still wrong:

| 005 | now | wanted |
| --- | --- | --- |
| `.lvl .bar { color: var(--data); opacity: .62 }` | bars at full `data` | the filled cells use the `data` token, the **count** uses `dim`; the bar is never the brightest thing in the rail |
| `.k` (the section headers) | `dim`, uppercase | `dim`, uppercase, and **letterspaced** by one space per character (`M E M O R Y`) when the rail is wide enough — drop the spacing rather than truncate the word |
| `.total { color: var(--data); opacity: .85 }` | the `nodes` count in `data` | keep `data`, it is the total |
| `.gauge .track { color: var(--rule-strong) } .gauge .mark { color: var(--data) }` | verify both | the track in rule_strong, the marker in data |
| `.fact .v { color: var(--body) } .v.num { color: var(--data) } .v small { color: var(--dim) }` | mostly right | a numeric value uses `data`; a text value uses `body`; anything in parentheses or after a `·` (the reset countdown, "0 unbuilt") uses `dim` |
| `.palette { color: var(--dim) }` | the `?` hint is dim | unchanged |

## 4. Do **not** add these, even though 005 has them

- **No exit-code or duration column on the tool packets.** 005's `.pkt` is a five-column grid
  (arrow, tool, args, exit, ms) and Illan explicitly asked for those two to be dropped. Keep one line
  per call: the tool's name and a clipped `key "value"` argument list.
- No second rail: keep one column, no nested boxes (he asked for that too).
- No font-size changes (a terminal has one size): express 005's size hierarchy with tone only.

## 5. Tests

- Spacing: a test per rule in the table above, asserting the blank rows are exactly where they belong
  and that two blank rows never appear consecutively; a test that the transcript's last line is never
  blank; a test that consecutive tool packets have no blank rows between them.
- Lists: hanging indentation of two cells, the marker in `dim`, and the wrapped text aligned.
- Rail: the header letterspacing (and its fallback when the rail is narrow), the count in `dim`, the
  manner in which a parenthesised or `·`-suffixed part of a value takes `dim`.
- Keep every existing intent green: the merge, the exact clip counts, the ladder bars, the dim
  labels, the yank from `source_text`, the idle silence, the frame diffing.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/tui/render.py`, `willia/tui/app.py`, `willia/tui/__init__.py`,
  `tests/test_tui_render.py`, `tests/test_tui_keys.py`, `tests/test_tui_wrap.py`,
  `tests/test_tui_rail_sections.py`.
- **No new dependency**, no palette token added or renamed, no theme changes.
- The system prompt, the tool array, the log format, the keymap and the yank behaviour do not change.
  Nothing on the startup path may block; an idle TUI still writes zero bytes.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then paste the frame from `uv run --no-project python probes/frame-text.py`, and state plainly
anything you could not do.
