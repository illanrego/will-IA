# P1a — the model client and its configuration

**Repo:** `~/Documents/coding/willia`. Read `docs/README.md` first, then `docs/WIRE-FORMATS.md` §1
(the wire, measured), `docs/ENV.md` §1/§2/§5 (env, paths, config) and `docs/LOOP.md` §7 (timeouts).
The doc set is the contract; this brief cites it rather than restating it. **Do not edit anything
under `docs/`**, `SCOPE.md`, `PLAN.md`, `briefs/`, `reports/`, or the vendored memory modules
(`store.py`, `tree.py`, `view.py`, `compactor.py`, `media.py`, `notes.py`, `text.py`, `tools.py`,
`persistence.py`, `toolkit.py`, `prompts.py` — all frozen).

**No new dependencies:** stdlib only (`urllib.request`, `json`, `uuid`, `threading`, `socket`).

**Proof to report verbatim:**

```
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

111 passed before this run; it must be green after, with the new tests included. **Every test you
write must run offline** — no network in the suite.

---

## 1. `willia/config.py`

- The data root: `$WILLIA_HOME` when set, else `~/.willia`. The config file: `$WILLIA_CONFIG` when
  set, else `<root>/config.json`. Absent file → the documented defaults (`docs/ENV.md` §5), no error.
- A `Config` dataclass with the same field names as the doc's JSON, nested as the doc nests it
  (`model.turns.reasoning_effort`, `model.compactions.thinking_disabled`, `model.compactions.max_tokens`,
  `view_min_bytes`, `view_max_bytes`, `node_bytes`, `compact_view_min_bytes`, `compact_view_max_bytes`,
  `compact_enabled`, `compact_concurrency`, `compact_max_retries`, `tool_clip_chars`, `web.*`,
  `vision.*`, `delegates.*`, `repl.*`), plus the call budgets from `docs/LOOP.md` §7
  (turn timeout 120 s, compaction timeout 60 s) which the doc names but the JSON sample omits —
  add them as `model.turn_timeout_s` / `model.compaction_timeout_s` and note the addition in your report.
  (Do not edit the doc; the report is where you flag it.)
- An unknown key logs a **warning**, never a crash; a wrong type for a known key raises `ValueError`
  naming the key. A nested object may be given partially; missing members take the defaults.
- `Config.load(path=None)` classmethod; keep the parsed dict on the instance as `raw`.
- A paths helper on the same module: `main_dir`, `tree_dir`, `view_file`, `view_backup_file`,
  `session_file`, `assets_dir`, `agents_dir`, `jobs_dir`, `logs_dir`, `prompt_file` — all derived from
  the root (`docs/ENV.md` §2). Creating directories is **not** this module's job.

## 2. `willia/envfile.py`

- A small `.env` reader: `KEY=VALUE` lines, `#` comments, blank lines ignored, surrounding single or
  double quotes stripped, **no shell evaluation** (a `$` or a backtick inside a value stays literal).
- `read_env_file(path) -> dict[str, str]`; the default path is `~/.hermes/.env`, overridable with
  `$WILLIA_ENV_FILE`.
- `require(name, *, path=None) -> str`: returns the value or raises `MissingCredential` naming the
  key and the file it looked in. `opencode_go_key()` and `openrouter_key()` are thin wrappers.
- A key present in the real environment wins over the file (so a shell export can override), and the
  returned value is never logged.

## 3. `willia/session.py`

- `session_id(root) -> str`: read `<root>/session.json` (`{"session": "<value>"}`); if absent,
  generate one (`uuid.uuid4().hex`), write it atomically (`tempfile` in the same directory, `fsync`,
  `os.replace`), and return it. **Never regenerate an existing value** — it pins the upstream backend
  and is the keystone of the prompt cache (`docs/WIRE-FORMATS.md` §1). A malformed file raises rather
  than silently rotating the value.
- Keep it byte-stable: the same value for every call of a chat.

## 4. `willia/client.py` — the transport

- `class Reply` (frozen dataclass): `content: str`, `reasoning: str`, `tool_calls: list[ToolCall]`,
  `usage: dict`, `finish_reason: str | None`.
- `class ToolCall` (frozen dataclass): `id: str`, `name: str`, `arguments: dict | str` (parsed when it
  is valid JSON, the raw string otherwise — exactly as the engine's record classifier expects).
- `class ClientError(Exception)` with the status and a short body excerpt; `class ClientTimeout(ClientError)`.
- **A transport seam so the suite is offline.** The client takes `transport: Callable[[str, dict, dict, float], Iterator[str]]`
  — `(url, headers, payload, timeout)` yielding raw SSE lines — and the default implementation uses
  `urllib.request`. Tests inject a fake.
- `Client(config, session, *, transport=None)`; `Client.turn(messages, tools, *, timeout=None) -> Reply`:
  - body: `{"model", "messages", "tools", "stream": true, "stream_options": {"include_usage": true}}`
    plus the reasoning knobs for **turns** (`reasoning_effort` from config; omit `thinking`).
  - parse SSE: accumulate `delta.content`; **capture** `delta.reasoning_content` into `Reply.reasoning`
    (never logged by the harness, and never echoed back — `docs/WIRE-FORMATS.md` §1); accumulate
    `delta.tool_calls[i]` by index, concatenating `function.arguments` fragments and taking `id`/`name`
    from whichever fragment carries them; read `usage` from the final chunk that has one.
  - headers exactly as `docs/WIRE-FORMATS.md` §1: `Authorization: Bearer <key>`, `Content-Type`,
    `User-Agent: willia/<version>`, `HTTP-Referer`, `X-Title: will.I.A.`, and `x-opencode-session: <session>`.
  - **Assert the invariant in code:** every `messages[].content` this client sends is a `str`. A list
    is a programming error here (the relay rejects list-type tool content) — raise `ValueError` rather
    than sending it.
- `Client.summarize(request: CompactionRequest) -> str` — the compaction call, **non-streaming**:
  - messages: `[{"role":"system","content":request.system}]` (when non-empty), then
    `{"role":"assistant","content":request.context}` (when non-empty), then
    `{"role":"user","content":request.task}`; `tools` = `request.tools or None`.
  - body adds `"thinking": {"type": "disabled"}` and `"max_tokens"` from config (the cap trap:
    `docs/WIRE-FORMATS.md` §1 — never cap with thinking on).
  - returns the **ordinary content only**, flattened with `" ".join(splitlines()).strip()`; an empty
    result or a reasoning-only reply raises `ClientError`. Never read `reasoning`.
- **Retries:** 429, 5xx, and timeouts retry up to 3 attempts with 1 s / 2 s / 4 s backoff; anything
  else raises immediately. A timeout raises `ClientTimeout`. `timeout` comes from config per call type.
- The client is **stateless** beyond config + session: it holds no conversation, no history, no view.
  Nothing may accumulate between calls (`docs/LOOP.md` §1).

## 5. Tests (all offline)

`tests/test_config.py`
- defaults when the file is absent; a partial nested object keeps the other defaults; an unknown key
  warns (check with `caplog`) and does not raise; a wrong type raises naming the key;
  `$WILLIA_HOME` / `$WILLIA_CONFIG` are honoured; the path helper set matches `docs/ENV.md` §2.

`tests/test_envfile.py`
- parsing (comments, blanks, quotes, a literal `$`), a value never containing shell expansion,
  a missing key raising with the key named, and the real environment overriding the file.

`tests/test_session.py`
- generates once and reuses (two calls, one value); a malformed file raises; the write is atomic
  (no `.tmp` left behind).

`tests/test_client.py` — with a fake transport
1. the header set includes `x-opencode-session`, a non-default `User-Agent` and the attribution pair;
2. SSE: content deltas concatenate; a reasoning delta lands in `Reply.reasoning`; two tool calls
   accumulate by index with fragmented `arguments`; `usage` is read from the final chunk and
   `usage["prompt_tokens_details"]["cached_tokens"]` survives into `Reply.usage`;
3. `summarize` returns ordinary content only, and raises when the fake returns reasoning with no
   content;
4. a 500 then a 200 succeeds with one retry; three 500s raise;
5. a `socket.timeout` in the transport raises `ClientTimeout`;
6. the compaction envelope is exactly `[system][assistant][user]` — `system` byte-equal to
   `prompts.build_system_prompt(prompts.default_instructions())`, `user` byte-equal to
   `prompts.COMPACTION_TASK.format(...)` alone (no instructions prefix), `tools` **byte-identical**
   to the turn's `tools`;
7. two successive `turn` calls send byte-identical `tools` and `messages[0]` (the cache anchor);
8. a list-valued `messages[].content` raises `ValueError` instead of being sent.

## Constraints

- Touch only: `willia/config.py`, `willia/envfile.py`, `willia/session.py`, `willia/client.py`
  (all new), `willia/__init__.py` (export the new modules; keep the memory API and `prompts`/`toolkit`
  as they are), and the four new test files. Nothing else.
- English everywhere, no em-dash normalization needed, and keep the module docstrings in the same
  register as the vendored files (a short statement of what the module owns, then why).
- Do not print, log or return the API key anywhere.
