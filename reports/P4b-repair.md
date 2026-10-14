Implemented and verified without using any git commands.

What the interrupted run left incomplete:

- `mcp`, `skills`, `todo`, and cron were wired into code, but the toolkit tests and `docs/TOOLS.md` still described the old 12-tool array.
- Cron remained throughout CLI, dispatch, prompts, log kinds, toolkit, docs, and tests.
- MCP cleanup had an edge case where descendants ignoring `SIGTERM` could survive after the direct server exited. [mcp.py](/home/illan/Documents/coding/willia/willia/mcp.py:214) now always finishes the entire process group.
- `skills` and `todo` matched the brief and required no behavioral correction.

Cron removal:

- Deleted `willia/cron.py` and `tests/test_cron.py`.
- Removed cron from toolkit, CLI, dispatch, prompt groups, log kinds, and the two authorized docs.
- `rg -n -i cron willia docs/TOOLS.md docs/PHASES.md tests` returned no matches.
- No cron-named test file remains.
- Repository-wide grep still finds historical mentions in out-of-scope `docs/HANDOFF.md`, `docs/README.md`, and `briefs/`; the edit constraint did not authorize changing those.

Tests were not weakened. I updated the toolkit’s expected names/schema cases, deleted the now-invalid cron tests, and added an MCP descendant-cleanup regression.

Full-suite result:

```text
........................................................................ [ 85%]
...........................................................              [100%]
419 passed, 3 warnings in 16.43s
```

The warnings are non-failing: two intentional invalid-record warnings and an existing delegate-thread teardown warning.

Array proof:

```text
names = zoom, date, delegate_codex, delegate_hermes, web_search, web_extract, vision, terminal, read_file, write_file, patch, search_files, mcp, skills, todo
count = 15
```

Argument schemas:

```json
{
  "mcp": {
    "type": "object",
    "properties": {
      "action": {"type": "string", "enum": ["list", "call"]},
      "server": {"type": "string"},
      "name": {"type": "string", "description": "The MCP tool name to call."},
      "arguments": {"type": "object", "description": "Arguments for the MCP tool."}
    },
    "required": ["action"]
  },
  "skills": {
    "type": "object",
    "properties": {
      "action": {"type": "string", "enum": ["list", "read"]},
      "name": {"type": "string", "description": "The skill name to read."}
    },
    "required": ["action"]
  },
  "todo": {
    "type": "object",
    "properties": {
      "action": {"type": "string", "enum": ["add", "list", "done", "drop"]},
      "text": {"type": "string", "description": "The item text to add."},
      "id": {"type": "integer", "description": "The item id to complete or drop."}
    },
    "required": ["action"]
  }
}
```