# will.I.A. — resume handoff (fresh session)

Paste-ready continuation. The repo's root `HANDOFF.md` is the **original kickoff** (historical);
this file is the live resume point. Nothing is in flight: the tree is clean, every commit is
pushed, no background process is running.

## What this project is

`~/Documents/coding/willia` — will.I.A., a standalone endless-chat harness (not a Hermes fork,
wrapper or plugin) implementing Taelin's OptChat/UniiChat design: one append-only log, a binary
summary tree, a constant-size view (64–128 KB sawtooth), `zoom`/`date` navigation, and compactions
shaped like turns so they read the turns' cache prefix. Coding is delegated out to Codex/Hermes as
subprocesses; the rest of the tools are native. Remote: `origin` =
`https://github.com/illanrego/will-IA.git` (pushing is fine now; he says push). Deterministic test
runner: `~/.hermes/tools/uv-0.12.3-linux-x64/uv`.

## Read first, in this order

1. `docs/README.md` — non-negotiables, repo map, reading order.
2. `docs/PHASES.md` — **the live phase state** (P2 is closed, P3's tooling is in, P4's first batch has landed) and each phase's
   acceptance criteria.
3. `docs/ENGINE.md` §0 (canon and precedence), §8 (the Hermes surface that was removed), §9 (canon
   conformance claim by claim).
4. `docs/WIRE-FORMATS.md` §1 (the wire, measured) and §9 (the usage surface **and** the meter's own
   line shape).
5. `docs/DELEGATES.md` — the subprocess contracts.
6. `docs/TOOLS.md` — the twelve-tool array, and §9's parity table for what comes next.
7. `briefs/P4a.md` — the brief whose batch just landed, kept as the record of its rulings, with
   `probes/p4a-live-proof.py` as its acceptance. The next brief (P4b, the browser batch) does not
   exist yet.
8. `~/.hermes/skills/software-development/willia/SKILL.md` and its `references/opencode-go-wire.md` —
   the workflow, the traps, the Codex model catalog, the notes-import recovery procedure.

## Check state before acting (do not trust this file)

```
git -C ~/Documents/coding/willia log --oneline -3
git -C ~/Documents/coding/willia status --porcelain=v1      # expect clean
git -C ~/Documents/coding/willia ls-remote origin main      # expect == local HEAD
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q  # 294 passed
willia --status                                             # the real chat's state
willia --usage                                              # the meter + the plan's windows
```

## State as of this handoff (2026-10-14, 54 commits, pushed; HEAD `48cd7b1`)

- **P0, P1, P2 closed; P3's bootstrap and tooling in (both accounts now); P4a landed; the TUI's
  P5a-P5d landed.**
  - **P2a** the delegates as real subprocesses; **P2b** the three native tools. P2's acceptance ran
    for real, both ways: a Codex job driven through `dispatch` (`probes/p2-live-proof.py`) and once
    more through a real model turn (`probes/p2-turn-proof.py`), plus real `web_search` /
    `web_extract` / `vision` round-trips (`probes/p2b-live-proof.py`).
  - **P3 tooling:** 134 `note` records imported; the usage meter landed (`willia --usage`,
    `<root>/logs/usage.jsonl`, `WIRE-FORMATS` §9) with a read-only `scripts/session-report.py`. Both
    were exercised against the live account (`probes/p3-usage-proof.py`). **What remains is his ride.**
  - **P4a landed:** `terminal`, `read_file`, `write_file`, `patch`, `search_files` - the array is 12
    tools now. The prompt gained a constant, code-owned `TOOL_GROUPS` block. Measured: the prefix
    rewrote once and the next call read 95.3% of it; `probes/p4a-live-proof.py` ran all five for real
    and a real turn called `terminal` itself.
- **294 tests green** (241 -> 272 -> 294). Live evidence now includes two real Codex jobs, real web
  and vision calls, a real plan-window read, and the shell batch's own round trip.
- **Vision is on the Go route**, with the chat's own model, not OpenRouter — Illan's call, then
  measured (`probes/willia-probe-vision.py`: HTTP 200 in either part order). The relay's
  list-content restriction is about **tool** messages only.
- The real chat `~/.willia`: 162 records (134 `note` from his curated markdowns, plus `user` 4,
  `will` 16, `tool` 4, `echo` 4), 321 tree nodes across levels 0–7, view 76,809 B, settled, nothing
  unbuilt. **Its `logs/usage.jsonl` does not exist yet** — no metered call has run in the real chat.
- `willia` is installed as a uv tool (`~/.local/bin/willia`, editable). It now has exactly one
  dependency, `ddgs`; after changing dependencies run
  `~/.hermes/tools/uv-0.12.3-linux-x64/uv tool install --editable . --force`.
- **The prompt is per chat.** `Chat.open` writes `~/.willia/prompt.md` only when it is absent, so
  editing `willia/prompt-default.md` reaches new chats only. That is why a tool batch carries a
  constant, code-owned block (`prompts.TOOL_GROUPS`) instead. **His `~/.willia/prompt.md` line 11
  still reads "You have no device shell and no computer-use tool"**, and the block says that line is
  out of date - so the chat works, but the sentence is stale and he may want it gone.

## Next, in order

1. **The remaining parity batches.** Illan asked for them all on 2026-10-14. Split by what they cost:
   **needs nothing** - `cron` (a stdlib scheduler over the existing job records), `mcp` (a JSON-RPC
   client over stdio, no package), `skills` (read `SKILL.md` directories), and the planning `todo`
   skipped in P4a. **Needs a decision** - `browser` is local Playwright per `TOOLS.md` section 9,
   which adds a dependency plus downloaded browser binaries to a project that keeps exactly one
   dependency on purpose; `computer_use` needs a driver process; `voice` needs a TTS backend. Ask
   before adding any of them, and each batch rewrites the cache prefix once, then freezes.
2. **His first real ride with the tools, now including the TUI.** Each failure the ride surfaces gets
   a repro, a fix, a test and a commit. `terminal` is the one to watch: it is ungated by design.
3. **Then the rest of the parity batches**, one at a time; each rewrites the cache prefix once, then
   freezes.

## The rules he holds you to

- **The canon rule.** One authority: `docs/optchat-gist.md`. The docs are its reading; the code is
  corrigible; `~/Documents/coding/opthermes` is history, never authority. If code and canon
  disagree, the canon wins and the code changes with a test.
- **A doc that is wrong is a defect.** Two live runs this session each caught something the offline
  suite could not, and both were fixed in the doc *and* the code together: `codex exec` needs
  `--skip-git-repo-check`, and the vision route is the Go route rather than OpenRouter.
- **Briefs → `codex exec`.** Default `gpt-5.6-sol` @ high; `gpt-6-astra` @ high only where a late
  catch costs more than the model. (The kickoff's `gpt-6-sol` was a typo: it does not exist and 400s
  instantly.) Write the brief to `briefs/`, read the report from `reports/`, and **read the diff** —
  a delegate's summary is not evidence. Every run costs its own ~6–8 k tokens of agent prompt, so
  batch small changes into one brief. One window fits roughly two large astra runs; he tracks it.
- **Verify before committing:** read the diff, run the suite yourself, and for any behaviour change
  prove it red-first (`git stash push -- <files>`, expect the new test to fail, restore) or by
  mutation (break the behaviour, watch the test fail, restore). Commit per verified step; push when
  he says. A delegate must never run git — say it in every brief, in those words.
- **Long jobs run in the background**, never in a foreground terminal call (the 180 s cap kills them).
- **English corrections:** verb forms and prepositions only. Never flag capitals or apostrophes —
  that is his deliberate style, and he asked for it to stop. This resumes in the new session.
- Brief replies, options over monologues, he stays in the loop, you do not open the next slice
  unasked.


## Known follow-ups (small, none blocking)

- The inspection suite's locked-engine test **hangs** on a blocking read instead of failing, so the
  mutation that takes the engine lock unconditionally has to be killed by hand. Give that test a
  bound. (Found while mutation-checking P5i: two verification cells died at the 300 s cap.)
- `willia --status` and `--restore-view` take the log lock, so they refuse while a TUI is riding even
  though `--status` only reads. The read-only report script already proves a lock-free path exists.
- `--status` prints `Last usage: {}` while `usage.jsonl` holds hundreds of calls: a field reading the
  wrong place.

## Traps already paid for (full list in the skill)

- **`codex exec` refuses to run outside a git repository**, and the configured delegate workspace
  (`~/Documents/coding`) is not one. Without `--skip-git-repo-check` every job dies at exit 1 while
  the whole offline suite stays green — the tool call still returns `started` and one honest `work`
  record still lands. This is why the delegate acceptance needs a **real** job.
- **The prompt is a per-chat, seeded file**, so a tool batch cannot reach an existing chat by editing
  the repo default. Check both before promising a batch changed the model's behaviour. The batch must
  also carry a constant block *and* a sentence that supersedes the stale line in the user's own copy,
  or the model is told it has no tool it demonstrably has.
- **Nothing on the TUI's startup path may wait.** A usage HTTP fetch and the rail's engine lock (which
  queues behind a whole compaction drain wave) once left the terminal blank for 25 seconds with zero
  bytes written. The fetch runs on a daemon thread; the rail reads a non-blocking snapshot
  (`Chat.engine_try`) and shows `compacting` instead of stalling.
- **An idle TUI must write zero bytes.** Repainting on the refresh timer and clearing the screen on
  every paint is what made it flash. The frame is compared to the last one, every row is padded to the
  full width, and the paint homes instead of clearing (`ESC[H` + `ESC[J`). Measured: 0 bytes while idle.
- **Never benchmark or probe against a copy of the live chat while it is catching up.** The copy
  re-runs the same compactions, on the real account. A stubbed summarizer for performance work, and a
  chat that has settled, or the numbers are someone else's bill.
- **A swallowed exception in the draw path hides everything.** `redraw()`'s `except Exception: pass`
  turned a `NameError` into a blank screen with nothing in the tests and nothing in the log; a draw
  error now shows on the status line as `DRAW FAILED` while still not killing the chat.
- **Guard the rail against the real builder, not a literal list.** A label renamed in
  `build_rail_facts` ships mute (no hint) and truncated (past the 9-cell column) unless the test builds
  its rows through the builder itself.
- **The suite must never touch `~/.willia`.** `tests/conftest.py` points `WILLIA_HOME` at a temp
  directory for every test, because the meter appends on every model call and some client tests build
  a `Config` whose root defaults to the real chat.
- A brief that scopes a delegate's latitude as a *count* ("exactly two edits") makes it stop and ask
  instead of applying a rename list — scope it as a set.
- A delegate implements a workaround around a defect instead of reporting it (three times now): read
  the diff. The last one was a schema offering a model name that does not exist.
- The frozen tool array and the prompt are the cache anchor: changing either costs one prefix
  rewrite, and that is why `docs/TOOLS.md` and `willia/toolkit.py` must move in lockstep (a test
  enforces it).
- Never rebuild `view.json`; a missing one is an explicit unavailable state and `--restore-view`
  validates before adopting.
- A notes import has **no dedup**: `probes/verify-notes-import.py` names which files landed, and the
  recovery is to import only the failures.
- A tool result is a JSON string, never list-type content in a tool message; a failure is
  `{"error": ...}` and never an exception into the loop.