# P3a — `willia --notes`: feed markdown files in as `note` records

**Repo:** `~/Documents/coding/willia`. Read `docs/LOOP.md` §4 (the record table), `docs/ENV.md` §6
(the launcher), `willia/notes.py` (the engine's import) and `willia/chat.py` (the startup and the
turn). This is the P3 bootstrap item PLAN.md names ("Import OPTCHAT_HELLO.md as `note` records"),
promoted because Illan wants to ride a realistic view now.

**Do not edit** anything under `docs/`, `SCOPE.md`, `PLAN.md`, `briefs/`, `reports/`, or the frozen
modules (`store.py`, `tree.py`, `view.py`, `compactor.py`, `media.py`, `notes.py`, `text.py`,
`tools.py`, `persistence.py`, `toolkit.py`, `prompts.py`, `records.py`, `dispatch.py`).

**NO GIT COMMANDS.** No `git add`, `commit`, `stash`, `checkout`, `reset`, `restore`.
**No new dependencies.** Tests run **offline** (a fake client, as `tests/test_pump.py` does).

**Proof to report verbatim:** the pytest command from the P1b brief. 223 passed before this run; it
must be green after with your new tests.

---

## 1. The flag (`willia/cli.py`)

```
willia --notes PATH [PATH ...] [--notes-recursive] [--notes-preview]
```

- A `PATH` may be a file or a directory; a directory contributes its `*.md` files, **sorted by name**
  (non-recursive unless `--notes-recursive`). A path that does not exist, or contributes no file,
  exits nonzero naming it. Duplicate paths are imported once per occurrence (see §3).
- `--notes-preview` prints what the import *would* do and **writes nothing at all**: each file with
  its byte size, the total bytes, the projected record count, and the projected number of compaction
  **merges** the tree will need. (Project the records with the same call the import uses —
  `text.split_for_kind(text, node_bytes, "note")` — so the number is not a guess; project merges as
  `records - 1`.)
- Without `--notes-preview`: open the chat exactly as `willia` does (the same lock rules — a chat held
  by another instance must fail with its message, not fight for the log), import, then report.

## 2. The import and the summary

- Import through the engine's own path: `notes.import_notes(log, compactor, view, texts)` under
  `chat._engine()` (the drain may be alive), one call per file so a failure names its file.
- `notes.import_notes` already saves the tree, runs a bounded pass and publishes the view; do not
  duplicate that work.
- Then run **bounded completion passes** with a printed progress line, because a real corpus is
  hundreds of nodes: loop `compactor.run_pending(limit=config.compact_concurrency, deadline=…)` under
  `chat._engine()` until the queue is empty **or** a wall-clock budget (`--notes-budget`, default 900
  seconds) is spent, printing one line every 25 builds (`built=… remaining=…`). Whatever is left is
  **resumable**: the tree reloads and `Compactor` re-derives its ready queue from `buildable()`, so
  say so in the closing line rather than pretending it finished.
- Print a final summary: files, bytes, **records added**, the tree's nodes by level, the view's bytes
  and line count, whether the view is settled, and how many nodes remain unbuilt.
- `tree.save()`, `view.save()` and `chat.save()` (the backup) at the end; `chat.close()` in a
  `finally`.
- Exit 0 on success, 1 on a refusal (a locked chat, an empty path list, a preview with no files).

## 3. Behaviour worth pinning in a test, because it is a property of the design

- **No dedup.** Importing the same file twice appends it twice; the design has no notion of a
  duplicate note. Pin it with a test and say it in the closing line of a real import
  (`already present? no dedup - a second import appends again`).
- A `note` record that fits one node needs **no model call**; only the merges do. Assert that in a
  test: import a small text and count the summarizer calls (a fake counter), expecting zero for the
  leaves and `records - 1` for the merges.

## 4. Tests (offline, `tests/test_notes_cli.py`)

1. `--notes-preview` on a temp directory of two small `.md` files prints both names, the total bytes
   and a projected record count equal to the real `split_for_kind` count, and leaves the root
   untouched (no `main/`, no `view.json` change — compare bytes).
2. A directory contributes only `*.md`, sorted; `--notes-recursive` picks up a nested one and the
   non-recursive run does not.
3. A missing path exits 1 naming it; an empty selection exits 1.
4. A real import of a small file: the records are `note` kind, the tree gains level-0 nodes, the view
   covers the whole log and is settled, the backup exists, and the closing summary's counts match the
   log.
5. The no-dedup property of §3, and the summarizer-call count of §3.
6. Importing into a chat that already has records appends after them and leaves the earlier records'
   bytes unchanged.

## 5. Constraints

- Touch only: `willia/cli.py`, `willia/__init__.py` (if an export is needed), and
  `tests/test_notes_cli.py` (new). **Nothing else.** If you believe another file must change, stop and
  say so in your report instead of changing it.
- The command must be honest about cost: a preview that says "356 records, ~355 merges" prevents a
  surprise wave, and the closing line must say what is still pending.
- English everywhere; keep the docstring register of the modules you touch.
