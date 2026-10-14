# brief: the transcript gets framed, and the tree gets its bars

Illan's verdict on the live TUI: *"it's not looking good. can we approximate from the initial sketch
(005)? the terminal calls are being shown in their entirety, hermes does this 'framing' on lines and
colors to separate the reasoning from the output and also from my input... also where are the bars
drawn in the tree? i want it to look like the prototype you shown me."*

All three complaints are confirmed by rendering a frame to text. The transcript is a flat wall: a user
record, a tool call, a raw JSON result, the answer and a work record all sit at the same weight with
**no labels, no rules and no spacing between blocks**. The result's JSON runs onto a second line its
clip did not catch. And the rail's ladder is bare numbers - `l0 7` - with no bars at all, while the
005 reference draws a proportional bar per level.

Read first: `sketches/005-rail-data-hover/index.html` (the reference: the ladder with its bars, the
`data-tip` explanations, the register of the labels), `docs/TUI.md`, `willia/tui/render.py`,
`willia/tui/app.py`, `willia/tui/__init__.py`, `tests/test_tui_render.py`.

## 1. The rail: the ladder gets its bars

In `build_rail_facts`, each level row's value becomes a **proportional bar plus its count**:

```
l0         ████████████ 162
l1         ██████ 81
l2         ███ 40
```

- The bar is **12 cells** wide, filled with `█` in proportion to that level's count against the
  largest level's count, rounded (`round(12 * count / biggest)`), and **at least one cell** for any
  non-zero count. The remainder is spaces - do not draw `░`.
- One space, then the count, right-aligned, exactly as the sketch has it.
- `nodes`, `#view`'s gauge, `state`, `queue`, `newest` and the facts group do not change.
- Same change for the count that follows the ladder (`nodes`), which already exists.

## 2. The transcript: one framed block per record

Every record becomes a block: a full-width dim hairline rule, a label line, then the content. Here is
the exact target for a 118-column terminal with a 29-column rail (the 005 look, at this width):

```
MEMORY                       │────────────────────────────────────────────────────────────────────────
l0         ████████████ 162  │ILLAN
l1         ██████ 81         │the posting CLI broke after the batch — check it and fix it.
l2         ███ 40            │
 nodes     321               │────────────────────────────────────────────────────────────────────────
VIEW                         │TOOL · delegate_codex
bytes      3,061 B           │task "Create the ledger module, wire it into the CLI, prove it with a focused test, and…
                             │
─●───────────  64K-128K       │────────────────────────────────────────────────────────────────────────
settled · 0 unbuilt          │RESULT
QUEUE                        │{"status": "started", "name": "Fix-CLI", "agent": "codex", "report_path": …
 0                           │… 1 more line
HERE                         │
 6                           │────────────────────────────────────────────────────────────────────────
FACTS                        │WILLIA
session    8e2621d5          │Delegated to Codex as Fix-CLI; its report will arrive on its own.
cache      95.3%             │
jobs       1                 │────────────────────────────────────────────────────────────────────────
go         3 / 14 / 24%      │WORK · [Fix-CLI]
go ↺       3h44m / 4d17h     │flag order was reversed in cli.py; patch applied, suite green.
codex      12 / 18%          │Ran: uv run pytest -q -> 12 passed.
codex ↺    3h51m / 6d9h      │… 1 more line - full report: /home/illan/.willia/jobs/Fix-CLI-20261014T080000Z/report.md
model      ds-v4.1-flash     │
NORMAL · transcript · You.…  │
```

The grammar, per record:

- **The rule**: the full transcript width, drawn with `─` in the theme's rule colour. It is the
  separation *between* blocks, so a block is never preceded by a blank line - the rule is the gap.
- **The label**, in the record's own colour, on its own line, with no padding:
  `ILLAN` (a `user` record), `WILLIA` (a `will` record), `TOOL · <name>` (a `tool` call),
  `RESULT` (an `echo`), `WORK · [<label>]` (a `work` badge), `NOTE` (a `note`, only when notes are
  shown), `THINK` (reasoning, when it is shown as its own record).
- **The content** under it, wrapped, at the transcript width. A `user` record keeps the user colour,
  an answer the body colour, reasoning the dim reasoning colour with its existing `│` gutter.
- **The reasoning stays where it is**: it is a stream kind inside the answer, and the existing dim
  treatment and gutter must not change.
- **The header** above the transcript (`session · model`, whatever is there today) stays.

## 3. Clipping: nothing may sprawl

- **A tool call is one line.** `TOOL · delegate_codex` then, on the next line, the arguments as
  `key "value"` pairs separated by two spaces, hard-clipped to the width with `…`. Long values are cut
  inside the quotes. The old behaviour showed the raw JSON across three lines; that is the complaint.
- **A result (`echo`) is at most 3 lines**, then a dim `… N more line(s)` where N is exact.
- **A work badge is at most 3 lines**, then a dim `… N more line(s)`; when the report file exists its
  path goes in that trailing line as above.
- Reasoning and an answer are **not** clipped - they are the conversation.
- Every wrapped or clipped line is a whole line; nothing may be cut mid-word by the padding step. (The
  rail's `state` row currently renders `settled · 0 unbuil` - the value must be allowed the room it
  has, and truncated with `…` rather than chopped.)

## 4. Tests

- `tests/test_tui_render.py` will need updating; **the intents must survive** - wrapping, the reasoning
  gutter, the clip counts, the visual range, the note toggle, the rail's memoisation. Update the
  assertions to the new shape rather than deleting them, and say in the report which ones changed
  meaning and why.
- Add: a block test asserting the rule/label/content triple for each record kind, with the label text
  exactly as above; a test that the clip counts are exact (`… 1 more line` vs `… 2 more lines`); a test
  that a tool call occupies exactly one line however long its arguments; and a ladder test asserting
  the bar's filled-cell count for a known set of level counts, including the at-least-one-cell case for
  a level of 1.
- Keep every existing idle-silence property: the frame is still compared before writing, and painting
  still homes rather than clearing.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/tui/render.py`, `willia/tui/app.py`, `willia/tui/__init__.py`,
  `willia/tui/theme.py` (only if a colour is genuinely missing), `tests/test_tui_render.py`,
  `tests/test_tui_keys.py`.
- **No new dependency.** Standard library only.
- The palette, the system prompt, the tool array and the log format do not change. Do not touch
  `willia/toolkit.py`, `willia/prompts.py` or anything under `willia/` outside the TUI.
- The hint line, the keymap, the themes and the yank behaviour stay exactly as they are.
- Nothing on the startup path may block, and an idle TUI still writes zero bytes.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then paste the frame your change produces for this exact record set, rendered with

```
uv run --no-project python probes/frame-text.py
```

(a copy of that harness is at `~/.hermes/cache/scratch/frame-text.py` if it is missing) and state
plainly anything you could not do.
