# will.I.A. — Scope (v0.1, for red-line)

**One-liner:** My own endless chat — a standalone program where the chat itself is the memory
(the OptChat/UniiChat design, engine already built and tested), with coding delegated to Codex
or Hermes, and non-coding tools implemented natively.

**Status:** Draft for red-line. No code until approved.

---

## Non-negotiables (settled in conversation)

- **Our own thing.** No Hermes fork, no wrapper, no plugin, no shared code with any host. A
  standalone process. It talks to Codex and Hermes ONLY as external subprocesses (the same way
  any program calls `git`). If a delegate breaks, we swap the target, not the internals.
- **The memory is the design.** One append-only log, binary summary tree, constant-size view
  (64–128 KB sawtooth), zoom/date navigation, compactions shaped like turns (cache-aligned
  envelope — already designed and measured in the optHermes season).
- **OpenCode Go plan.** Chat and compactions authenticate with `OPENCODE_GO_API_KEY` read from
  `~/.hermes/.env`; base URL `https://opencode.ai/zen/go/v1`; default model
  `deepseek-v4.1-flash`. **One credential, zero new ones** - turns, compactions and the v1 native
  `vision` tool all go through this route (settled 2026-10-13, measured: an ordinary multimodal user
  message on the same endpoint, `docs/TOOLS.md` §7).
- **Not for coding.** Coding tasks delegate out: `delegate_codex` (primary) and
  `delegate_hermes` (his default profile; inherits its default model — nothing to override).
- **Native tools = the non-coding rest:** `web_search`, `web_extract`, `vision` for v1
  (grow only when a want is actually missed).
- **One endless chat, single profile** (profiles are a later, maybe-never feature).
- **Hermes is never retired.** will.I.A. is a companion; Hermes stays the daily driver.

## Design invariants (do not violate; these are the recipe's rules)

- System prompt and tool schemas are FIXED: no dates, no state (they anchor the cache).
- Render the view BEFORE logging the new message; the message goes whole after it.
- Nothing carries between turns; the view is the only continuity.
- Compactions reuse the turns' `[system][tools]` prefix and their own `<chat>` view (16–32 KB).
- Never rebuild the view; save/load it. Never edit the log. One writer, flush every write.
- Summaries: ≤512 bytes, ruler-checked, retried; nodes built once.
- Delegates run in the background; reports arrive as `work` records; the master never waits/polls.

## Already built (engine — `~/Documents/coding/opthermes`, 333 tests)

| Module | What it is | Verdict |
|---|---|---|
| `store.py` | append-only log: fsync, lock, records, day files | **Reuse**, minus the host ingestion protocol |
| `tree.py` | binary summary tree, build-once, load/save | **Reuse** |
| `view.py` | sawtooth view, merge order, render, compaction views | **Reuse** |
| `compactor.py` | compaction queue: due formula, 8-way, retries, ruler | **Reuse** |
| `prompts.py` | verbatim design templates | **Rewrite** to the recipe §5 text (rename agent) |
| `summarizer.py` | cache-aligned `[system][view][task]` envelope | **Do not vendor**; the envelope is our client's contract |
| `text.py`, `notes.py`, `tools.py`, `media.py`, `persistence.py` | rules, note import, zoom/date, media, helpers | **Reuse** (`cache.py` dropped: host breakpoint planning) |
| `engine.py`, `turn_view.py`, `shim.py` | Hermes-host integration (~2k lines) | **Parked** — not needed standalone |

> **Amended 2026-10-13:** the Hermes-inherited surface was audited and removed — the ingestion
> checkpoint protocol, the host media envelope, the child index, and breakpoint cache planning. See
> `docs/ENGINE.md` §8. The design (Taelin's recipe) is the spec; tool parity with Hermes returns
> later as native tools (`docs/TOOLS.md` §9, phase P4).
>
> **Canon:** Taelin's design only, vendored at `docs/optchat-gist.md`. This doc set is its reading;
> the engine is our implementation of it and may be re-derived; the previous project's records
> (CONTRACT.md, docs/optchat-spec.md, FINDINGS.md) are history, never authority — `docs/ENGINE.md` §0.

## Left to code (the harness — ~1.5–2k lines, straightforward)

1. **Model client** (~200) — chat-completions + streaming + tool calls on OpenCode Go.
2. **Turn loop** (~300) — the recipe's §6: settle-wait, render-before-log, assemble
   `[system][view][message]`, log everything as it happens, drive the compaction pump.
3. **Compaction wiring** (~200) — bind compactor → client via the existing envelope; background
   drain (≤8 concurrent).
4. **Tools + dispatch** (~500) — zoom/date (port); `delegate_codex`, `delegate_hermes`
   (background spawn → report → `work` record); native `web_search`/`web_extract`/`vision`.
5. **CLI/REPL** (~300) — streaming display, long-paste support, `/quit` + minimal commands.
6. **Config + launcher** (~150) — paths, budgets, delegate settings, one command: `willia`.

## Phases (each = Codex build → my verification → commit; push only when told)

- **P0 — repo setup.** `~/Documents/coding/willia`: vendor the Reuse modules (byte-identical
  where possible) + their applicable tests; leave the Parked modules in the old repo. README.
- **P1 — core chat.** Client + turn loop + compaction pump + REPL + config + launcher.
  Verify: real conversation, log/tree/view correct, compactions build, envelope intact,
  cache behavior sane (`state.db`-style usage visible).
- **P2 — tools.** zoom/date exposed; both delegates (incl. background reports as `work`);
  web + vision native.
- **P3 — bootstrap & polish.** Import `OPTCHAT_HELLO.md` as `note` records; first real rides;
  then whatever the rides ask for (usage meter, browse view, …).

## Open questions for red-line

1. Directory/repo name: `willia` on disk? (GitHub name is yours; nothing is pushed until told.)
2. In-prompt agent name: rename the recipe's "Unii" to "Will" (or "will.I.A.")? Persona is yours.
3. ~~P1 REPL: plain line-based first (recommended), fancy TUI later?~~ **SETTLED 2026-10-14, revised:**
   plain line-based shipped in P1; the **TUI is the next slice, before the remaining P4 parity
   batches**. Reason for the reversal: the REPL renders the model's reasoning and its answer as one
   indistinguishable stream (`chat._on_delta` ignores the stream kind), which is unusable day to day.
   Direction: a cyberpunk AI tool, blue-dominant, closer to the Omarchy home menu than to opencode.
   **All three palettes ship** - blue, green and mixed are switchable in the TUI (his ruling, 2026-10-14),
   and the left panel carries the machine's data including both accounts' usage **and their reset
   countdowns**, which arrive with the percentages and so cost no extra call.
4. Native v1 set: web + vision is enough to start, or anything else already missing?
5. ~~Codex delegation default~~ **SETTLED:** `gpt-5.6-sol` at high effort for most tasks; `gpt-6-astra` at high only for the tricky or precision-critical parts (where a late catch would cost more than the model does). (Corrected 2026-10-13: this line said `gpt-6-sol`, which does not exist and 400s instantly. The account's catalog is `gpt-5.5`, `gpt-5.6-sol`, `gpt-6-astra`; the delegate command is `docs/DELEGATES.md` section 2.)
