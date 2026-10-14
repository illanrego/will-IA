# brief: one block per answer, and 005's tones on the right side

Illan's second verdict on the framed TUI:

> "it's all too white (font colors) and we having some lines on the output (with the WILLIA signaling
> author) at times that doesn't make sense, the whole answer should be within a block, not several
> arbitrarily cut. on all three themes we're lacking colors and contrast, is all too whitey (the
> sidebar is almost cool, the big problem is the right side). take another look at our reference
> `sketches/005-rail-data-hover/index.html`."

Both are real, and both have a measured cause. Read `sketches/005-rail-data-hover/index.html`'s
`/* ---------- the turn ---------- */` block (about lines 105-135) before you touch anything.

## 1. One block per answer - the split is a streaming artifact

`~/.willia`'s log holds a run of **six consecutive `will` records** for a single answer. The client
flushes its buffer at a size boundary, and the boundary lands **mid-word**: fragment 1 ends
`...The branch ` and fragment 2 begins `` `feat/notebook-shell-redesign` has 4 c ``. So the answer is
drawn as six rules and six `WILLIA` labels, which is what he is seeing.

- **Merge consecutive records of the streaming kinds into one block**: `will`, `user` and
  `reasoning` - the kinds whose text is one continuous stream. Concatenate their texts with **no
  separator at all** (the split is mid-word, so a newline or a space would corrupt the text), then
  wrap and draw **one** rule and **one** label for the whole run.
- **Never merge** `tool`, `echo`, `work` or `note`: each is its own event. Two consecutive `tool`
  records are two different calls, and concatenating their JSON would be nonsense. (A run of six
  `will` records merges; a run of two `echo` records does not.)
- The `source_text` / `source_index` bookkeeping must survive the merge: a yank on any line of the
  merged block still copies **the log's own text** for that record, and the visual range still spans
  what the user sees. The existing yank test must keep passing.
- Grouping happens in the iteration step, not inside `record_lines` (which must keep rendering exactly
  one record), so the note toggle, the collapsed rendering and the per-record tags still work.

## 2. The right side gets 005's tones - it is too white

The palettes are already 005's byte for byte, so this is about **which token each part uses**. From
the reference, the transcript's rule is that the bodies carry the colour and the **labels stay dim**;
the accents (`agent`, `amber`, `ok`, `data`) are small and rare:

| line | 005 | use |
| --- | --- | --- |
| the author label (`.who`) | `dim`, letterspaced, uppercase | `ILLAN`, `WILLIA`, `RESULT`, `NOTE`, `THINK` |
| his message (`.say.you`) | `you` | unchanged |
| the answer (`.answer`) | `body`, with `.answer strong` in `strong` | see the markdown note below |
| the reasoning (`.think .body`) | `reason`, behind a `rule_strong` left border | unchanged (already right) |
| the tool name (`.pkt .tool`) | `agent` | the `TOOL · <name>` label keeps `agent` |
| the tool args (`.pkt .args`) | `dim` | unchanged |
| the output (`.out pre`) | `dim`, behind a `rule` left border | **add the `│ ` gutter to `RESULT`** |
| the work tag (`.work .tag`) | `amber`; its text `dim` | unchanged |
| the exit code / success (`--ok`) | `ok` | use for a work report that says it succeeded, if that is unambiguous in the text; if not, leave it |

So: **the `ILLAN` / `WILLIA` / `RESULT` / `NOTE` / `THINK` labels all become `dim`**, exactly as the
reference has them. Keep the `WORK · [badge]` label in `amber` and the `TOOL · <name>` label in
`agent`, because the reference colours those two, and they are the only bright things in the lane.

## 3. Markdown-lite, because that is where the missing colour is

His live answers are full of `**bold**` and `` `code` `` and the markers are currently printed raw.
The reference renders `strong` for bold and uses `data` for inline code/values. So:

- In a `will` body, `**text**` renders as the text alone in the `strong` token, and `` `text` ``
  renders as the text alone in `data`. Both markers are dropped from the display.
- Everything else is untouched, and a lone `*` or backtick that is not part of a pair stays literal.
- Wrapping still happens on the whole text with the spans carried across the wrap; it must not break
  the gutter, the visual range, or `source_text` (which stays the record's raw log text, markers and
  all, so a yank copies what the model actually wrote).
- Do this for `will` bodies only. Do not touch the reasoning, the output or his own message.

## 4. Tests

- Merging: six consecutive `will` records render as one rule, one `WILLIA` label, and one continuous
  wrapped body whose text is the six texts concatenated with nothing between them; two consecutive
  `tool` records still render as two blocks; a merged block's yank still returns the log's text.
- Tones: assert the token each line uses - the labels `dim`, the tool name `agent`, the work tag
  `amber`, his message `you`, the answer `body`, `**x**` → `strong`, `` `x` `` → `data`, and the
  `RESULT` gutter in `rule`.
- Keep every existing intent, including the exact clip counts, the ladder bars, the idle silence and
  the frame-diffing.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/tui/render.py`, `willia/tui/app.py`, `willia/tui/__init__.py`,
  `tests/test_tui_render.py`, `tests/test_tui_keys.py`.
- **No new dependency**, and do not add or rename a palette token: the three palettes are signed off
  byte for byte and a test pins their token set.
- The system prompt, the tool array, the log format, the keymap, the themes and the yank behaviour do
  not change. Nothing on the startup path may block; an idle TUI still writes zero bytes.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then render the frame with `uv run --no-project python probes/frame-text.py`, paste it, and say plainly
anything you could not do.
