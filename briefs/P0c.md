# P0c — close P0: the kind rename, the seven-name guard, the seeded instructions file

**Repo:** `~/Documents/coding/willia`. Read `docs/README.md` first; the doc set is the contract and
this brief cites it rather than restating it. **Do not edit anything under `docs/`**, `SCOPE.md`,
`PLAN.md`, `handoff`, `briefs/` or `reports/`. No git commands. No new dependencies.

**Proof to report verbatim:**

```
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

110 passed before this run; it must be green after, with the new assertions included.

---

## 1. `willia/prompts.py` — the kind rename in the prompt text

P0b's brief wrongly said "exactly two edits"; the `docs/ENGINE.md` §6 rename list applies to the
prompt text as well. So in `SYSTEM_PROMPT`, change the kinds-list line

```
- unii: WillIA's replies
```

to

```
- will: WillIA's replies
```

The log kind literal is `will` (`willia/store.py::KINDS`), and the level-0 node prefix is
`will: ` — leaving `unii` in the prompt would make the prompt contradict the log records and the
view the model reads. Nothing else in the block changes.

## 2. `willia/prompt-default.md` — the seeded standing instructions (a new file, in the package)

The composed system prompt is the design's block **then the user's own instructions**
(§5 of the canon; `docs/ENV.md` §4). This file is the shipped default; at runtime the harness copies
it to `~/.willia/prompt.md` if that is absent and the user edits his copy from then on. Write it as
**instructions addressed to WillIA**, in the second person, plain English, no headings other than the
four below, and keep it under ~200 words. The facts are pinned here so nothing is invented:

```
WHO YOU ARE
You work for Illan. English everywhere: chat, code, documents, commit messages.
Portuguese only in product copy and UI text.

HOW WORK IS DONE HERE
Coding is delegated, never done by you: delegate_codex for code (it takes a written
brief and works in a directory), delegate_hermes when Illan wants his own agent's
capabilities. Both run in the background; a report arrives as a [Name] message.
Never wait or poll for one.
Use web_search and web_extract for the web, and vision to look at an image.
Keep him in the loop: be brief, offer options instead of monologues, and ask before
a tradeoff he would care about.
Never make anything look further along than it is.

THIS MACHINE
You have no device shell and no computer-use tool: what is not in your tool list
cannot be done here, so say so instead of guessing.

ABOUT THIS FILE
These are Illan's own instructions, part of your fixed system prompt. He edits them
at ~/.willia/prompt.md.
```

Write that content, worded cleanly, as the file's body. Do not add tool parameter details — the
schemas carry those (`docs/TOOLS.md`).

## 3. `willia/prompts.py` — the loader for that file

```python
def default_instructions() -> str:
    """The shipped user-instructions text (willia/prompt-default.md).

    Read from the package, so an installed copy works; the harness copies it to
    ~/.willia/prompt.md on first run and the user edits that copy.
    """
```
Read it with `importlib.resources.files("willia").joinpath("prompt-default.md").read_text(
encoding="utf-8")` and return the text with trailing whitespace stripped. If the file is missing the
package is broken: let the error propagate (no `""` fallback — a silent empty default would ship a
prompt with no instructions).

## 4. `tests/test_toolkit.py` — the assertions this closes

- **Update the byte-check** (`test_system_prompt_matches_canonical_block`) so its expectation applies
  the kind rename as well as the name rename: the canon's `Unii` → `WillIA` **and** the canon's
  lowercase `unii` → `will`. The test must fail if the prompt keeps `unii`.
- **The seven-name guard** (the point of this run, `docs/ENGINE.md` §6): every name in
  `toolkit.TOOL_NAMES` appears in `prompts.build_system_prompt(prompts.default_instructions())`; and
  `zoom` and `date` appear in `prompts.SYSTEM_PROMPT` itself (they are the canon's own tools, inside
  the block).
- The composed prompt starts with the block: `build_system_prompt(default_instructions())` begins
  with `SYSTEM_PROMPT` and is strictly longer than it.
- `default_instructions()` is non-empty and mentions all five non-canon tool names, so a future edit
  that drops one is caught.
- Keep every existing assertion working (order, deep copies, shapes, the compaction request).

## 5. `pyproject.toml`

Add the package data so the seeded file ships:

```toml
[tool.setuptools.package-data]
willia = ["*.md"]
```

## Acceptance (report the raw output for each)

1. the pytest command above
2. `python -c "import willia; p=willia.prompts; print(len(p.SYSTEM_PROMPT), len(p.build_system_prompt(p.default_instructions())))"`
3. the list of files you changed
