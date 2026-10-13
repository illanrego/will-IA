# P4a brief - the shell + files batch (`terminal`, `read_file`, `write_file`, `patch`, `search_files`)

**STATUS: NOT RUN.** Two decisions are owed by Illan, and the five schemas below are a **proposal to
red-line** - they do not exist in `docs/TOOLS.md` yet, and the tool array is the cache anchor, so
whoever writes them is writing an interface. Nothing in this brief has been implemented.

Read `docs/TOOLS.md` section 9 (the parity table and its two constraints), `docs/LOOP.md` section 4
(how a result is logged), and `willia/toolkit.py`, `willia/prompt-default.md`,
`tests/test_toolkit.py::test_all_tool_names_are_in_the_composed_prompt`.

## What is true today

- The v1 array holds exactly seven tools. Adding five schemas **rewrites the shared prefix once**;
  the batch is designed to land whole and then freeze (`TOOLS.md` section 9, constraint 1). That is
  the point of the batch, not a side effect to avoid - but it means the five must be right the first
  time, because a later tweak rewrites the prefix again.
- A guard test asserts that **every** name in `toolkit.TOOL_NAMES` appears in the composed system
  prompt (`SYSTEM_PROMPT` plus the user's own instructions). A batch therefore cannot land without
  naming its tools in the prompt.
- The machine paragraph lives in `willia/prompt-default.md` and says, in Illan's own voice: "You
  have no device shell and no computer-use tool. What is not in your tool list cannot be done here."
  True today; false the moment this batch lands.
- The prompt is **per chat**. `Chat.open` writes `prompt.md` into the root only if it is absent, and
  the real chat at `~/.willia` already has one (1019 bytes, Illan's file, seeded at creation).
  Editing the repo default therefore does **not** reach an existing chat - this is the gap the first
  decision is about.

## Decision 1 - how an existing chat learns the new tool set

- **(a) A fixed, code-owned block (recommended).** `prompts.build_system_prompt` appends a *constant*
  paragraph naming the tool groups, after `SYSTEM_PROMPT` and before the user's instructions.
  Constant means it cannot vary per turn, so the anchor still holds, and every existing chat gets it
  without anyone touching a file the user owns. Cost: the composed prompt is no longer literally
  `SYSTEM_PROMPT + user text`, so `test_system_prompt_matches_canonical_block` needs one line
  restated (it asserts `composed.startswith(SYSTEM_PROMPT)` today, which stays true).
- **(b) Edit `willia/prompt-default.md` only.** Cheapest, but reaches **new chats only**:
  `~/.willia/prompt.md` keeps telling the model it has no shell, and it will not use one.
- **(c) Edit the default *and* `~/.willia/prompt.md`.** Honest, but writes to the user's own file.
  Only he should do that.

## Decision 2 - what `terminal` is allowed to do

willia has no approval gate and no sandbox, and "workspace-scoped" (`TOOLS.md` section 9) is not yet
a mechanism. This is a real policy choice, not a detail.

- **(a) Workspaced, ungated (recommended for v1).** A fixed working directory (a configured
  workspace, default `~/Documents/coding`), a per-call timeout, output clipped head+tail at the
  tool clip limit, and the command visible in the `tool` record. No allow-list. This is the same
  trust level the delegate lane already has - `codex exec` runs with the same reach today - so it
  adds no new exposure, and it is what unlocks the willcuts and posting CLIs.
- **(b) Allow-list or deny-list of commands.** Buys little: a deny-list on a shell is theatre, and
  (a) already matches the delegates' reach.
- **(c) Keep the whole group in the delegate lane** and add nothing to the array. Safest, and it
  costs exactly the thing this batch exists for.

## Proposed schemas (to red-line before anything is written)

Drafted in the style and conventions of the existing seven. `TOOLS.md` needs a new section 5b (or
5-9 relettered) for these, and `toolkit.py` must move in lockstep or the guard test fails.

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

Implied result shapes (the tool message is always a JSON string):

| Tool | Result |
|---|---|
| `terminal` | `{"exit_code": <int>, "stdout": "<text>", "stderr": "<text>", "workdir": "<abs>", "timed_out": <bool>}` |
| `read_file` | `{"path": "<abs>", "content": "<lines>", "total_lines": <int>, "offset": <int>}` |
| `write_file` | `{"path": "<abs>", "bytes_written": <int>}` |
| `patch` | `{"path": "<abs>", "diff": "<unified diff>", "replacements": <int>}` |
| `search_files` | `{"results": [{"path": "<abs>", "line": <int>, "text": "<line>"} | {"path": "<abs>"}], "truncated": <bool>}` |

Open sub-questions inside the proposal, all small and all his to settle:

1. Does `terminal` stream, or return once? (Recommend: return once, clipped - streaming would put
   per-turn state in the loop.)
2. Is the workspace a **new** config field (`workspace`) or `delegates.codex.dir` reused? (Recommend:
   a new `workspace` field defaulting to `~/Documents/coding`, with `delegates.codex.dir` defaulting
   to it so the two cannot drift.)
3. Does `write_file` refuse a path outside the workspace, or accept any absolute path? (Recommend:
   accept any absolute path, exactly as the delegates can already write anywhere - a scope that is
   only enforced in one tool is worse than none, because it reads as a guarantee.)
4. `read_file` on a binary: refuse with a named error, or return a size note? (Recommend: refuse.)

## Deliverables (once both decisions are made)

1. `willia/fs.py` (new) - the five handlers, each returning the JSON string above, each refusing
   rather than raising. `search_files` uses the stdlib; no new dependency.
2. `willia/toolkit.py` - the five schemas appended to `_SCHEMAS` and `TOOL_NAMES`, in the order
   `terminal, read_file, write_file, patch, search_files`.
3. `willia/prompt-default.md` + `prompts.build_system_prompt` - per Decision 1, and the machine
   paragraph's "you have no device shell" line corrected.
4. `willia/dispatch.py` - routing for the five, with `chat=None` still working for the ones that
   need only a workspace.
5. `docs/TOOLS.md` - a section for the five (schema + result shape + error rules), so the guard test
   and the doc agree; and section 9's table updated to mark the group landed.
6. Tests - offline, with the filesystem confined to `tmp_path`; plus a `terminal` test that runs a
   real trivial command (`python3 -c print(...)`) and asserts the exit code and both streams.
7. The batch's own Green check: serialize the tool array and the composed prompt **before and after**
   the batch and assert they differ **only** by the five added schemas and the prompt paragraph; then
   measure one real cache read on the first turn after the batch and record it in
   `docs/WIRE-FORMATS.md` section 1.

## Constraints (every one, again)

- **No git commands of any kind.** Do not commit, stash, branch, restore, diff or reset.
- Edit only the files named above.
- Do not add a dependency. stdlib only.
- A tool result is a JSON string and never list-type content in a tool message.
- A tool never raises into the loop: a failure is `{"error": ...}`.
- Nothing per-turn (cwd listings, dates, device state) may enter the array or the system prompt.
