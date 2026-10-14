# brief: drop cron, finish the other three

A previous run built four tools — `cron`, `mcp`, `skills`, `todo` — and was **killed mid-flight**
because Illan dropped cron. Its output is in the working tree, uncommitted. The suite says: **430
passed, 3 failed**, and all three failures are in `tests/test_toolkit.py` — the lockstep between
`willia/toolkit.py`'s array and `docs/TOOLS.md`, which is the piece the run had not reached. So the
work is nearly there and your job is to finish it correctly, not to rewrite it.

**First, audit what is actually in the tree.** Read the diff of the modified files (`willia/chat.py`,
`willia/cli.py`, `willia/dispatch.py`, `willia/prompts.py`, `willia/store.py`, `willia/toolkit.py`)
and the four new modules. Say plainly in your report if something is half-wired, inconsistent or
missing — the previous run was interrupted, so do not assume its work is coherent.

## 1. Remove `cron` completely

Illan's words: *"you shouldn't mind with cron, drop it. when I need cron I'll use hermes gateway."*
So cron must be gone as if it had never been proposed:

- Delete `willia/cron.py` and `tests/test_cron.py`.
- Remove every reference to it: the array entry in `willia/toolkit.py`, the group/prompt block in
  `willia/prompts.py`, the `--cron-due` flag and its handling in `willia/cli.py`, whatever
  `willia/dispatch.py`, `willia/chat.py` and `willia/store.py` gained for it, and every mention in
  `docs/TOOLS.md` and `docs/PHASES.md`.
- The tools are **`mcp`, `skills`, `todo`** — three, not four. The array's count is the pre-batch
  count plus three, and no test may still reference cron (grep for it before you finish and say in
  your report what you found).

## 2. Make the lockstep pass, and check the three tools against the brief

The three failures in `tests/test_toolkit.py` are the array-vs-documentation contract. Fix them by
making the code and `docs/TOOLS.md` agree — never by weakening the test.

Then verify the surviving three against the rules the original brief set:

- **`mcp`** — exactly **one** tool with `list` and `call` (the servers' own tools stay out of the
  array so the cache prefix cannot multiply); a JSON-RPC 2.0 handshake (`initialize`, then
  `notifications/initialized`, then `tools/list` / `tools/call`); a server that never answers is
  killed by a timeout and returns a readable error instead of hanging; **no orphan child process
  survives a turn**.
- **`skills`** — the search order `$WILLIA_SKILLS`, then `<workspace>/skills`, then
  `~/.hermes/skills`; a depth bound that a symlink loop cannot hang; `list` reports name and
  description from the frontmatter and gives the exact count of what it omitted; `read` suggests near
  matches for an unknown name; nothing is ever written inside a skill directory.
- **`todo`** — a todo is a **record in the chat's log**, not a file, so it compacts with everything
  else; `add`, `list` (open items first with ids, then the done ones, never truncating silently),
  `done`, `drop`.

Anything in those three that the interrupted run left half-done or wrong, finish it. Keep its tests
that are sound; replace any that assert the wrong contract, and say which and why.

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/`, `docs/TOOLS.md`, `docs/PHASES.md`, `tests/`.
- **No new dependency.** Standard library only.
- Do not change `SYSTEM_PROMPT`, the log format, the view, the compaction rubric, the TUI, or the
  behaviour of any tool that already existed.
- Nothing on the startup path may block; an idle TUI still writes zero bytes.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail —
it must be green, with no cron test left anywhere. Then paste the array's names and the array's
count, and the argument schema of each of the three tools. State plainly what the interrupted run had
left incomplete.
