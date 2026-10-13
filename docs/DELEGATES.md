# DELEGATES.md — the subprocess contracts

willia never contains a coding agent. It **spawns** one, in the background, and gets a report
later. A delegate is reached only through the shell, exactly the way any program calls `git`.
If a delegate is broken, the target is swapped; nothing inside willia changes.

## 1. The two delegates

| | `delegate_codex` | `delegate_hermes` |
|---|---|---|
| binary | `$(npm prefix -g)/bin/codex` (verified `/home/illan/.nvm/versions/node/v24.15.0/bin/codex`, `codex-cli 0.153.4`; **not on PATH**) | `hermes` (verified `/home/illan/.local/bin/hermes`) |
| model | explicit `-m`: the account's catalog is `gpt-5.5`, `gpt-5.6-sol`, `gpt-6-astra` — **verified live 2026-10-13** (`gpt-6-sol` does not exist; the kickoff's name was a typo for `gpt-5.6-sol`, and a bad name fails instantly with a 400, so a retry costs nothing) | the default profile's own model — **pass nothing** |
| brief delivery | a file, `$(cat brief.md)` | `--query-file <path>` (or `-` for stdin) — no shell quoting |
| report | `-o <report>.md` (the last message) | stdout (`--format text`) |
| default dir | the configured workspace (a `willia.delegates.codex.dir`) | its own workspace |
| cost | the Codex plan | the host profile's provider |

## 2. `delegate_codex` — the exact command

```
$(npm prefix -g)/bin/codex exec \
  -m gpt-5.6-sol \
  -c model_reasoning_effort="high" \
  --approve-for-me \
  --skip-git-repo-check \
  -C <workdir> \
  -o <report>.md \
  "$(cat <brief>.md)"
```

- **Always pass `-m`.** `~/.codex/config.toml` defaults to `gpt-6-astra` at `medium`; relying on
  the config silently spends the expensive model. The account's catalog lives in
  `[tui.model_availability_nux]` (`gpt-5.5`, `gpt-5.6-sol`, `gpt-6-astra`), and all three were
  exercised live on 2026-10-13.
- Flags verified against `codex-cli 0.153.4 --help`: `-m/--model`, `-c <key=value>`,
  `--approve-for-me`, `-C/--cd`, `-o/--output-last-message`, `--json`, `-s/--sandbox`,
  `--skip-git-repo-check`. `codex exec` also has `resume` / `fork` / `review` subcommands.
- **Model policy** (the user's rule, by undo cost): `gpt-5.6-sol` at high for most tasks;
  `gpt-6-astra` at high only where a late catch costs more than the model (the interface-critical
  and precision-critical steps — P0b's prompt transcription is the canonical example); `gpt-5.5` for
  the smallest mechanical edits. A wrong or unavailable model name fails immediately with a 400, so
  a mis-typed run wastes seconds, not quota. Never two large astras in parallel.
- Every run carries its own agent prompt (~6–8 k tokens measured even for a one-word reply), so
  batch small changes into one brief instead of one run per file.
- The brief is a **file**, written before the run, and it is what the report is judged against.
  It cites the doc (`ENGINE.md`, `LOOP.md`, …), it never re-describes it.
- `--json` is available for a stream of events; v1 uses the plain form plus `-o` (simpler to
  verify). `[P2: revisit if structured progress is wanted]`

## 3. `delegate_hermes` — the exact command

```
hermes chat --oneshot --query-file <brief>.md --format text --in <workdir>
```

- Verified: `hermes chat` takes `-q/--query` or `--query-file PATH` (`-` reads stdin, nothing is
  shell-interpreted), `--oneshot` (implied on a non-TTY), `--format text|stream-json`, `--in DIR`,
  `-m/--model`, `-t/--toolsets`, `--reasoning`, `--max-turns`, `--run-budget`.
- **No `-m`**: the delegate inherits the default profile's model, by design
  (`SCOPE.md`: "his default profile; inherits its default model — nothing to override").
- The report is stdout (or the last assistant message under `--format stream-json`).
- A Hermes delegate is a full agent with its own skills/tools: use it when the task wants Hermes's
  own capabilities, not as a cheaper Codex.

## 4. Background mechanics and the `work` record

1. The tool call returns **immediately**:
   `{"status": "started", "name": "<label>", "agent": "<codex|hermes>", "report_path": "<abs>"}`.
   The call itself is logged as one `tool` record (the brief is its `arguments`).
2. A supervisor thread owns the process: `subprocess.Popen` with the working directory, stdout and
   stderr captured to `<report>.log`, a wall-clock cap, and a kill on timeout (process group).
3. On exit: read the report (`-o` file, else stdout). Empty or missing → the failure is named.
4. Append exactly one `work` record:
   - success: `"[{name}] {report}"` (clipped head+tail at 30,000; the full text stays on disk at
     `report_path`, and the record names it).
   - failure: `"[{name}] failed: {reason}"` (exit code, timeout, or "no report"). **Never silent** —
     a delegate that produced nothing must be visible in the memory, or the next turn will believe
     the work happened.
5. Create the child: `<root>/agents/<label>/` gets its own chat (below). The label is this job's
   name; a label that already exists gets a numeric suffix at **creation** time, decided by us, not
   by a lookup table (`ENGINE.md` §8.4). `zoom("<Name>")` then opens the child.
6. Delivery: if a turn is running, the `work` record is handed to it **between tool calls**;
   otherwise it is used to start the next turn (it is the message after the view).
   The master never sleeps, polls, or waits.
7. `kind: "work"` is how the memory labels it; the model sees `[Name] …` and the recipe's prompt
   rule ("each one's report reaches you as a message starting [Name]").

## 5. The child chat (what `zoom("Name")` opens)

The recipe is explicit: "Its own steps stay in its own log (`zoom("Name")`), out of the chat." So a
delegate is not only a report — it gets a real **child chat**, built by the same engine code:

- `<root>/agents/<label>/` holds its own `main/`, `tree/`, `view.json` and `lock`.
- Records: the brief as one `user` record (split if long), the process output as `echo` records
  (clipped head+tail at 30,000), the final report as one `will` record.
- Resolution is a **directory name**, not an index lookup: the label must be a single safe path
  component and the directory must hold a `view.json` (`ENGINE.md` §8.4). No index file, no
  repointing rules.
- The label is chosen at creation — the tool's `name` argument, sanitised, with a numeric suffix
  only on a real collision. It is both the name `zoom("Name")` uses and the `[Name]` tag in the
  `work` record.
- The child's view renders from the child's own tree, so `zoom("Name")` returns real memory, not a
  stub. Its steps never enter the master's chat; only the one `work` record does.

## 6. Status and inspectability

- `/status` lists running delegates (label, agent, started at, elapsed).
- The report file and the process log stay on disk next to the data root
  (`~/.willia/jobs/<label>-<ts>/`), so a verdict can always be re-derived from raw evidence —
  the standing rule: never trust a delegate's summary.

## 7. Failure modes

| Mode | Behaviour |
|---|---|
| non-zero exit | `work` record `"[{name}] failed: exit <code>"` + the last 2,000 characters of the process log |
| timeout (default 30 min, configurable) | process group killed; `work` record `"[{name}] failed: timeout after <n>m"` |
| empty report, exit 0 | `work` record `"[{name}] failed: the delegate produced no report"` |
| binary missing | the tool returns `{"error": "codex not found at <path>"}`; nothing is spawned, nothing is logged as a `tool` |
| brief file unreadable | same shape as above, named in the error |
| the process dies with the app | the child registry entry stays; the `work` record never lands. On the next start, `/status` reports the orphaned job dir (`jobs/<label>-<ts>/` with no report) so it is not silently swallowed. |
