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
`https://github.com/illanrego/will-IA.git` (pushing is fine now; he says push).

## Read first, in this order

1. `docs/README.md` — non-negotiables, repo map, reading order.
2. `docs/PHASES.md` — **the live phase state** and each phase's acceptance criteria.
3. `docs/ENGINE.md` §0 (canon and precedence), §8 (the Hermes surface that was removed), §9 (canon
   conformance claim by claim).
4. `docs/LOOP.md` and `docs/WIRE-FORMATS.md` §1 (the wire, measured — session header, reasoning,
   the cap trap, the cache numbers).
5. `docs/DELEGATES.md` — the contract for the next slice.
6. `~/.hermes/skills/software-development/willia/SKILL.md` and its `references/opencode-go-wire.md` —
   the workflow, the traps, the Codex model catalog, and the notes-import recovery procedure.

## Check state before acting (do not trust this file)

```
git -C ~/Documents/coding/willia log --oneline -3
git -C ~/Documents/coding/willia status --porcelain=v1      # expect clean
git -C ~/Documents/coding/willia ls-remote origin main      # expect == local HEAD
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q   # expect 241 passed
willia --status                                             # the real chat's state
```

## State as of this handoff (2026-10-13, 20 commits, pushed)

- **P0 closed** (canon vendored, the engine's nine modules copied under the rename list with the
  Hermes surface stripped, the prompt byte-verified against the canon's §5 block, the tool array
  guarded). **P1 closed** in three slices: P1a client/config/env/session, P1b loop + records +
  dispatch + REPL + launcher, P1c pump + lock + watchdog + `--restore-view`. **P3a done**:
  `willia --notes` (files or directories, a preview that writes nothing, bounded resumable
  completion). **P2a done**: the delegates as real subprocesses.
- 241 tests green. Live evidence so far: turn→turn cache 96.6%, turn→compaction 95.8%, a real
  conversation where the model called `zoom` and answered from the log, a 66 KB notes import
  verified exactly-once, and a real ride by Illan himself.
- The real chat `~/.willia`: 134 `note` records from five of his markdowns (curated: identity,
  rules and context; the strategy compendium was deliberately held back as a snapshot of open
  tasks), plus his own turns. View ≈77 KB, settled, nothing unbuilt.
- `willia` is installed as a uv tool (`~/.local/bin/willia`, editable, so repo changes apply).

## Next, in order

1. **The live delegate proof — P2's missing acceptance.** Everything verifies the mechanism with
   local processes only; no real Codex job has run through willia yet. Drive
   `dispatch("delegate_codex", {...})` from a probe (not a model turn — it costs less) with a
   trivial task, model `gpt-5.6-sol`, a temp working directory; then assert: the job directory and
   its `brief.md`/`run.log`/`report.md`, **exactly one `work` record** with the `[label]` prefix,
   the child chat under `agents/<label>/`, `zoom("<label>")` opening it, and **the file the delegate
   claims to have written — read by you, not taken on faith**. Then once through a real turn.
   Run the job from a background terminal call, never foreground (a 180 s cap kills long jobs).
2. **P2b — the remaining native tools:** `web_extract` and `vision` need no dependency (stdlib and
   his OpenRouter key); `web_search` needs one decision — the `ddgs` package (keyless, what Hermes
   uses by default) or a keyed API hand-rolled. Ask him before adding a dependency.
3. **P3 — the first ride with tools**, then the usage meter (`logs/usage.jsonl`, `willia --usage`,
   plus the Go plan's rolling/weekly/monthly windows from `GET /zen/v1/usage`) and a read-only
   session report script.
4. **P4 — the parity batches, in this order:** shell + files (`terminal`, `read_file`, `write_file`,
   `patch`, `search_files`) — this is the one that unlocks his willcuts and posting CLIs as plain
   commands rather than tools — then browser, then computer use, then voice, cron, MCP, skills.
   Each batch rewrites the cache prefix once and then freezes.

## The rules he holds you to

- **The canon rule.** One authority: `docs/optchat-gist.md`. The docs are its reading; the code is
  corrigible; `~/Documents/coding/opthermes` is history, never authority. If code and canon
  disagree, the canon wins and the code changes with a test.
- **Briefs → `codex exec`.** Default `gpt-5.6-sol` @ high; `gpt-6-astra` @ high only where a late
  catch costs more than the model. (The kickoff's `gpt-6-sol` was a typo: it does not exist and
  400s instantly.) Write the brief to `briefs/`, read the report from `reports/`, and **read the
  diff** — a delegate's summary is not evidence. Every run costs its own ~6–8 k tokens of agent
  prompt, so batch small changes into one brief. One window fits roughly two large astra runs.
- **Verify before committing:** read the diff, run the suite yourself, and for any behaviour change
  prove it red-first (`git stash push -- <files>`, expect the new test to fail, restore) or by
  mutation (break the behaviour, watch the test fail, restore). Commit per verified step; push when
  he says. A delegate must never run git — say it in every brief, in those words.
- **Long jobs run in the background**, never in a foreground terminal call.
- **English corrections:** verb forms and prepositions only. Never flag capitals or apostrophes —
  that is his deliberate style, and he asked for it to stop. This resumes in the new session.
- Brief replies, options over monologues, he stays in the loop, you do not open the next slice
  unasked.

## Traps already paid for (full list in the skill)

- A brief that scopes a delegate's latitude as a *count* ("exactly two edits") makes it stop and
  ask instead of applying the rename list — scope it as a set.
- A delegate implements a workaround around a defect instead of reporting it (three times now):
  read the diff. The last one was a schema offering a model name that does not exist.
- The frozen tool array and the prompt are the cache anchor: changing either costs one prefix
  rewrite, and that is why `docs/TOOLS.md` and `willia/toolkit.py` must move in lockstep (a test
  enforces it).
- Never rebuild `view.json`; a missing one is an explicit unavailable state and `--restore-view`
  validates before adopting.
- A notes import has **no dedup**: `probes/verify-notes-import.py` names which files landed, and the
  recovery is to import only the failures.
