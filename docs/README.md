# will.I.A. — doc set (the build contract)

Stage A of `PLAN.md`. These docs are the contract: briefs cite a doc, they never re-describe it.
Interfaces and shapes here are **extracted from the engine's source** at
`~/Documents/coding/opthermes` (main, tip `fc0b13e`, 333 tests green), not paraphrased.

**Status:** all docs are drafts for red-line. No code until the red-lines are in.

## Reading order

1. `README.md` — this file: non-negotiables, repo map, what exists vs what does not.
2. `ENGINE.md` — the memory engine: every vendored module, its exact interface, its invariants.
3. `WIRE-FORMATS.md` — every shape crossing a boundary (OpenCode Go, the view, the envelope, the log).
4. `LOOP.md` — the turn loop and the compaction pump.
5. `TOOLS.md` — the tool set, exact JSON schemas and where each result lands.
6. `DELEGATES.md` — the Codex/Hermes subprocess contracts and the `work` record.
7. `ENV.md` — env matrix, paths, budgets.
8. `PHASES.md` — P0–P5 with per-phase acceptance checks.
9. `TUI.md` — the modal terminal interface: layout, modes, keys, slices.

**`optchat-gist.md` is not one of those nine:** it is the spec itself, vendored here so the
contract's source of truth does not live in a prunable cache. Taelin's design doc, byte-identical
at vendoring time (`sha256 12f300f7…`, 19,092 bytes), upstream
`gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449`. Every "recipe §N" citation in this
doc set refers to its headings. When the upstream gist moves, the vendored copy is refreshed in a
commit of its own — never edited in place.

## Non-negotiables

- **Our own thing.** No Hermes fork, wrapper, plugin, or shared code with any host. Codex and
  Hermes are reached only as external subprocesses, the way any program calls `git`. A broken
  delegate is swapped, not absorbed.
- **One canon: Taelin's design** (`docs/optchat-gist.md`). Our docs are its reading, the vendored
  code is an implementation we may re-derive, and the previous project's records are history —
  `ENGINE.md` §0.
- **The memory is the design.** One append-only log; a binary summary tree; a constant-size view
  (64–128 KB sawtooth); zoom/date navigation; compactions shaped like turns so they read the
  turns' cache prefix. `SCOPE.md` holds the invariants; `ENGINE.md` shows which module enforces each.
- **OpenCode Go is the only route, for every call.** `OPENCODE_GO_API_KEY` from `~/.hermes/.env`,
  base `https://opencode.ai/zen/go/v1`, default model `deepseek-v4.1-flash`. Turns, compactions and
  `vision` all go through it: the vision call is an ordinary multimodal **user** message on the same
  route, with the chat's own model, measured 2026-10-13. **One credential, and zero new ones.**
- **Not for coding.** Coding delegates out (`delegate_codex` primary, `delegate_hermes` secondary).
- **Native tools are the non-coding rest:** `web_search`, `web_extract`, `vision` for v1.
- **One endless chat, single profile.** No profiles, no threads, no session list.
- **Hermes is never retired.** will.I.A. is a companion; Hermes stays the daily driver.
- **No Hermes inheritance.** Anything that existed only for Hermes' engine host is deleted or
  replaced (`ENGINE.md` §8). Tool *parity* is a goal (P4, `TOOLS.md` §9); importing Hermes code is
  not a method.

## Repo map

```
SCOPE.md            red-lined scope (invariants, reuse/parked map, phases, open questions)
PLAN.md             this phase's plan (docs first, then Codex implementation)
HANDOFF.md          the kickoff prompt (historical; the live state is in the docs and git log)
docs/               THIS DOC SET - the build contract
willia/             the program package (P0 creates it; the engine's `optchat/`, renamed - ENGINE.md §6)
tests/              pytest suite (vendored subset + new tests)
briefs/             one .md brief per Codex run (P0+)
reports/            one -o report per Codex run (P0+)
```

Package name: **`willia/`** (the engine's `optchat/`, renamed — the exact surface is `ENGINE.md`
§6). The name is load-bearing: `SCOPE.md`'s "our own thing" rule means no `optchat`/`OptChat`
string survives anywhere in the program, warnings included.

## What exists vs what does not

| Piece | State |
|---|---|
| Memory engine (store, tree, view, compactor, prompts, text, notes, tools, media, persistence, cache) | **built and tested** in `~/Documents/coding/opthermes`; vendored in P0 |
| Engine's Hermes adapter (`engine.py`, `turn_view.py`, `shim.py`) | **parked** — never vendored |
| Model client (OpenCode Go, streaming, tool calls) | not written |
| Turn loop, compaction pump wiring | not written |
| REPL, config, `willia` launcher | not written |
| Native tools (web/vision), delegates | not written |
| Notes import, first rides, usage meter | not written (P3) |
| Hermes-parity tools (browser, computer use, voice) | not written (P4, `TOOLS.md` §9) — shell, files, MCP, skills and todo have landed; cron was dropped on 2026-10-14 (the Hermes gateway covers it) |

## Standing rules for every brief and every commit

- Brief → `codex exec` (sol @ high default; astra @ high for tricky/precision) → read the diff →
  run the suite → prove red-first when behavior changed → commit per step. Never trust a
  delegate's summary. No pushes until the user says.
- Vendored files are copied **with exactly the `ENGINE.md` §6 rename list and the §8 verdicts
  applied, and no other edit**; any further deviation is listed in `ENGINE.md` §5 with its reason,
  and each file's header records its origin (`opthermes` commit `fc0b13e`).
- Behavior changes need a test that fails against the old code first.
