# TOOLS.md — the tool set

The tool array is **fixed**: the same schemas, in the same order, are sent on every turn and every
compaction, so they are a stable cache prefix (`WIRE-FORMATS` §3). Nothing in the array varies with
state. A test must read the tool names from the registry and assert each appears in the system
prompt's text (the host build once shipped `zoom`/`date` in the prompt while the registered names
were `optchat_*`, and navigation was impossible — `ENGINE.md` §6).

Current array, in this order: `zoom`, `date`, `delegate_codex`, `delegate_hermes`, `web_search`,
`web_extract`, `vision`, `terminal`, `read_file`, `write_file`, `patch`, `search_files`, `mcp`,
`skills`, `todo`.

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
    "model": {"type": "string", "enum": ["gpt-5.6-sol", "gpt-6-astra"],
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

## 7. `vision` — native (OpenCode Go)

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
Route and credential: the same OpenCode Go `/chat/completions` route, session header, attribution
headers and `OPENCODE_GO_API_KEY` as the chat. It sends an ordinary multimodal **user** message,
whose content is a text part plus an `image_url` part; the relay accepts that shape. The restriction
against list-type content still applies to **tool** messages. The default is the chat's own model;
`VisionConfig.model` is an optional override. The text answer is bounded by
`VisionConfig.max_chars` and says when it was truncated.
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
| `terminal` | `echo` | one bounded result after the process exits or times out |
| `read_file` | `echo` | numbered text from the bounded file head |
| `write_file` | `echo` | path and byte count |
| `patch` | `echo` | path, unified diff and replacement count |
| `search_files` | `echo` | bounded match list |
| `mcp` | `echo` | configured servers and remote tool results; server processes close at turn end |
| `skills` | `echo` | available metadata or one complete `SKILL.md` |
| `todo` | `echo` | the operation result; todo state itself is rebuilt from `todo` records |
| an unknown tool name | `echo` | `{"error": "unknown tool: <name>"}` — never silently dropped |

## 9. Hermes-parity tools (P4; shell + files landed)

The v1 array was small because it had to be. The tools you actually use daily on Hermes return as
**native implementations in willia** — never as Hermes imports — in this order of value:

| Group | Tools | Notes |
|---|---|---|
| shell + files | `terminal`, `read_file`, `write_file`, `patch`, `search_files` | **Landed in P4a.** Workspace defaults apply to relative paths and shell execution; absolute paths remain available. |
| planning | `todo` | **Landed.** State is rebuilt from records in the chat log. |
| browse | `browser` (local playwright) | the site-check and posting-automation workflows. |
| computer use | `computer_use` (desktop driving) | the heavy one; in Hermes it is a driver process. Keep it in the delegate lane until it earns its place in the array. |
| voice | `tts` (Edge `en-US-GuyNeural`), voice notes in | |
| ecosystem | `mcp` client, `skills` (markdown procedures) | **Landed.** Server schemas stay behind the one fixed `mcp` tool; skill text is returned only by calls. |

Two constraints on every addition:

1. **The tool array is a cache anchor.** Adding or editing a schema invalidates the shared prefix
   once (recipe §3.3: tools and system prompt never change). So tools land in **batches**, and after
   each batch the schemas are frozen — which is why v1's array is chosen now instead of grown.
2. **Nothing per-turn may enter the array or the system prompt.** Skill text, device lists and
   dates all go **after** the view (recipe §6, §7.10). Tool results stay JSON
   strings and never carry list-type content (the Go relay — `WIRE-FORMATS` §1).

### 9.1 P4a — shell + files

All five results are JSON strings. Their successful shapes are fixed:

| Tool | Result |
|---|---|
| `terminal` | `{"exit_code": <int>, "stdout": "<text>", "stderr": "<text>", "workdir": "<abs>", "timed_out": <bool>}` |
| `read_file` | `{"path": "<abs>", "content": "<lines>", "total_lines": <int>, "offset": <int>, "replaced_bytes": <int>}` |
| `write_file` | `{"path": "<abs>", "bytes_written": <int>}` |
| `patch` | `{"path": "<abs>", "diff": "<unified diff>", "replacements": <int>}` |
| `search_files` | `{"results": [{"path": "<abs>", "line": <int>, "text": "<line>"} or {"path": "<abs>"}], "truncated": <bool>}` |

Every failure is a named `{"error": ...}` result, never an exception. This includes a missing path;
a directory where a file is required; an absent `patch` `old_string`; a repeated `old_string`
without `replace_all`; a nonexistent `terminal` workdir; and a binary `read_file` input. Binary is
defined by a NUL byte in the bounded head, not by UTF-8 decoding. Text is decoded with replacement
and reports `replaced_bytes`.

```json
{"type": "function", "function": {
  "name": "terminal",
  "description": "Run a shell command and return its output. Use for anything the other tools do not cover.",
  "parameters": {"type": "object", "properties": {
    "command": {"type": "string", "description": "The command line to run."},
    "workdir": {"type": "string", "description": "Absolute directory to run in (defaults to the workspace)."},
    "timeout_s": {"type": "integer", "description": "Seconds before the process group is killed (default 120, max 600)."}},
   "required": ["command"]}}}
```

```json
{"type": "function", "function": {
  "name": "read_file",
  "description": "Read a text file, with line numbers and pagination.",
  "parameters": {"type": "object", "properties": {
    "path": {"type": "string"},
    "offset": {"type": "integer", "description": "First line to read, 1-indexed (default 1)."},
    "limit": {"type": "integer", "description": "Maximum lines (default 2000)."}},
   "required": ["path"]}}}
```

```json
{"type": "function", "function": {
  "name": "write_file",
  "description": "Write a file, replacing it whole. Writing a new path creates it.",
  "parameters": {"type": "object", "properties": {
    "path": {"type": "string"},
    "content": {"type": "string"}},
   "required": ["path", "content"]}}}
```

```json
{"type": "function", "function": {
  "name": "patch",
  "description": "Replace one exact string in a file. The old text must appear exactly once.",
  "parameters": {"type": "object", "properties": {
    "path": {"type": "string"},
    "old_string": {"type": "string"},
    "new_string": {"type": "string"},
    "replace_all": {"type": "boolean", "description": "Replace every occurrence instead of requiring one (default false)."}},
   "required": ["path", "old_string", "new_string"]}}}
```

```json
{"type": "function", "function": {
  "name": "search_files",
  "description": "Find files by name, or search inside files by regular expression.",
  "parameters": {"type": "object", "properties": {
    "pattern": {"type": "string", "description": "A regex, or a glob such as *.py when target is files."},
    "target": {"type": "string", "enum": ["content", "files"], "description": "Search inside files (default), or find files by name."},
    "path": {"type": "string", "description": "Directory or file to search (defaults to the workspace)."},
    "file_glob": {"type": "string", "description": "Restrict a content search to matching files, e.g. *.py."},
    "limit": {"type": "integer", "description": "Maximum results (default 50)."}},
   "required": ["pattern"]}}}
```

### 9.2 P4b — MCP, skills and todo

Only the fixed `mcp` wrapper is in the array; tools advertised by configured servers are runtime
results and never multiply the cache prefix. Each stdio server receives `initialize`, then
`notifications/initialized`, then `tools/list` or `tools/call`. Servers are bounded by a timeout,
and their whole process groups are closed at the end of every turn.

Skills are discovered read-only in this order: `$WILLIA_SKILLS`, `<workspace>/skills`, then
`~/.hermes/skills`. Discovery does not follow directory symlinks and stops at depth four. `list`
returns frontmatter names and descriptions plus the exact number omitted by its result cap; `read`
returns the whole selected file or nearby names when no exact name exists.

Todo operations append `todo` records to the chat log, so their state follows the normal view and
compaction lifecycle. `list` returns every live item, open first and then completed, with stable
record ids; it never silently truncates.

```json
{"type": "function", "function": {
  "name": "mcp",
  "description": "List configured MCP servers and their tools, or call one tool over stdio.",
  "parameters": {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["list", "call"]},
    "server": {"type": "string"},
    "name": {"type": "string", "description": "The MCP tool name to call."},
    "arguments": {"type": "object", "description": "Arguments for the MCP tool."}},
   "required": ["action"]}}}
```

```json
{"type": "function", "function": {
  "name": "skills",
  "description": "List available SKILL.md procedures or read one in full.",
  "parameters": {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["list", "read"]},
    "name": {"type": "string", "description": "The skill name to read."}},
   "required": ["action"]}}}
```

```json
{"type": "function", "function": {
  "name": "todo",
  "description": "Add, list, complete or drop durable planning items in the chat log.",
  "parameters": {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["add", "list", "done", "drop"]},
    "text": {"type": "string", "description": "The item text to add."},
    "id": {"type": "integer", "description": "The item id to complete or drop."}},
   "required": ["action"]}}}
```
