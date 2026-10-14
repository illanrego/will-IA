# TUI.md — the modal terminal interface

The REPL prints everything through one path, so the model's reasoning and its answer arrive as one
indistinguishable stream (`chat._on_delta` ignores the stream kind). This replaces that display. It is
**display only**: the system prompt, the tool array and the log format are the cache anchor and the
record, and none of them changes here.

## 0. The one principle

**The TUI is a renderer over the log.** The transcript is a function of `log.range()` plus the
in-flight stream; the sink that carries that stream is only for what has not been logged yet. So a
redraw needs no state of its own beyond a scroll offset and the current mode, and the thing on screen
is always what is actually in the memory.

## 1. Layout (the 005 sketch, which Illan approved)

- **Left rail, 30 columns.** Everything the machine knows, one panel: the tree levels with node
  counts, the view size against its 64–128 KB sawtooth, the compaction queue, the newest id, then a
  hairline and the group `session · cache · jobs · go · codex · model` — including both accounts'
  usage **and their reset countdowns**, which arrive with the percentages and cost no extra call.
  The rail ends with the command hint, pinned to the bottom.
- **Centre, the rest.** The turn, oldest first: your message, the model's reasoning in a dim
  left-ruled gutter, the reply in the body colour, tool calls as one-line packets (`→ terminal …  0`),
  tool output collapsed behind a fold, delegate reports badged `[Name]`.
- **Bottom line, one line.** The mode (`NORMAL` / `INSERT`), the focused pane, the explanation of
  whatever is focused, and the two accounts' percentages.

## 2. Modes and keys

Explicitly modal, vim-shaped, and bounded: no registers, no macros, no operators with text objects.

| Context | Keys |
|---|---|
| insert | `i` or `Enter` to compose · `Enter` sends · `Ctrl-j` newline · `Ctrl-u` clear · `Ctrl-w` delete word · `Up`/`Down` history · `Esc` back to normal |
| normal | `h j k l` move · `Ctrl-d`/`Ctrl-u` half page · `gg`/`G` oldest/newest · `Tab` or `Ctrl-w h/j/k/l` switch pane · `Enter`/`Esc` fold the focused thing · `n`/`N` next/previous match |
| yank | `y` focused line · `Y` whole record · `v` … `y` a visual range (all to the system clipboard) |
| search | `/` in the transcript |
| command | `:` — `:zoom 40 8`, `:date 162`, `:usage`, `:jobs`, `:view`, `:theme blue\|green\|mixed`, `:q` |
| help | `?` — an overlay of the explanations |

`:` for commands and `/` for search, the vim idioms. The explanations written for the 005 hover layer
become the `?` overlay *and* the bottom line's text for whatever is focused: hover does not exist in a
terminal, and this is better, because a focused thing can be yanked and searched.

## 3. Technical choices

- **No new dependency, and no curses.** The terminal goes into raw mode with `termios`/`tty`; the
  screen is the alternate buffer (`ESC [?1049h`); every draw is our own ANSI with **24-bit colour**, so
  the palette is exactly what was signed off rather than quantised into 256 indexed slots. Curses
  would own the screen and its colour pairs are indexed, which is the one thing this design cannot
  afford now that the contrast was tuned by measurement.
- **The terminal is always restored** — alternate buffer off, cursor shown, raw mode off — on every
  exit path: `:q`, `Ctrl-C`, an unhandled exception, and `SIGTERM`. This is the classic TUI failure and
  it is a test, not a hope.
- **The stream is coalesced.** A delta arrives per token, so the frame is painted at most every
  ~33 ms, and once more when the turn ends. A paint per token flickers: measured at 61 full repaints
  for one short reply before the fix.
- **The transcript is rendered once per change, not once per frame.** A frame slices a cached wrap of
  the last 300 records. Re-wrapping the whole log twice per keystroke cost 185 ms and ~400 ms per
  character end to end; it is 0.3 ms now. Wrapping builds style runs, and per-character width is
  memoised.
- **The rail reads a non-blocking snapshot.** A compaction wave holds the engine lock across a whole
  pass, so a frame that waited on it measured 6.5 seconds; it now keeps the numbers it has and the
  status line says `compacting` instead of stalling.
- **The turn runs on a worker thread** and reports through a queue, so the UI keeps reading keys and
  repainting while the model streams and while the post-turn pass runs. `:q` during a pass no longer
  looks dead.
- **The transcript shows the conversation, not the memory.** Imported `note` records are hidden unless
  `:notes` is toggled - the live chat holds 134 of them and they buried everything - and tool output
  folds to two lines.
- **Resize** on `SIGWINCH`: re-measure and redraw. A draw is a full repaint; at this size that is
  cheap and it removes a whole class of partial-update bugs.
- **Width**, not length: `wcwidth`-style handling via `unicodedata.east_asian_width` (stdlib), because
  the log holds non-ASCII text and a misplaced column breaks the rail.
- **Colour depth** degrades: truecolour when `COLORTERM` says so, otherwise 256, otherwise 8.
- **Clipboard** is OSC 52 (`ESC ] 52 ; c ; <base64> BEL`), which tmux passes through (his
  `set-clipboard` is `external`), falling back to `wl-copy` then `xclip` when it is unavailable.

## 4. Slices

Each slice is one Codex run with its own acceptance, and each is rideable rather than a stub.

- **P5a — the shell.** Alternate screen, the transcript renderer, insert/normal modes, a real turn,
  scrolling by key, the static rail, the theme module with all three palettes, `willia --tui`.
  Acceptance: the terminal restores on every exit path; a real turn streams with reasoning and answer
  visually distinct; `j k Ctrl-d Ctrl-u gg G` scroll continuously inside the app; the renderer is a pure
  function and is tested without a tty.
- **P5b — focus and the hint line.** Pane focus, folding, and the focused thing's explanation on the
  bottom line, drawn from the 005 texts.
- **P5c — yank, clipboard, help.** `y`/`Y`/visual-range yank through OSC 52 with the tool fallback, and
  the `?` overlay.
- **P5d — themes.** `:theme blue|green|mixed` plus a `tui.theme` config default, switching live.

`willia --tui` stays an explicit flag until P5c lands; the REPL remains the default until the TUI has
earned the seat, and the flip is its own decision.

## 5. What must not change

- The system prompt, the tool array, the compaction envelope, the log format. None of them.
- The event sink added for streaming defaults to today's `print` behaviour, so the REPL, the probes and
  every existing test are unaffected.
- Nothing per-turn may enter the prompt: the rail's numbers live on screen, never in a request.
