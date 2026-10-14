# will.I.A. — kickoff (paste this into a fresh session)

You're starting the detailed planning phase for **will.I.A.** — my own endless-chat harness. A standalone program (our own code; no Hermes fork, wrapper, or plugin) where the chat itself is the memory — Taelin's OptChat/UniiChat design — with a memory engine that is already built and tested, coding delegated out to Codex or Hermes, and non-coding tools implemented natively. It runs on my OpenCode Go plan (`OPENCODE_GO_API_KEY` from `~/.hermes/.env`; base `https://opencode.ai/zen/go/v1`; default model `deepseek-v4.1-flash`).

Read these first, in order:
1. `~/Documents/coding/willia/SCOPE.md` — the red-lined scope (invariants, reuse/parked map, phases, open questions).
2. `~/Documents/coding/willia/PLAN.md` — this phase's plan: docs first, then implementation via Codex.
3. `~/Documents/coding/opthermes/CONTRACT.md` — the engine's frozen interfaces (revisions 1–19).
4. `~/.hermes/cache/scratch/optchat-gist/optchat.md` — Taelin's design doc (the recipe).
5. `~/Documents/coding/opthermes/docs/FINDINGS.md` — lessons from the dropped Hermes integration (what NOT to redo).

Skim when relevant: `~/Documents/coding/opthermes/optchat/` (the Reuse modules) and `~/Documents/coding/markdowns/OPTCHAT_HELLO.md` (my personal text, imported later as the first notes).

State: nothing is in flight. `~/Documents/coding/willia/` has SCOPE.md and PLAN.md; it is not yet a git repo (you initialize it in P0). The engine lives at `~/Documents/coding/opthermes` (main, 333 tests green). No pushes anywhere until I say so.

What to do, in order:
1. CHECK state first (`ls ~/Documents/coding/willia`; `git -C ~/Documents/coding/opthermes log --oneline -3`). Trust nothing.
2. Ask me the open questions at the bottom of SCOPE.md (dir/repo name; in-prompt agent name; P1 REPL shape; native v1 tool set) in ONE short round.
3. Produce the doc set listed in PLAN.md — interfaces EXTRACTED from the engine's source, exact shapes, no paraphrasing. Brief replies; I red-line each doc.
4. When I say go, implement in phases P0→P3, delegating the code to Codex:
   - default: `codex exec -m gpt-5.6-sol -c model_reasoning_effort="high" --approve-for-me --skip-git-repo-check -C ~/Documents/coding/willia -o <report>.md "$(cat <brief>.md)"` — sol @ high for most tasks; (Corrected 2026-10-13: the kickoff wrote `-m gpt-6-sol`, which does not exist and 400s instantly, and omitted `--skip-git-repo-check`, which `codex exec` needs outside a git repository. The live resume point is `docs/HANDOFF.md`.)
   - exceptions (tricky or precision-critical): the same command with `-m gpt-6-astra` @ high.
   - Write each brief to a file first; verify every run yourself (read the diff, run the tests, prove red-first when behavior changes) BEFORE committing; commit per step; never trust the delegate's summary.

Rules I hold you to: brief replies; correct my English inline at the top of every reply (standing habit — resumes); options over monologues; I stay in the loop; commit after verification, never before; push only when I say; cost-conscious — sol by default, astra only where precision pays.
