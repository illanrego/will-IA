# brief: the four tools that need no dependency

Illan has approved these four. They land as **one batch** because the cache prefix is rewritten once
per batch and then frozen — that is the design, and doing them separately would pay for four rewrites
of the same anchor.

Order matters: finish cron **completely** before starting mcp, mcp before skills, skills before todo.
If you run short of room, a fully finished earlier tool beats four half-built ones. Say plainly in
your report what you did not finish.

Read first: `docs/TOOLS.md` (the tool contracts and the rules about the frozen array), `docs/PHASES.md`
(P4's remaining batches), `willia/toolkit.py` (the array and the group block), `willia/tools.py` (the
existing native tools), `willia/prompts.py`, `willia/dispatch.py`, `willia/jobs.py` (how a subprocess
delegate is run — the pattern to follow), `willia/store.py`, and the existing tests for the native
tools.

## The rule that governs all four

`willia/toolkit.py`'s array and `docs/TOOLS.md` move **in lockstep** — a test enforces it. Changing
either rewrites the prompt's prefix once; that is expected here and only here. Do not touch
`SYSTEM_PROMPT`, the log format, the view, the compaction rubric or the TUI. Standard library only:
no new package, no new binary, no network service that willia itself must host.

## 1. `cron` — schedules, with no daemon

A job is a record in the chat's own log (kind `cron`), so scheduled work is compacted and summarised
like everything else, and survives a restart because the log does.

- The tool: `schedule` (a name, a prompt or a shell command to run, and when), `list`, `cancel`.
  "When" is a small, honest grammar: `every 30m`, `every 2h`, `daily 09:00`, or an ISO-8601 timestamp.
  Reject anything else with a clear message rather than guessing.
- No daemon, no thread, no watcher. Instead the CLI gains **`willia --cron-due`**, which runs whatever
  is due *now* and exits — so the system's own cron (or a systemd timer) is the scheduler, and willia
  stays a plain program. Document the crontab line in `docs/TOOLS.md`.
- Running a job's prompt goes through the normal turn path so its cost is metered like any other turn;
  a job's shell command runs through the same workspace and process-group rules `terminal` already
  uses, with a timeout, and its output lands as an `echo`-style record.
- `willia --cron-due` must be safe to run twice, and must not double-run a job that is already due in
  the same minute: a job records when it last ran.

## 2. `mcp` — the tools of an MCP server, over stdio

A JSON-RPC 2.0 client over a child process's stdin/stdout. No package: `subprocess` plus `json`.

- The tool: `list` (the servers configured, and each one's tools), and `call` (a server, a tool, and
  its arguments).
- Configuration in a small file under the chat's root or the workspace: a name, a command, its
  arguments and its environment per server. Start the child on demand, keep it alive between calls
  within a turn, and **always** close it when the turn ends — no orphan processes.
- The handshake is the documented one: `initialize`, then `notifications/initialized`, then
  `tools/list` and `tools/call`. A server that fails to handshake, dies mid-call or answers with an
  error must produce a readable tool result, never a hang: every read has a timeout, and a timed-out
  server is killed and reported as such.
- Keep the raw MCP tool schemas out of willia's own array (that would rewrite the prefix and multiply
  it): `mcp` is **one** tool with `list`/`call`, and the model discovers the rest through it.

## 3. `skills` — procedures from disk

Hermes' convention, which Illan already maintains: a directory of `SKILL.md` files with YAML
frontmatter (`name`, `description`) and a body.

- The tool: `list` (name plus description, from the frontmatter) and `read` (the whole `SKILL.md`).
- Search the conventional places, in this order: `$WILLIA_SKILLS` if set, then `<workspace>/skills`,
  then `~/.hermes/skills`. Bound the depth so a symlink loop cannot hang the call, and cap the number
  of entries returned with the exact count of what was omitted.
- A file without valid frontmatter is skipped, not crashed on; a `read` of an unknown name lists the
  nearest matches.
- Read-only: never write inside a skill directory.

## 4. `todo` — the planning list, in the log

Deliberately skipped in P4a; it belongs here because it is the same kind of thing as `cron`.

- The tool: `add`, `list` (with the done ones marked), `done`, `drop`. A todo is a record in the
  chat's log, so it compacts with everything else and needs no file.
- `list` shows the open items first with their ids, then the done ones, and never truncates silently.

## Tests (each tool, plus the shared rules)

- `cron`: the "when" grammar parses the accepted forms and refuses the rest; a due job runs once and
  not twice in the same minute; a job's cost is metered; `--cron-due` on a chat with nothing due is a
  quiet no-op.
- `mcp`: against a **stub server** (a small script the test starts, no real server): the handshake
  order, `list`, `call`, a server error, a server that exits mid-call, and a server that never
  answers (the timeout kills it and the call returns). Assert no child process is left running.
- `skills`: frontmatter parsing, the search order, the depth bound, an invalid file skipped, a missing
  name's suggestions, and that nothing is written.
- `todo`: add/list/done/drop, the ordering, the ids, and that everything is a record.
- **Shared**: `willia/toolkit.py` and `docs/TOOLS.md` agree (the existing lockstep test must pass with
  the new tools in both); the array is now the old count plus four, and `docs/TOOLS.md` says so; the
  prompt's composed length is recorded in the report (the cache anchor moved once, which is intended).

## Constraints (every one, again)

- **No git commands of any kind.** No commit, stash, branch, restore, diff or reset.
- Edit only: `willia/` (the toolkit, tools, prompts, cron/mcp/skills/todo modules, cli), `docs/TOOLS.md`,
  `docs/PHASES.md`, and `tests/`.
- **No new dependency.** Standard library only. Nothing may be downloaded.
- Do not change `SYSTEM_PROMPT`, the log format, the view, the compaction rubric, the TUI or the
  existing tools' behaviour.
- Nothing on the startup path may block, and an idle TUI still writes zero bytes.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then, for each of the four: the tool's name and its argument schema as it appears in the array, and
one sentence on what you verified beyond the suite. State plainly anything you did not finish.
