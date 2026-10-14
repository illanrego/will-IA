# P4a brief - the shell + files batch: `terminal`, `read_file`, `write_file`, `patch`, `search_files`

**APPROVED 2026-10-13 - run this.** The six decisions below are settled rulings, not options, and the
five schemas are approved: copy them **verbatim** into `docs/TOOLS.md` and `willia/toolkit.py` in
lockstep - a guard test compares the two.

Read first: `docs/TOOLS.md` (sections 1-4 for the conventions every tool follows, 8 and 9),
`docs/LOOP.md` section 4 (how a result is logged), `willia/dispatch.py`, `willia/toolkit.py`,
`willia/prompts.py`, `willia/config.py`, `willia/web.py` (the shape a handler has), and
`tests/test_toolkit.py` (the guard tests you must update).

## The settled rulings

1. **The prompt carries a constant, code-owned block.** `prompts.build_system_prompt` returns
   `SYSTEM_PROMPT + "\n\n" + TOOL_GROUPS + "\n\n" + instructions`, where `TOOL_GROUPS` is a new module
   constant. It reaches every existing chat without editing a file the user owns. `SYSTEM_PROMPT`
   itself must not change by even one byte - a test compares it to the canon.
2. **`terminal` is workspaced and ungated.** It runs in the configured workspace, with a per-call
   timeout, output clipped head+tail; no allow-list. That is the same reach `codex exec` already has.
3. **One workspace setting.** A new `Config.workspace` defaulting to a new module constant
   `DEFAULT_WORKSPACE = "~/Documents/coding"`, and `CodexDelegateConfig.dir` defaulting to that same
   constant so the two cannot drift. Add `workspace` to `Config.load`'s `known` set and thread it into
   `_codex` so an unset delegate dir follows the workspace.
4. **`terminal` does not stream.** It returns once, clipped.
5. **`write_file` accepts any absolute path**, exactly as the delegates can already write anywhere.
6. **`read_file` refuses binary**, so the model gets an honest error instead of garbage in a log that
   is never edited. The test is a **NUL byte** in the bounded head (present in essentially every real
   binary, absent from text) - *not* "does not decode as UTF-8", which would wrongly refuse a
   legacy-encoded text file. A file that passes is decoded with `errors="replace"` and the result
   reports how many bytes were replaced (`replaced_bytes`). Read a bounded head (the first few MB)
   and stop rather than slurping a huge file to answer a 2000-line request.

## Frozen schemas (verbatim, appended after `vision`, in this order)

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

**A trap in `docs/TOOLS.md`:** the guard test reads every ```json block in the file, in order, and
synthesizes `delegate_hermes` from `delegate_codex` at index 2. The five new blocks must therefore
appear **after** the `vision` block, and no other ```json block may follow them in the file. Do not
renumber the existing sections - give the batch its own subsection at the end of section 9.

## Result shapes (the tool message is always a JSON string; a failure is `{"error": ...}`)

| Tool | Result |
|---|---|
| `terminal` | `{"exit_code": <int>, "stdout": "<text>", "stderr": "<text>", "workdir": "<abs>", "timed_out": <bool>}` |
| `read_file` | `{"path": "<abs>", "content": "<lines>", "total_lines": <int>, "offset": <int>, "replaced_bytes": <int>}` |
| `write_file` | `{"path": "<abs>", "bytes_written": <int>}` |
| `patch` | `{"path": "<abs>", "diff": "<unified diff>", "replacements": <int>}` |
| `search_files` | `{"results": [{"path": "<abs>", "line": <int>, "text": "<line>"} or {"path": "<abs>"}], "truncated": <bool>}` |

Error rules, each a named `{"error": ...}` and never an exception: a missing path; a path that is a
directory where a file is wanted; a `patch` whose `old_string` is absent, or (without `replace_all`)
appears more than once; a `terminal` `workdir` that does not exist; a `read_file` on binary.

## Deliverables

1. `willia/fs.py` (new) - the five handlers, each returning its JSON string. `terminal` uses
   `subprocess.Popen(command, shell=True, cwd=workdir, stdout=PIPE, stderr=PIPE,
   start_new_session=True)` with the same process-group kill on timeout the delegate supervisor uses
   (`os.killpg(..., signal.SIGKILL)`), and clips stdout/stderr head+tail at `config.tool_clip_chars`.
   `search_files` is stdlib: `os.walk`, skip `.git` directories, skip files over ~5 MB, and honour
   `target` / `file_glob` / `limit` so it terminates on a large tree.
2. `willia/toolkit.py` - the five schemas appended to `_SCHEMAS` and `TOOL_NAMES`.
3. `willia/prompts.py` - `TOOL_GROUPS` as a module constant, written in the register of
   `willia/prompt-default.md` (second person, plain), naming the five new tools and stating that they
   run on Illan's machine with no approval step. It must also say that any earlier line claiming there
   is no shell is out of date: existing chats carry Illan's own seeded `~/.willia/prompt.md`, which
   still contains that sentence and must not contradict the tool list. `build_system_prompt` composes
   as ruling 1 says.
4. `willia/config.py` - `DEFAULT_WORKSPACE`, `Config.workspace`, the `known` entry, and
   `delegates.codex.dir` following the same constant.
5. `willia/dispatch.py` - routing for the five, with `chat=None` still working (fall back to
   `Config()` for the workspace, as the web tools already do).
6. `docs/TOOLS.md` - the batch's subsection (the five schemas, the result shapes, the error rules),
   section 9's table marking the shell + files row as landed, and five new rows in section 8's
   "where each result lands" table (all five land as `echo`).
7. Tests - `tests/test_fs.py` (new) plus the updates `tests/test_toolkit.py` needs: `NAMES` becomes
   twelve, `test_function_schema_shape` gains the five rows, `test_all_tool_names_are_in_the_composed_prompt`
   keeps its `NAMES[2:]` claim only for the five names that live in the user's instructions, and the
   two prompt-composition tests must expect the new block. **All offline**; every filesystem test
   confined to `tmp_path`; the `terminal` test runs a real trivial command
   (`python3 -c "print(...)"`) and asserts the exit code and both streams; another asserts that a
   timeout kills a sleeping process group.

## The batch's own Green check (the session runs this, not you)

Serialize `toolkit.schemas()` and `build_system_prompt(default_instructions())` **before and after**
the batch and assert they differ only by the five added schemas and the added prompt block; then the
session measures one real cache read on the first turn after the batch and records it in
`docs/WIRE-FORMATS.md` section 1.

## Constraints (every one, again)

- **No git commands of any kind.** Do not commit, stash, branch, restore, diff or reset.
- Edit only the files named above.
- Do not add a dependency. stdlib only.
- Do not change a byte of `prompts.SYSTEM_PROMPT` or of the seven existing schemas.
- A tool result is a JSON string and never list-type content in a tool message.
- A tool never raises into the loop: a failure is `{"error": ...}`.
- Nothing per-turn (a directory listing, a date, device state) may enter the array or the prompt.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then paste the `TOOL_GROUPS` constant and the five handler bodies, and say for each deliverable
exactly what you changed.
