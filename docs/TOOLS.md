# TOOLS.md — the tool set

The tool array is **fixed**: the same schemas, in the same order, are sent on every turn and every
compaction, so they are a stable cache prefix (`WIRE-FORMATS` §3). Nothing in the array varies with
state. A test must read the tool names from the registry and assert each appears in the system
prompt's text (the host build once shipped `zoom`/`date` in the prompt while the registered names
were `optchat_*`, and navigation was impossible — `ENGINE.md` §6).

v1 array, in this order: `zoom`, `date`, `delegate_codex`, `delegate_hermes`, `web_search`,
`web_extract`, `vision`.

## 1. Renames and result rules

- Registered names: `zoom` / `date` (the recipe's names; the vendor's `optchat_` prefix is gone with
  the rest of the host-era naming — `ENGINE.md` §6).
- Every tool result is a **JSON string** sent as a `role: "tool"` message. Images never travel in
  tool messages (the Go relay rejects list-type tool content — `WIRE-FORMATS` §1).
- A tool never raises into the loop: a failure is `{"error": "<reason>"}`.
- Anything over 30,000 characters is clipped head+tail before it is logged (`LOOP.md` §4).

## 2. `zoom` — navigation (handler: vendored `tools.zoom`, byte-identical)

```json
{"type": "function", "function": {
  "name": "zoom",
  "description": "Open a child chat by name, a chat span, or a raw message. Without scope, an integer id resolves against the chat whose view you are reading; a returned child chat names the scope its ids resolve with.",
  "parameters": {"type": "object", "properties": {
    "id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    "n": {"type": "integer"},
    "scope": {"type": "string", "description": "A subagent's name: resolve the id against that child's chat instead of the chat whose view you are reading."}},
   "required": ["id"]}}}
```

Payloads (exact, from `tools.zoom`):

| Call | Result |
|---|---|
| `id` a string (a child name) | `{"name": <name>, "scope": <name>, "chat": "<chat>\n…</chat>"}` — the child's whole view |
| `n == 1` | `{"id": <id>, "n": 1, "kind": <kind>, "scope": <scope or null>, "text": <whole message>, "media": [...]}` |
| `n` a power of two > 1 | `{"id": <id>, "n": <n>, "scope": …, "halves": [{"id": …, "n": n/2, "text": …}, {"id": …, "n": n/2, "text": …}]}` |

Errors, verbatim: `"id must be a string or nonnegative integer; n must be a positive integer"` ·
`"n must be a power of two"` · `"id must be a multiple of n"` · `"message does not exist"` ·
`"span does not exist"` (the span runs past the log) · `"span is not summarized yet"` (a child or
the parent is unbuilt) · `"unknown subagent name"` · `"subagent chat does not exist"`.

Harness-level rules (from `engine.handle_tool_call`, minus the host):

- `scope` absent → the chat whose view the caller is reading (the master's own chat).
- `scope` present → resolve `<root>/agents/<name>/` directly (our rule, `ENGINE.md` §8.4): the name
  must be a single safe path component and the directory must hold a `view.json`. Errors:
  `"unknown scope: '<name>'"`, `"scope '<name>' has no chat"`, `"scope '<name>' cannot be read: <exc>"`.
  Navigation never falls back to another namespace.
- A string `id` **is** its own scope: passing `scope` with it is
  `"a string id opens its own chat; do not pass scope with it"`.
- `scope` must be a nonempty string: `"scope must be a nonempty subagent name"`.
- **No media envelope exists in willia.** The host's `_multimodal` tool-result shape was deleted with
  §8.5, and the Go relay rejects list-type tool content anyway. Every result is a JSON string;
  images reach the model only through the `vision` tool, which answers in text.
- The model is told `zoom` is its **only** mechanism to navigate the tree — never grep, never a
  search over the log — and to zoom until a thing is whole *before* it acts, guesses or asks.

## 3. `date` — one message's timestamp (handler: vendored `tools.date`)

```json
{"type": "function", "function": {
  "name": "date",
  "description": "Get the stored ISO timestamp of a raw message, from the chat whose view you are reading or from the subagent's chat named by scope.",
  "parameters": {"type": "object", "properties": {
    "id": {"type": "integer"},
    "scope": {"type": "string", "description": "A subagent's name: read the id from that child's chat instead of the chat whose view you are reading."}},
   "required": ["id"]}}}
```

Result: `{"id": <id>, "date": "<ISO-8601 UTC>", "scope": <scope or null>}`.
Errors: `"id must be a nonnegative integer"`, `"message does not exist"`.

## 4. `delegate_codex` / `delegate_hermes` — coding out (see `DELEGATES.md`)

Schemas (new, exact):

```json
{"type": "function", "function": {
  "name": "delegate_codex",
  "description": "Spawn a Codex coding agent on a task, in the background, and get its report later as a work message. Use for code, tests, builds, refactors. It has its own shell and works in the given directory.",
  "parameters": {"type": "object", "properties": {
    "task": {"type": "string", "description": "The full brief: what to do, where, and how to prove it."},
    "dir": {"type": "string", "description": "Absolute working directory (defaults to the configured workspace)."},
    "model": {"type": "string", "enum": ["gpt-6-sol", "gpt-6-astra"],
              "description": "sol for most tasks; astra only where precision matters more than cost."},
    "name": {"type": "string", "description": "Short label for this child, used by zoom(\"Name\") and in the report's [Name] tag."}},
   "required": ["task"]}}}
```

`delegate_hermes` has the same schema minus `model`/`dir` (it runs in the user's default Hermes
profile with its own model and its own workspace).

Behaviour: the call returns immediately with
`{"status": "started", "name": "<name>", "agent": "codex|hermes", "report_path": "<abs path>"}`.
The report lands later as a `work` record. **The master never waits or polls.**

## 5. `web_search` — native

```json
{"type": "function", "function": {
  "name": "web_search",
  "description": "Search the web. Returns titles, URLs and snippets.",
  "parameters": {"type": "object", "properties": {
    "query": {"type": "string"},
    "limit": {"type": "integer", "description": "Results to return (default 5, max 10)."}},
   "required": ["query"]}}}
```

Result: `{"results": [{"title": "...", "url": "...", "description": "..."}, ...]}`.
Implementation: the `ddgs` package (no key, nothing to configure), the same backend the host uses
by default. Logged as one `echo` record (clipped if long).

## 6. `web_extract` — native

```json
{"type": "function", "function": {
  "name": "web_extract",
  "description": "Fetch pages and return their text, one entry per URL.",
  "parameters": {"type": "object", "properties": {
    "urls": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    "char_limit": {"type": "integer", "description": "Per-page character budget (default 15000)."}},
   "required": ["urls"]}}}
```

Result: `{"results": [{"url": "...", "title": "...", "content": "...", "error": null}, ...]}` —
one entry per requested URL, in order, `error` set instead of `content` on failure. HTML is reduced
to text/markdown. A page over `char_limit` is head+tail truncated and says so in the content.
Logged as one `echo`.

## 7. `vision` — native (OpenRouter, not the Go relay)

```json
{"type": "function", "function": {
  "name": "vision",
  "description": "Look at an image (a local path or an http(s) URL) and answer a question about it.",
  "parameters": {"type": "object", "properties": {
    "image_url": {"type": "string", "description": "A local file path or an http(s) URL."},
    "question": {"type": "string"}},
   "required": ["image_url", "question"]}}}
```

Result: `{"answer": "<text>", "source": "<the path or URL>"}`. Never an image part: the answer is
text, so nothing image-shaped ever enters a tool message on the Go route.
Credential: `OPENROUTER_API_KEY` (the only thing willia reads it for)
`[VERIFY in P2: the exact vision model id and whether it is a config field]`.
A local file is archived through `media.archive_media` (so the chat's own record of it survives even
if the file moves); a remote URL is passed to the model and recorded as a reference
(`retry_pending_media` keeps remote URLs untouched by design).
Logged as one `echo` — and the answer's key fact belongs in the model's *reply*, because summaries
keep little of tool output (the recipe's line that does the most work).

## 8. Where each tool's result lands

| Tool | Log kind | Notes |
|---|---|---|
| `zoom` | `echo` | whole, clipped only past 30,000 (a `n=1` message can be long) |
| `date` | `echo` | tiny |
| `delegate_codex` / `delegate_hermes` (the call) | `tool` | the brief is in the arguments |
| a delegate's eventual report | `work` | `"[Name] <report>"`, clipped head+tail |
| `web_search` / `web_extract` | `echo` | clipped head+tail |
| `vision` | `echo` | the answer text |
| an unknown tool name | `echo` | `{"error": "unknown tool: <name>"}` — never silently dropped |

## 9. Later: the Hermes-parity tools (P4 — deliberately not v1)

The v1 array is small because it must be. The tools you actually use daily on Hermes come back as
**native implementations in willia** — never as Hermes imports — in this order of value:

| Group | Tools | Notes |
|---|---|---|
| shell + files | `terminal`, `read_file`, `write_file`, `patch`, `search_files` | workspace-scoped; the recipe's "do the user's tasks yourself, with your tools" assumes exactly this. |
| planning | `todo` | per-turn state goes **after** the view. |
| browse | `browser` (local playwright) | the site-check and posting-automation workflows. |
| computer use | `computer_use` (desktop driving) | the heavy one; in Hermes it is a driver process. Keep it in the delegate lane until it earns its place in the array. |
| voice | `tts` (Edge `en-US-GuyNeural`), voice notes in | |
| time | `cron` (recurring turns) | an **extension**: the design has no clock trigger. A cron fires a turn; its metadata goes after the view, never in the prompt. |
| ecosystem | `mcp` client, `skills` (markdown procedures) | so the existing servers and skills keep working. Skill text is per-turn → after the view. |

Two constraints on every addition:

1. **The tool array is a cache anchor.** Adding or editing a schema invalidates the shared prefix
   once (recipe §3.3: tools and system prompt never change). So tools land in **batches**, and after
   each batch the schemas are frozen — which is why v1's array is chosen now instead of grown.
2. **Nothing per-turn may enter the array or the system prompt.** Skill text, device lists, cron
   metadata, dates: all of it goes **after** the view (recipe §6, §7.10). Tool results stay JSON
   strings and never carry list-type content (the Go relay — `WIRE-FORMATS` §1).
