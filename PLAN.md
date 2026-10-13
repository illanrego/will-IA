# will.I.A. — Build plan (docs first, then Codex implementation)

**Goal:** from the red-lined SCOPE.md to a running will.I.A., with every build delegated to Codex
and verified here before it counts.

**Sequencing:** one brief per Codex run, disjoint file sets, verification between runs. Codex writes
code; the session writes the briefs, reviews the diffs, runs the tests, commits.

## Stage A — detailed planning & doccing (no code)

1. Close the open questions (SCOPE.md bottom) in one short round with the user.
2. Produce the doc set, in `~/Documents/coding/willia/docs/`, English, each doc red-lined by the user:
   - `README.md` — non-negotiables, repo map, what exists vs what does not, reading order.
   - `ENGINE.md` — the memory engine map: every Reuse module + its exact interface (read from
     source, not paraphrased), the invariants it holds, and the test map.
   - `WIRE-FORMATS.md` — every shape crossing a boundary, exact: OpenCode Go chat-completions
     request/response (streaming, tool calls, usage fields), the view `<chat>` format, the
     compaction envelope `[system][view][task]`, the log record `{id,kind,text,size,date}`.
   - `LOOP.md` — the turn loop + compaction pump spec (recipe §6 + §2–4): settle rule,
     render-before-log, background drain (≤8 concurrent), failure handling, delegate backgrounding.
   - `TOOLS.md` — exact JSON schemas + behaviors: `zoom`, `date`, `delegate_codex`,
     `delegate_hermes`, `web_search`, `web_extract`, `vision`; where each result lands in the log.
   - `DELEGATES.md` — subprocess contracts: exact commands (incl. the `codex exec` form), working
     dirs, report capture, background/report mechanics, the `work`-record shape.
   - `ENV.md` — env matrix: `OPENCODE_GO_API_KEY` (+ source file), `OPENROUTER_API_KEY` for
     vision, data path (`~/.willia` or decided), budgets (view 64–128 KB, compaction views 16–32 KB).
   - `PHASES.md` — P0–P3 with per-phase acceptance checks (what green means, what to measure).
3. Freeze: after red-lines, the docs are the build contract. Briefs cite the doc, never re-describe it.

## Stage B — implementation (Codex runs; session verifies; user gates)

- **P0 — repo setup.** `git init` in `~/Documents/coding/willia`; vendor the Reuse modules from
  `~/Documents/coding/opthermes/optchat` (byte-identical where possible: store, tree, view,
  compactor, prompts, summarizer envelope, text, notes, tools, cache, persistence, media) + their
  applicable tests; leave `engine.py` / `turn_view.py` / `shim.py` behind; README. Green = the
  vendored test subset passes.
- **P1 — core chat.** Model client (OpenCode Go), turn loop, compaction wiring, REPL v1, config,
  `willia` launcher. Green = a real conversation: log/tree/view correct; compactions build;
  envelope intact; usage visible.
- **P2 — tools.** `zoom`/`date` exposed; `delegate_codex` + `delegate_hermes` (background →
  `work` records; report on the next turn); web + vision native. Green = one real delegated coding
  task end-to-end + web/vision round-trips.
- **P3 — bootstrap & ride.** Import `OPTCHAT_HELLO.md` as `note` records; first real rides; fix
  what the rides surface; then (optionally) browse/usage polish.

## Verification discipline (per run)

- Brief → `codex exec` (sol high by default; astra high for tricky/precision) → read the DIFF →
  run the suite → when behavior changed, prove red-first (revert source only, keep new tests,
  expect failures) → commit per step → never trust the delegate's summary → no pushes until told.

## References

- `SCOPE.md` (invariants, reuse/parked map) — repo root.
- Engine: `~/Documents/coding/opthermes` (CONTRACT.md, docs/FINDINGS.md, optchat/).
- Recipe (the spec): `docs/optchat-gist.md` in this repo — Taelin's design doc, byte-identical to
  the upstream gist (`gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449`), vendored so
  the contract does not depend on a prunable cache.
- Personal text for notes import: `~/Documents/coding/markdowns/OPTCHAT_HELLO.md`.
- UX reference, not code: github.com/jonaslsaa/pi-optchat.

## Open questions (settle in Stage A)

1. Dir/repo name (`willia` on disk? GitHub name later).
2. In-prompt agent name (rename "Unii" → "Will" / "will.I.A."?).
3. P1 REPL shape (plain first recommended).
4. Native v1 tool set (web + vision enough?).
