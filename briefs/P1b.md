# P1b — the turn loop, the REPL and the launcher

**Repo:** `~/Documents/coding/willia`. Read `docs/README.md` first, then `docs/LOOP.md` §1–§5 and §7–§9
(this brief implements them), `docs/ENV.md` §2/§4/§6 (paths, the prompt, the launcher), `docs/TOOLS.md`
§2/§8 (zoom/date payloads, where results land), and `docs/WIRE-FORMATS.md` §2–§4.

**Do not edit anything under `docs/`**, `SCOPE.md`, `PLAN.md`, `briefs/`, `reports/`, or the frozen
memory modules (`store.py`, `tree.py`, `view.py`, `compactor.py`, `media.py`, `notes.py`, `text.py`,
`tools.py`, `persistence.py`, `toolkit.py`, `prompts.py`).

**NO GIT COMMANDS.** No `git add`, `commit`, `stash`, `checkout`, `reset`, `restore` — nothing. The
session commits; a delegate that commits makes the verification meaningless.
**No new dependencies** (stdlib only, plus what is already imported).

**Proof to report verbatim:**

```
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

139 passed before this run; it must be green after, with the new tests. **Every test must run
offline** — no network, no real Codex, no subprocess.

---

## 0. Four fixes to `willia/client.py` (found by review of P1a)

1. **`HTTP-Referer`** must default to `https://github.com/illanrego/will-IA` and be configurable: add
   `model.referer` to `willia/config.py` (default that URL, a `str`) and read it in `_headers()`.
   `X-Title` stays `will.I.A.`.
2. **Omit `reasoning_effort` when it is `None`** instead of sending `"reasoning_effort": null`.
   (The config default is `"medium"`, so this is a guard for an explicit null.)
3. **`Client.last_usage: dict`** — set after every call (`turn` and `summarize`) so the P3 meter and
   `/status` can read the most recent usage without the client returning it.
4. **Streaming must be incremental.** `_send` currently materialises the whole stream before parsing,
   so nothing can be displayed as it arrives. Parse the SSE line by line and call an optional
   callback: `turn(messages, tools, *, on_delta: Callable[[str, str], None] | None = None)` where
   `on_delta(kind, text)` is called with `kind` in `{"content", "reasoning"}` per delta. Keep the
   existing `Reply` return value and every existing test passing.

## 1. `willia/records.py` — the classification table (`docs/LOOP.md` §4, exact)

```python
def classify(msg: dict, node_bytes: int, tool_name: str | None = None) -> list[tuple[str, str]]
def clip_tool_output(text: str, limit: int = 30_000) -> str
def delegate_name(payload_text: str) -> str        # "subagent" when nothing usable is found
```

Exact rules (extracted from the engine's parked `_records`, which stays parked):

| Input | Records |
|---|---|
| `role: user` | one `("user", chunk)` per `text.split_for_kind(content, node_bytes, "user")` chunk |
| `role: assistant`, plain content | one `("will", chunk)` per `split_for_kind(content, node_bytes, "will")`; **empty content → no record at all** (thoughts are never logged) |
| `role: assistant` with `tool_calls` | one `("tool", json)` per call: compact JSON, `ensure_ascii=False`, `separators=(",",":")`, keys `name`, `arguments` (parsed when the raw string is valid JSON, else the raw string), plus `content` **only when the assistant message also carried text** |
| `role: tool` | `clip_tool_output(text)`; if `tool_name` is a delegate (`delegate_codex`, `delegate_hermes`) → one `("work", f"[{name}] {text}")`; else one `("echo", text)` |
| anything else | nothing |

`content` extraction: a `str` is itself; a list joins the `text` parts that are not media parts with
`"\n"` (mirror the engine's `_content_text`, including its media-part exclusion); `None` → `""`.
`clip_tool_output`: `text[:15_000] + text[-15_000:]` when `len(text) > limit`, unchanged otherwise.
`delegate_name`: parse the payload as JSON; the first non-empty `str` among `name`, `agent`, `task`
wins; otherwise `"subagent"`.

## 2. `willia/dispatch.py` — the tool dispatcher (`docs/TOOLS.md` §2, §8)

```python
def dispatch(name: str, arguments: object, *, log, tree, view, root, node_bytes: int) -> str
```
- Always returns a **JSON string**; never raises for a tool-level problem.
- `zoom`: validate `scope` first (a non-empty string, or absent), then
  - a string `id` with a `scope` → `{"error": "a string id opens its own chat; do not pass scope with it"}`;
  - a `scope` → resolve `<root>/agents/<scope>/` (a single safe path component, and the directory must
    hold a `view.json`); errors `{"error": "unknown scope: '<name>'"}` / `{"error": "scope '<name>' has no chat"}`;
    then `tools.zoom(child_log, child_tree, None, id, n, scope=scope)`;
  - otherwise `tools.zoom(log, tree, view, id, n, master_root=root)`.
  The child's log opens **read-only** (`Log(child_root, read_only=True)`, `Tree(child_root, read_only=True)`).
- `date`: the `scope` path likewise, else `tools.date(log, id)`.
- The five not-yet-implemented tools (`delegate_codex`, `delegate_hermes`, `web_search`, `web_extract`,
  `vision`) → `{"error": "not implemented yet: <name>"}`. They stay in the array (the cache anchor);
  their implementations arrive in P2.
- An unknown name → `{"error": "unknown tool: <name>"}`.

## 3. `willia/chat.py` — the state and the turn

**Startup** (`Chat.open(config, *, client=None) -> Chat`):
- Ensure the directories of `docs/ENV.md` §2 exist; copy `prompts.default_instructions()` to
  `<root>/prompt.md` **if that file is absent**; read it and compose
  `system = prompts.build_system_prompt(text)`; `tools = toolkit.schemas()`.
- `Log(root)` — a locked root raises a clear message and a nonzero exit (the caller prints it).
- `Tree(root, node_bytes)`; `View(tree, view_min, view_max, records=log.count())` — a
  `ViewStateUnavailable` must stop startup with the message `docs/LOOP.md` §5 prescribes (say that
  `willia --restore-view` exists and that nothing was written).
- **Startup reconciliation** (`docs/LOOP.md` §5), never a rebuild: add the missing roots from
  `view._end()` to `log.count() - 1`, and re-seed every record `i` whose `node(0, i)` is missing
  (`compactor.seed(record.i, record.text, record.kind)`); if anything changed, `merge_batch`, save,
  then a bounded `run_pending`.
- `Compactor(tree, self._summarize, node_bytes, view=view)` with `compactor.system = system` and
  `compactor.tools = tools` set **before** any pass.
- `session_id(root)`; `Client(config, session)` unless one was injected (tests inject a fake).
- Open `~/.willia/logs/willia.log` (append) and write one startup line.

**`Chat.turn(texts: list[str]) -> None`** — `docs/LOOP.md` §1, in this order:
1. `compactor.settle(max_nodes=64, timeout_s=20.0, model_calls=False)`.
2. `view_text = view.render()` — **before** logging anything.
3. For each text (and each chunk of it): `log.append("user", chunk)` → `compactor.seed(i, chunk, "user")`
   → `view.add_root(i)`; keep the chunk list for the request.
4. `request = [{"role": "system", "content": system}, {"role": "assistant", "content": view_text}]`
   then one `{"role": "user"}` per chunk, in order.
5. Loop: `reply = client.turn(request, tools, on_delta=...)`; log the reply's records through
   `records.classify`; append the assistant message to `request` (with `content: ""` — never `null` —
   when it carried only tool calls, and `tool_calls` as `{"id", "type": "function", "function":
   {"name", "arguments": <the raw string the model sent>}}`); if there are no tool calls, break;
   otherwise for each call `dispatch(...)`, log the result, and append
   `{"role": "tool", "tool_call_id": call.id, "content": result}`.
6. **Drain the inbox** between rounds (`docs/LOOP.md` §1): each queued message is logged and appended
   to `request` as a user message before the next API call. In P1b the queue is the REPL's; a
   `Chat.turn` call with no queue behaves as if it were empty.
7. **`view_text` never changes during the turn** — assert it in a test.
8. `end_turn()`: `tree.save()`, `view.save()`, copy `<root>/view.json` to `<root>/backups/view.json`,
   then a bounded `compactor.run_pending(limit=config.compact_concurrency)` and save again if it built
   anything. In P1b the pump is **synchronous and bounded** (no thread — the drain thread, the lock
   discipline, the watchdog and `--restore-view` are P1c). Print one line per turn with
   `prompt_tokens`, `cached_tokens` and `reasoning_tokens` from `client.last_usage`.

`Chat.status() -> list[str]`: the root, the session's first 8 chars, the record count, the view bytes,
the unbuilt node count, the number of children under `agents/`, and the last usage.

## 4. `willia/repl.py` and `willia/cli.py`

- `repl.run(chat)`: a small reader thread reads stdin lines into a `queue.Queue`; the main loop takes
  lines. A line that is a command (`/quit`, `/help`, `/status`) is handled immediately **when the
  buffer is empty**; a line ending in a single `\` continues the buffer; an empty line submits the
  buffer as one message (and an empty buffer does nothing). While a turn is running, the reader keeps
  feeding `chat.inbox` so the loop's step 6 can hand the text to it — the reader must never touch the
  Log, the Tree or the View (it only enqueues).
- Display: the model's text streams to stdout as it arrives (`on_delta`); a tool call prints one line
  (`→ zoom {"id": 40, "n": 8}`); a tool result prints its first line, truncated to 200 characters
  (the whole result is in the log). `/quit` saves, prints the closing line and exits 0.
- `cli.main(argv=None) -> int`: `willia` (continue or create the one chat), `willia --new` (move the
  whole root to `~/.willia-archive/<UTC timestamp>/`, then create a fresh one), `willia --status`
  (print `Chat.status()` and exit), `willia --help`. Unknown flags exit nonzero with a usage line.
  Do **not** add `--restore-view` yet (P1c owns it).
- `pyproject.toml`: add the console script `willia = "willia.cli:main"`.

## 5. Tests (all offline; inject a fake client and a fake summarizer)

`tests/test_records.py` — every row of the table above, including: a media-part list joining only
text parts; empty assistant content → no record; two tool calls → two `tool` records with the exact
compact JSON; a 30,001-character tool result clipped to head+tail; a delegate result becoming a
`work` record with the `[Name]` prefix; a reasoning-only reply logging nothing.

`tests/test_dispatch.py` — the zoom/date payloads and every error string in §2; the scope rules
(a string id with a scope; an unsafe scope; a scope with no chat); the five unimplemented names; an
unknown name.

`tests/test_chat.py` — with a fake client scripted per round:
- the first request's view message has **no line for the message being sent** (render-before-log);
- the view text is byte-identical across a turn's rounds, and the assistant message carries
  `content: ""` on a tool-only round;
- the tool message carries the right `tool_call_id`, and the next request contains it;
- a long paste becomes several `user` records and several user messages;
- the inbox: a message queued between rounds is logged and appears in the next request, in order;
- startup on a fresh root: `prompt.md` seeded, `view.json` written, no journal left over;
- startup with the log ahead of the view: the missing roots are added and view coverage reaches
  `log.count()`; startup with the view behind by more than one day file still reconciles;
- a missing `view.json` on a chat with records: `Chat.open` raises and writes nothing;
- `backups/view.json` exists after `end_turn` and parses as the same shape as `view.json`.

`tests/test_cli.py` — `--status` on a fresh root prints the documented fields; `--new` archives the
root and leaves an empty chat behind (assert the archive directory exists and the new root has no
records); `--help` exits 0; an unknown flag exits nonzero.

Extend `tests/test_client.py` for §0: the new `HTTP-Referer` default and its override, the omitted
`reasoning_effort` when `None`, `last_usage` after a turn and after a summarize, and `on_delta`
receiving the content deltas in order.

## 6. Constraints

- Touch only: `willia/client.py`, `willia/config.py`, `willia/records.py` (new), `willia/dispatch.py`
  (new), `willia/chat.py` (new), `willia/repl.py` (new), `willia/cli.py` (new), `willia/__init__.py`,
  `pyproject.toml`, and the test files named above. **Nothing else.**
- The turn must never block on a model call for a compaction in P1b (the bounded `run_pending` at
  `end_turn` is the whole pump for now).
- No date, session id, model name or per-turn state may enter the system prompt or the tool array
  (`docs/LOOP.md` §9.10) — print them, never send them there.
- English everywhere; docstrings in the vendored files' register (what the module owns, then why).
