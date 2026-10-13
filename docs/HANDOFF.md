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
2. `docs/PHASES.md` — **the live phase state** (P2 is closed, P3's tooling is in) and each phase's
   acceptance criteria.
3. `docs/ENGINE.md` §0 (canon and precedence), §8 (the Hermes surface that was removed), §9 (canon
   conformance claim by claim).
4. `docs/WIRE-FORMATS.md` §1 (the wire, measured) and §9 (the usage surface **and** the meter's own
   line shape).
5. `docs/DELEGATES.md` — the subprocess contracts.
6. `docs/TOOLS.md` — the seven-tool array, and §9's parity table for what comes next.
7. `briefs/P4a.md` — **the next slice, already briefed and deliberately not run.** It carries two
   decisions owed by Illan and a proposal for five new schemas to red-line before anything is
   written.
8. `~/.hermes/skills/software-development/willia/SKILL.md` and its `references/opencode-go-wire.md` —
   the workflow, the traps, the Codex model catalog, the notes-import recovery procedure.

## Check state before acting (do not trust this file)

```
git -C ~/Documents/coding/willia log --oneline -3
git -C ~/Documents/coding/willia status --porcelain=v1      # expect clean
git -C ~/Documents/coding/willia ls-remote origin main      # expect == local HEAD
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q  # 272 passed
willia --status                                             # the real chat's state
willia --usage                                              # the meter + the plan's windows
```

## State as of this handoff (2026-10-13, 25 commits, pushed; HEAD `fc953dc`)

- **P0, P1 and P2 are closed; P3's bootstrap and tooling are in; P3's ride and P4 are open.**
  - **P2a** the delegates as real subprocesses; **P2b** the three native tools. P2's acceptance ran
    for real, both ways: a Codex job driven through `dispatch` (`probes/p2-live-proof.py`) and once
    more through a real model turn (`probes/p2-turn-proof.py`), plus real `web_search` /
    `web_extract` / `vision` round-trips (`probes/p2b-live-proof.py`).
  - **P3 tooling:** 134 `note` records imported; the usage meter landed (`willia --usage`,
    `<root>/logs/usage.jsonl`, `WIRE-FORMATS` §9) with a read-only `scripts/session-report.py`. Both
    were exercised against the live account (`probes/p3-usage-proof.py`). **What remains is his ride.**
- **272 tests green** (was 241 at the last handoff). Live evidence now includes two real Codex jobs,
  real web and vision calls, and a real plan-window read.
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
  editing `willia/prompt-default.md` reaches new chats only — that gap is Decision 1 in
  `briefs/P4a.md`, and it is why a tool batch cannot be landed silently.

## Next, in order

1. **Take the two decisions in `briefs/P4a.md`** — how an existing chat learns a new tool set, and
   what `terminal` is allowed to do — and red-line the five proposed schemas. Nothing in that batch
   is implemented today; the five schemas do not exist in `docs/TOOLS.md`, and only he should write
   an interface that becomes the cache anchor. Then run the brief as one Codex pass.
2. **His first real ride with tools** (P3 item 2). Each failure the ride surfaces gets a repro, a
   fix, a test and a commit — the engine's own `FINDINGS.md` discipline carried over.
3. **Then the remaining P4 batches**, in this order: browser, computer use, voice, cron, MCP,
   skills. Each rewrites the cache prefix once, then freezes.

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

## Traps already paid for (full list in the skill)

- **`codex exec` refuses to run outside a git repository**, and the configured delegate workspace
  (`~/Documents/coding`) is not one. Without `--skip-git-repo-check` every job dies at exit 1 while
  the whole offline suite stays green — the tool call still returns `started` and one honest `work`
  record still lands. This is why the delegate acceptance needs a **real** job.
- **The prompt is a per-chat, seeded file**, so a tool batch cannot reach an existing chat by editing
  the repo default. Check both before promising a batch changed the model's behaviour.
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
