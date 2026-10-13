# P0b — the code-shaping half of P0 (delegated run)

**Repo:** `~/Documents/coding/willia`. Read `docs/README.md` first; the doc set is the contract, and
this brief cites it rather than restating it. **Do not edit anything under `docs/`.** No git
commands. No new third-party dependencies.

**Proof required at the end (report it verbatim in your final message):**

```
~/.hermes/tools/uv-0.12.3-linux-x64/uv run --no-project --with pytest python -m pytest -q
```

The suite is green now (83 passed); it must be green when you finish, with your new tests included.

---

## 1. `willia/prompts.py` — the design's one prompt (the highest-consequence file in this run)

The canon is `docs/optchat-gist.md`. Task 1 is a **transcription**, not a summary.

- `SYSTEM_PROMPT` becomes the canon's **§5 fenced code block, verbatim** — the whole block: the
  persona line, `# The view`, `# Turns`, and `# Compactions` (which includes the rubric). Copy it
  character for character, including the blank lines and the bullet markers, with **exactly two
  edits allowed**:
  1. `Unii` → `WillIA` (and `Unii's memory` → `WillIA's memory`, `to Unii` → `to WillIA`, every
     occurrence inside the block).
  2. **Drop the paragraph on computers** — the one beginning "The user's computers that have unii
     open now are listed at the start of each message." — and its following sentence about
     `device` fields and computer tasks, because will.I.A. has no device shell (`SCOPE.md`).
  Nothing else changes: no rewording, no reflowing, no added or dropped list items, no reordering.
  The tools it names are already `zoom`/`date` (the canon's own names).
- Delete the module's old `SYSTEM_PROMPT` text and the separate `COMPACTION_SYSTEM` and `RUBRIC`
  constants: their content now lives inside `SYSTEM_PROMPT` (the canon carries the compaction
  instructions and the rubric in that same block). Keep `COMPACTION_TASK`, `COMPACTION_MERGE_TASK`
  and `OVER_LENGTH_NOTICE` **verbatim** exactly as they are.
- Add:

```python
def build_system_prompt(user_instructions: str = "") -> str:
    """The one fixed prompt: the design's text, then the user's own instructions.

    The prompt is the cache anchor (docs/ENV.md section 4): it must not vary per turn.
    The instructions are read once at startup by the harness, never per call.
    """
```
  It returns `SYSTEM_PROMPT` when `user_instructions` is empty, else `SYSTEM_PROMPT` + `"\n\n"` +
  the instructions (stripped of a trailing newline). One blank line between them.
- Update the module docstring to say what the file now is (the design's single prompt for turns and
  compactions, plus the compaction task templates), citing `docs/ENGINE.md` §5.1.

## 2. `willia/compactor.py` — the one-line deviation (`docs/ENGINE.md` §2, §5.1)

- The import of `COMPACTION_SYSTEM`/`RUBRIC` goes; `_request` builds
  `task = template.format(...)` **alone** — the design's system prompt already carries the
  compaction instructions, so the former `COMPACTION_SYSTEM.format(rubric=RUBRIC) + "\n\n"` prefix
  is dropped. Update the docstring accordingly.
- **Review item (`docs/ENGINE.md` §8.9):** the per-job `contextvars.copy_context()` existed to carry
  the *host's* routing ContextVar into the worker pool. Try removing it (plain
  `executor.submit(self._summarize, request, key)`). Keep the removal **only if the whole suite,
  including `tests/test_compactor.py`'s concurrency tests, stays green**; otherwise restore it and
  say so in your report. Either way, leave a one-line comment giving the reason.

## 3. `willia/toolkit.py` — the fixed tool array (the cache anchor)

New module. Define the seven schemas **exactly as written in `docs/TOOLS.md`** (§2 `zoom`, §3 `date`,
§4 `delegate_codex` and `delegate_hermes`, §5 `web_search`, §6 `web_extract`, §7 `vision`), in that
order, as JSON-compatible literals. Public surface:

```python
TOOL_NAMES: tuple[str, ...]          # ("zoom", "date", "delegate_codex", "delegate_hermes",
                                     #  "web_search", "web_extract", "vision")
def schemas() -> list[dict]:         # a fresh deep copy every call — callers must not be able to
                                     # mutate the anchor
```

Copy the descriptions verbatim from the doc; do not improve the wording.

## 4. `tests/test_toolkit.py`

- Every name in `TOOL_NAMES` appears in `prompts.SYSTEM_PROMPT` (this is the guard the engine
  learned the hard way — `docs/ENGINE.md` §6: a prompt that names tools that are not registered
  makes navigation impossible).
- `TOOL_NAMES` equals the names of `schemas()`, in order.
- `schemas()` returns a deep copy: mutating the first result leaves the second untouched.
- Each schema has `type == "function"`, a `function.name` equal to its key, a `description`, and
  `parameters.type == "object"` with the required fields the doc lists.

## 5. `tests/test_media.py` — the direct-API replacement

The vendored file was dropped in P0a because every test in it drove the host adapter
(`docs/ENGINE.md` §4). Write a new one against the surviving API only — `media.archive_media`,
`media.media_for`, `media.record_pending_media`, `media.retry_pending_media` — with no engine and no
envelope. Cases:

1. a decodable inline image part is archived under `assets/<id>-<part>.<ext>` and indexed;
2. a media-only message (no text part) archives and indexes;
3. two parts keep their content order and both are indexed;
4. an undecodable payload warns (via `logging`) and records its reference in `assets/pending.json`,
   and the message stays ingestible;
5. a remote `http(s)` reference survives a retry untouched (`retry_pending_media` reports it under
   `remote` and keeps the reference byte-identical);
6. an index write failure is recorded as a pending `index` entry, and a later retry merges the
   entries and clears it (`retry_pending_media` → `{"archived": 1, "pending": 0, …}`), including the
   `attempts` counter behaviour the module documents;
7. audio and file parts archive with the right extension and `type`.

## 6. Package root and packaging

- `willia/__init__.py`: the final root. Export the memory API (`Log`, `Record`, `KINDS`,
  `LogLockedError`, `Tree`, `Line`, `View`, `ViewStateUnavailable`, `due`, `Compactor`,
  `CompactionRequest`, `Summarizer`, `COMPACT_CONCURRENCY`, `import_notes`) plus `prompts` and
  `toolkit` submodules. No host import, no Hermes name anywhere. Module docstring: what will.I.A.
  is (one line), its provenance (vendored from the opthermes engine at `fc0b13e` with the renames
  and the §8 deletions), and that the canon is `docs/optchat-gist.md`.
- `pyproject.toml`: project name `willia`, version `0.0.1`, description from `docs/README.md`'s
  one-liner, `requires-python = ">=3.11"`, no dependencies, and a `[tool.setuptools]` /
  hatchling-compatible package config for the `willia` package. **No console-script entry point
  yet** — `cli.py` arrives in P1, and a stub is worse than nothing.
- `README.md` at the repo root: a short pointer to `docs/README.md` (the reading order), the
  one-liner, and how to run the tests. Ten lines at most.

## Constraints

- Keep every rename from `docs/ENGINE.md` §6 (`willia/`, kind `will`, tools `zoom`/`date`,
  `Record.i`) and every deletion from §8.
- Touch only: `willia/prompts.py`, `willia/compactor.py`, `willia/toolkit.py` (new),
  `willia/__init__.py`, `tests/test_toolkit.py` (new), `tests/test_media.py` (new),
  `pyproject.toml` (new), `README.md` (new). Nothing under `docs/`, nothing in `SCOPE.md`,
  `PLAN.md` or `handoff`.
- English everywhere. No em-dashes to be avoided — prose style is yours to keep plain.
