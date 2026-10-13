# ENV.md — environment, paths, budgets, config

## 1. Environment matrix

| Variable | Used for | Source | Notes |
|---|---|---|---|
| `OPENCODE_GO_API_KEY` | every chat call and every compaction | read from `~/.hermes/.env` at startup | the only credential the chat route needs; never copied into the repo or into `~/.willia` |
| `OPENROUTER_API_KEY` | the `vision` tool only | read from `~/.hermes/.env` | vision is a separate out-of-band call returning text (`TOOLS.md` §7) |
| `WILLIA_HOME` | overrides the data root | the environment | optional; default below |
| `WILLIA_CONFIG` | overrides the config file path | the environment | optional |

- `.env` parsing is willia's own small reader: `KEY=VALUE` lines, `#` comments, no shell
  evaluation, no `export` handling needed. A missing file or key is a **startup error naming the
  key**, not a silent default.
- The `HOME` in this environment is `/home/illan`; `~/.hermes/.env` is the canonical location.
- willia reads **no** `HERMES_*` variable and imports nothing from Hermes. The paint is deliberately
  not shared.
- The attribution headers used on the Go route are willia's own
  (`HTTP-Referer`/`X-Title`/`User-Agent`, `WIRE-FORMATS` §1) — values, not secrets.

## 2. Paths

```
~/.willia/                      the one chat (the DEFAULT: WILLIA_HOME)
  main/YYYY-MM-DD.jsonl         the log (store.Log)
  tree/YYYY-MM-DD.jsonl         the summary nodes (tree.Tree)
  view.json                     the view + compaction views (View.save)
  assets/                       archived media (media.archive_media)
    index.json                  message id -> archive entries
    pending.json                failed media parts, for retry
  agents/
    <label>/                    a delegate's own chat: main/, tree/, view.json (DELEGATES.md §5)
  jobs/<label>-<ts>/            delegate working dirs: brief.md, report.md, run.log
  backups/view.json             the last good view publication (recovery, LOOP.md §5)
  session.json                  the chat's x-opencode-session value (written once, never regenerated)
  logs/willia.log               the harness's own log (the engine warns go here too)
  config.json                   the config below
  prompt.md                     the fixed system prompt (see §4)
  lock                          the writer's flock (store.Log)
```

- `~/.willia-archive/<timestamp>/` — where `willia --new` moves a finished chat (never deleted).
- Nothing in the repo, nothing in a cache dir, nothing under `~/.hermes`.

## 3. Budgets (UTF-8 bytes, never tokens) — the vendored constants

| Name | Value | Meaning | Where |
|---|---|---|---|
| `node_bytes` | 512 | one summary line | `Tree`, `Compactor`, `View` |
| (free node) | ≤ 512 | a source this small is its own node, no model call | `Tree.free_text` |
| `view_min_bytes` | 64,000 | batch merges down to this | `View` |
| `view_max_bytes` | 128,000 | batch merges trigger above this | `View` |
| `compact_view_min_bytes` | 16,000 | compaction view floor | `View.context_view` |
| `compact_view_max_bytes` | 32,000 | compaction view ceiling | `View.context_view` |
| `tool_clip_chars` | 30,000 | tool output clipped head+tail (15,000 + 15,000) | harness (`LOOP.md` §4) |
| `compact_concurrency` | 8 | max model calls in flight (`COMPACT_CONCURRENCY`) | `Compactor` |
| `compact_max_retries` | 5 | oversize retries; the shortest line wins | `Compactor` |
| `settle_max_nodes` / `settle_timeout_s` | 64 / 20.0 | the turn's bounded wait | harness (`LOOP.md` §2) |

## 4. The system prompt (the cache anchor)

- The prompt is the recipe **§5 block verbatim** — persona ("You are WillIA, an AI agent that works
  for one user in a single chat that never ends…"), the view format, the kinds, the tools, the turns
  section and the compactions section — with `Unii` renamed and the paragraph on computers dropped
  (no device shell here; coding is delegated). **One text, for turns and compactions alike**
  (`ENGINE.md` §5.1).
- The user's own instructions **follow it**: who he is, how his files are organized, how he wants
  work done — the recipe's own sentence. They live in `prompt.md` (data root) and are concatenated
  after the fixed text at startup; nothing else may touch either part.
- Read once per process, never varying per turn. Editing it is allowed and costs exactly one cache
  rebuild.
- No dates, no session id, no model name, no device list, no open-device list — recipe §7.10, §3.3.
- A compaction sends the identical text and, as its user message, the task template alone
  (`WIRE-FORMATS` §4).

## 5. `config.json`

```json
{
  "model": {"provider": "opencode-go",
            "base_url": "https://opencode.ai/zen/go/v1",
            "model": "deepseek-v4.1-flash",
            "turns": {"reasoning_effort": "medium"},
            "compactions": {"thinking_disabled": true, "max_tokens": 700}},
  "view_min_bytes": 64000, "view_max_bytes": 128000, "node_bytes": 512,
  "compact_view_min_bytes": 16000, "compact_view_max_bytes": 32000,
  "compact_enabled": true, "compact_concurrency": 8, "compact_max_retries": 5,
  "tool_clip_chars": 30000,
  "web": {"backend": "ddgs", "max_results": 5, "extract_char_limit": 15000},
  "vision": {"model": null, "max_chars": 4000},
  "delegates": {
    "codex": {"enabled": true, "bin": "$(npm prefix -g)/bin/codex",
              "model": "gpt-5.6-sol", "model_precise": "gpt-6-astra",
              "reasoning_effort": "high", "dir": "~/Documents/coding",
              "timeout_minutes": 30},
    "hermes": {"enabled": true, "bin": "hermes", "timeout_minutes": 30}
  },
  "repl": {"stream": true, "history": true}
}
```

- Keys are additive; an unknown key is a **warning**, not a crash.
- **Reasoning is per call type, measured** (`WIRE-FORMATS` §1): turns carry a pinned
  `reasoning_effort`; compactions run with `thinking: {"type": "disabled"}` and a small `max_tokens`
  — a cap with thinking on returns empty content, and the setting does not partition the prompt
  cache, so the two call types can differ safely.
- `session.json` holds the chat's `x-opencode-session` value (opaque, generated once, **never
  regenerated** — it pins the upstream backend that keeps the prompt cache warm).
- Nothing in config can vary the system prompt or the tool array per turn.

## 6. The launcher

One command: `willia`.

- `willia` — continue the one chat. If `~/.willia` exists it is opened (and the startup
  reconciliation runs, `LOOP.md` §5); if not, an empty chat is created and its `view.json` saved.
- `willia --new` — archive the current root to `~/.willia-archive/<ts>/` and start empty. There is
  no session list, no profiles, no threads: **one endless chat** is the design.
- `willia --restore-view` — adopt `backups/view.json` after validating it (`LOOP.md` §5): the
  covered end must not exceed the log's record count, every pair must have a built node, and the
  missing roots are then added forward. Refuses anything else, loudly.
- `willia --status` — print paths, record count, view bytes, unbuilt nodes, running delegate jobs.
- `willia --help`.
- Implementation: a console entry point in the repo (`willia/…`), installed with `pipx`/`uv tool`
  or exposed by a small `bin/willia` shim — the packaging choice is a P0 detail, the *single
  command* is not. `[P0: pick uv-managed venv + console script]`

## 7. What willia must never read

- No Hermes config, skills, memory, session db, or profile.
- No `state.db`: the usage meter comes from the API's own `usage` object and the Go `/usage`
  endpoint (`WIRE-FORMATS` §9), never from a host artifact.
- The only Hermes artifacts ever touched are the two keys in `~/.hermes/.env` (§1).
