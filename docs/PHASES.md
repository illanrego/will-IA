# PHASES.md — P0…P3, with acceptance checks

Every phase is: **brief → one Codex run (sol @ high; astra @ high only for the precision-critical)
→ read the diff → run the suite → prove red-first when behavior changed → commit**. Never trust the
delegate's summary. Push only when the user says so.

Green means the check at the bottom of each phase, run by the session, not by the delegate.

## P0 — repo setup

**Deliverables**
1. `git init` in `~/Documents/coding/willia` (no remote yet; first commit = the current
   SCOPE/PLAN/HANDOFF/docs tree).
2. Vendor the Reuse set from `~/Documents/coding/opthermes/optchat/` — the nine files in
   `ENGINE.md` §1 — applying **exactly the §6 rename list** and the **§8 verdicts** (no `cache.py`;
   the ingestion protocol deleted; the host media envelope deleted; our own child resolution;
   `Record.i`), plus `prompts.py` **rewritten** (§5.1) and the one-line `Compactor._request` change
   (§2, §5.1).
3. The vendored test subset: `test_store.py`, `test_tree.py`, `test_view.py`, `test_compactor.py`,
   `test_text.py`, `test_notes.py`, `test_tools.py` — minus the tests that covered deleted host
   code (they go with it; the deletions are named in `ENGINE.md` §8). `test_media.py` is **not
   vendored at all**: every one of its tests drives the host adapter, so P0b writes its direct-API
   replacement (`archive_media` / `media_for` / `retry_pending_media`).
   Leave `test_cache.py`, `test_engine.py`, `test_compaction_prefix.py`, `test_prompts.py`,
   `test_summarizer.py`, `test_registration.py`, `test_shim.py`, `test_host_identity.py`,
   `test_turn_view.py` behind (~3,700 lines of host-coupled tests).
4. The package layout, the rewritten package root (`__init__.py` must not import a Hermes adapter),
   `pyproject.toml`, `.gitignore`, and `README.md` (a short pointer to `docs/README.md`).
5. Apply the §6 rename list (package `willia/`, kind `will`, tools `zoom`/`date`, `OptChat` inside
   strings → `willia`) and port the prompt/tool-name guard test.

**Green**
- `uv run --no-project --with pytest python -m pytest -q` is green on the vendored subset.
- Every vendored file diffs against its opthermes original by **the §6 rename list and the §8
  verdicts only** — for `tree.py`, `view.py`, `compactor.py`, `text.py` and `persistence.py` that
  means byte-identical after the renames; for `store.py`, `notes.py`, `tools.py` and `media.py`,
  only the named deletions. Each file's header records its origin commit and any deviation.
- The prompt/tool-name guard is green: every registered tool name appears in the system prompt.
- `git log` shows the vendor commit; `git status` clean; nothing pushed.

### P0b — the code-shaping half (delegated: Codex, `gpt-6-astra` @ high)

Deliberately a separate run and a separate model: the foundation, and a late catch costs more than
the model. Deliverables (full detail in `briefs/P0b.md`):

1. `prompts.py` — the canon's §5 block **transcribed verbatim** (rename + the computers paragraph
   dropped), the separate compaction constants folded in, plus `build_system_prompt(instructions)`.
2. `compactor.py` — the one-line deviation the §5.1 rewrite forces (the task template alone), and the
   §8.9 review of the per-job `contextvars.copy_context()`.
3. `toolkit.py` — the seven tool schemas as the fixed array, with `TOOL_NAMES` and a deep-copying
   `schemas()`.
4. `tests/test_toolkit.py` — the prompt/tool-name guard, the order, the deep copy, the shapes.
5. `tests/test_media.py` — the direct-API replacement for the dropped engine-driven file.
6. The final package root, `pyproject.toml`, and a root `README.md` pointing at `docs/README.md`.

**Green**
- The suite is green including the new tests.
- The prompt is **byte-verified against the canon**: extracting the §5 block from
  `docs/optchat-gist.md`, applying the two permitted edits, and diffing it against `SYSTEM_PROMPT`
  yields no difference. A paraphrase is a failure, not a style choice.
- `python -c "import willia"` works with no Hermes on the path.

## P1 — core chat

**P1a — the client, config, `.env`, session (done, 2026-10-13; `willia/client.py`, `config.py`,
`envfile.py`, `session.py`).** Verified: 139 tests green (28 new, all offline); my own live proof
(`probes/p1a-live-proof.py`) shows a real turn, a second turn reading **96.6% of its prefix from the
cache**, and a real compaction that built a 359-byte node reading **95.8% from the cache** with zero
reasoning tokens. `~/.willia/session.json` now holds the chat's pinned session id. Open items found
by review, folded into P1b: the `HTTP-Referer` value must be a real, configurable URL; the client
must omit `reasoning_effort` when it is null; `Client.last_usage` should record the usage of every
call (turn and compaction) for the meter; and the loop must send `content: ""` (never `null`) on a
tool-call-only assistant message.

**P1b — the turn loop, REPL v1 and launcher (done, 2026-10-13; `willia/records.py`, `dispatch.py`,
`chat.py`, `repl.py`, `cli.py`).** Verified: 208 tests green (69 new, all offline); my own live proof
(`probes/p1b-live-proof.py`, throwaway root) ran a real three-turn conversation — including a turn
where the model called `zoom {"id": 0, "n": 1}`, our dispatcher returned the real payload, and the
model answered from it — with the cache at **94.1%** on the tool round and **85%** on the long-paste
turn, a compaction wave building 8 nodes above level 0 with a compliant model-written line, and a
restart that loaded the view (10 of 10 records covered, settled, nothing reconciled). Mutation checks
prove the tests bite: breaking render-before-log fails four chat tests, mis-clipping a tool result
fails the clip test. The delegate added two guards I did not ask for and kept: a partially streamed
response is **never retried** (a replay would duplicate text and splice tool arguments), and the
missing-view preflight runs *before* the lock and any tail repair, so a lost view leaves every byte
intact for recovery.

**P1c — the compaction pump, watchdog, recovery and `--restore-view` (briefed: `briefs/P1c.md`).**

**Remaining deliverables**
1. **Model client** (~200 lines): OpenCode Go chat-completions, streaming, tool calls, usage
   capture, bounded retries, the fixed headers, key from `~/.hermes/.env`, and the compaction
   entry point that reproduces the vendored envelope exactly (`WIRE-FORMATS` §4).
2. **Turn loop** (~300): `LOOP.md` §1–§4 — settle, render-before-log, frozen view per turn,
   record classification, long-paste splitting, tool dispatch, `turn_end`.
3. **Compaction wiring** (~200): compactor → client, the background drain (≤8), `tree.save()` /
   `view.save()` after each pass, the recovery reconciliation at startup (`LOOP.md` §5).
4. **REPL v1** (~200) + **config + launcher** (~150): `ENV.md` §5–§6, `willia` as one command.

**Green (all run by the session, with real output)**
- A real multi-turn conversation runs in the REPL: 3+ turns, a tool call, a long paste that lands
  as several records, and a long tool result that lands clipped.
- Every request carries a real `User-Agent` and the chat's stored `x-opencode-session`; a request
  without the latter is proven to fail (400 MissingSessionID), so the client's header set is
  covered by a test against a fake transport.
- Compactions run thinking-disabled with the cap, produce a ≤512-byte line, and the measured
  `cached_tokens` for turn→turn and turn→compaction are recorded in `WIRE-FORMATS` §1.
- `~/.willia/` contains `main/*.jsonl`, `tree/*.jsonl`, `view.json`, `lock`; the log ids are dense;
  `view.json` covers a contiguous prefix; every pair in it has a built node after the first drain.
- A compaction actually ran: a `tree/` node exists whose covering messages are the last few
  records, and its text is ≤512 bytes.
- The envelope is intact: for a compaction the client sends the **same** `[system]` as a turn and
  the same tool array, and its user message is the task template alone (assert on the serialized
  request: system and tools byte-identical to the turn's).
- Cache behaviour is sane: the API `usage` of a second call inside one turn shows
  `prompt_tokens_details`-style cache reads (the real keys are recorded in `WIRE-FORMATS` §1 at
  this point), and a turn→compaction read is measured and written into `WIRE-FORMATS` §4.
- Restart proof: kill the process mid-conversation, restart, and the chat continues with the same
  view bytes (no `ViewStateUnavailable`, no rebuild, no duplicate id).
- Red-first: every behaviour test added in P1 fails against the pre-P1 tree.

## P2 — tools

**Status (2026-10-13): closed.** P2a (the delegates as real subprocesses) and P2b (the three native
tools) both landed, and this phase's own Green checks were run by the session with real output:
a real Codex job through `dispatch`, and once more through a real model turn
(`probes/p2-live-proof.py`, `probes/p2-turn-proof.py`), plus real `web_search` / `web_extract` /
`vision` round-trips (`probes/p2b-live-proof.py`). Two defects the live runs caught, neither
visible to the offline suite: `codex exec` refuses to run outside a git repository, so the frozen
command needs `--skip-git-repo-check` (the configured delegate workspace is not a repository);
and the vision route is the Go route with the chat's own model, not OpenRouter.

**Deliverables**
1. `zoom` / `date` exposed with the renamed schemas and the exact payloads (`TOOLS.md` §2–§3),
   including the prompt-name guard test.
2. `delegate_codex` + `delegate_hermes`: spawn → background supervisor → report → `work` record →
   child registration (`DELEGATES.md` §2–§7).
3. `web_search`, `web_extract`, `vision` native (`TOOLS.md` §5–§7).

**Green**
- A real delegated coding task runs end to end: the call returns immediately, the master does not
  block, the report lands as a `work` record, `zoom("<Name>")` opens the child, and the file the
  delegate claims to have written **exists and is verified by the session**.
- `web_search` and `web_extract` round-trip with real results; `vision` answers a real question
  about a real image through OpenRouter.
- `zoom(40, 8)`-style navigation round-trips against a real chat, including one
  `"span is not summarized yet"` and one `"is not a power of two"` error path.
- No tool result ever places a list-type content part in a tool message (grep the client's
  serialized requests; the Go relay 400s on those).

## P3 — bootstrap and the first rides

**Status (2026-10-13): the bootstrap and the tooling are in; the rides are his.** 134 `note`
records were imported from the curated markdowns. The usage meter landed (`willia --usage`,
`<root>/logs/usage.jsonl`, `WIRE-FORMATS` §9) with a read-only `scripts/session-report.py`, and
both were exercised against the live account. What remains is item 2: a real ride.

**Deliverables**
1. Import `~/Documents/coding/markdowns/OPTCHAT_HELLO.md` as `note` records (`notes.import_notes`),
   as the chat's first memory.
2. First real rides: use it for actual work, then fix only what the rides surface.
3. Then, in whatever order the rides ask for: the usage meter (`/usage`, `WIRE-FORMATS` §9),
   a browse view (`/view` — the rendered view plus record counts), note commands.

**Green**
- The imported notes are navigable (`zoom` opens a note; `date` returns its timestamp) and the view
  covers them.
- The user has had at least one real ride, and each failure it produced has a repro, a fix, a test
  and a commit — the engine's own `FINDINGS.md` discipline carried over.

## P4 — parity tools (post-v1, batched)

**Deliverables:** the tool groups in `TOOLS.md` §9, one batch per run, each batch frozen once it
lands: (a) shell + files + todo, (b) browser, (c) computer use, (d) voice, (e) cron, (f) MCP +
skills.

**Green per batch**
- Every new tool round-trips for real, and its result lands in the log per `LOOP.md` §4.
- The serialized tool array and system prompt are asserted **unchanged from the previous batch
  except for the added schemas** — no drift in the existing entries.
- One measured cache-read number is recorded for the first turn after the batch: the prefix is
  rewritten exactly once, then cached again (`TOOLS.md` §9 constraint 1).
- Nothing per-turn (skill text, device lists, cron metadata, dates) entered the system prompt or
  the array.

## Per-run verification discipline (every phase)

1. Write the brief to `briefs/<phase>-<n>.md`; it cites the docs, never re-describes them.
2. Run `codex exec … -o reports/<phase>-<n>.md`; capture the report.
3. Read the **diff**, not the report.
4. Run the suite; then, for behaviour changes, stash **only** the source files
   (`git stash push -- <files>`) and confirm the new tests fail against the old code; restore and
   re-run green.
5. Commit per step, with a message that says what was verified.
6. Never push. Never trust "done" without the raw output.
