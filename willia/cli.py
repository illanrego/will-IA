"""Launch, inspect or archive the one durable chat.

Archiving moves the complete root while holding its writer lock; an invocation
never deletes history or replaces unavailable view state.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import notes, repl, text, tui, usage
from .chat import Chat
from .config import Config
from .envfile import MissingCredential
from .store import Log
from .tree import Tree


def _archive(root: Path) -> None:
    if not root.exists():
        return
    with Log(root) as _owner:
        parent = Path.home() / ".willia-archive"
        parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = parent / timestamp
        if destination.exists():
            raise FileExistsError(f"Archive already exists: {destination}")
        shutil.move(str(root), str(destination))


def _backup_pairs(raw, *, label: str, tree: Tree) -> int:
    if not isinstance(raw, list):
        raise ValueError(f"Invalid view backup: {label} is not a list")
    cursor = 0
    for pair in raw:
        if (not isinstance(pair, list) or len(pair) != 2
                or any(type(value) is not int or value < 0 for value in pair)):
            raise ValueError(f"Invalid view backup: {label} contains an invalid pair")
        level, index = pair
        if (index << level) != cursor:
            raise ValueError(f"Invalid view backup: {label} is not contiguous")
        if tree.get(level, index) is None:
            raise ValueError(
                f"View backup pair ({level}, {index}) has no built tree node")
        cursor += 1 << level
    return cursor


def _validate_view_backup(raw, tree: Tree) -> int:
    top_keys = {"version", "pairs", "batch_pending", "compaction_views"}
    if not isinstance(raw, dict) or set(raw) != top_keys or raw.get("version") != 2:
        raise ValueError("Invalid view backup: expected version 2 view state")
    if type(raw["batch_pending"]) is not bool:
        raise ValueError("Invalid view backup: batch_pending is not boolean")
    covered = _backup_pairs(raw["pairs"], label="pairs", tree=tree)
    compaction_views = raw["compaction_views"]
    if not isinstance(compaction_views, list):
        raise ValueError("Invalid view backup: compaction_views is not a list")
    item_keys = {"min_bytes", "max_bytes", "pairs", "batch_pending", "contexts"}
    for position, item in enumerate(compaction_views):
        if not isinstance(item, dict) or set(item) != item_keys:
            raise ValueError(
                f"Invalid view backup: compaction_views[{position}] has the wrong shape")
        minimum, maximum = item["min_bytes"], item["max_bytes"]
        if (type(minimum) is not int or type(maximum) is not int
                or minimum < 0 or maximum <= 0 or minimum > maximum):
            raise ValueError("Invalid view backup: invalid compaction view budgets")
        if type(item["batch_pending"]) is not bool:
            raise ValueError("Invalid view backup: invalid compaction batch state")
        _backup_pairs(item["pairs"], label="compaction pairs", tree=tree)
        contexts = item["contexts"]
        if not isinstance(contexts, dict) or any(not isinstance(key, str) for key in contexts):
            raise ValueError("Invalid view backup: invalid compaction contexts")
        for key, context in contexts.items():
            if (not isinstance(context, list) or len(context) != 2
                    or type(context[0]) is not int or context[0] < 0):
                raise ValueError(f"Invalid view backup: invalid context {key!r}")
            end = _backup_pairs(context[1], label=f"context {key!r}", tree=tree)
            if end > context[0]:
                raise ValueError(f"Invalid view backup: context {key!r} exceeds its boundary")
    return covered


def _restore_view(config: Config) -> tuple[int, int, int]:
    backup = config.view_backup_file
    if not backup.is_file():
        raise ValueError(f"View backup is absent: {backup}")
    try:
        raw = json.loads(backup.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"View backup is corrupt: {exc}") from exc

    with Log(config.root, read_only=True) as log:
        records = log.count()
        tree = Tree(config.root, config.node_bytes, read_only=True)
        covered = _validate_view_backup(raw, tree)
    if covered > records:
        raise ValueError(
            f"View backup covers {covered} records but the log contains {records}")

    roots_added = records - covered
    config.view_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup, config.view_file)
    chat = Chat.open(config)
    try:
        with chat._engine():
            if chat.view._end() != records:
                raise RuntimeError("Restored view did not advance to the log record count")
    finally:
        chat.close()
    return covered, records, roots_added


def _print_usage(config: Config) -> None:
    """The local meter plus the account's own plan windows.  Writes nothing."""
    path = usage.usage_file(config.root)
    entries = usage.read(path)
    summary = usage.totals(entries)
    print(f"Usage log: {path}")
    print(f"Calls: {summary['calls']}")
    for name in usage.BUCKETS:
        print(f"{name}: {summary[name]}")
    for kind in sorted(summary["by_kind"]):
        bucket = summary["by_kind"][kind]
        print(f"{kind}: calls={bucket['calls']} input={bucket['input_tokens']} "
              f"output={bucket['output_tokens']} cache_read={bucket['cache_read_tokens']} "
              f"cache_write={bucket['cache_write_tokens']} "
              f"reasoning={bucket['reasoning_tokens']}")
    if entries:
        print(f"Latest call: {entries[-1].get('at')} ({entries[-1].get('kind')})")
    try:
        windows = usage.subscription_windows(config)
    except (OSError, ValueError, MissingCredential) as exc:
        print(f"Windows: unavailable ({exc})")
        return
    reported = [name for name in usage.WINDOWS if isinstance(windows.get(name), dict)]
    if not reported:
        print("Windows: none reported for this plan")
    for name in reported:
        window = windows[name]
        print(f"{name}: {window.get('percent')}% resets {window.get('resetsAt')}")


def _note_files(raw_paths: list[str], *, recursive: bool) -> list[Path]:
    """Expand note operands in occurrence order without collapsing duplicates."""
    files = []
    for raw in raw_paths:
        path = Path(raw).expanduser()
        if not path.exists():
            raise ValueError(f"Note path does not exist: {path}")
        if path.is_file():
            selected = [path]
        elif path.is_dir():
            candidates = path.rglob("*.md") if recursive else path.glob("*.md")
            selected = sorted(
                (candidate for candidate in candidates if candidate.is_file()),
                key=lambda candidate: (candidate.name, str(candidate)),
            )
        else:
            selected = []
        if not selected:
            raise ValueError(f"Note path contributes no files: {path}")
        files.extend(selected)
    return files


def _read_note(path: Path) -> tuple[str, int]:
    try:
        raw = path.read_bytes()
        return raw.decode("utf-8"), len(raw)
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Cannot read note file {path}: {exc}") from exc


def _preview_notes(config: Config, files: list[Path]) -> None:
    total_bytes = 0
    total_records = 0
    print("Notes preview (no writes):")
    for path in files:
        note_text, size = _read_note(path)
        records = len(text.split_for_kind(note_text, config.node_bytes, "note"))
        total_bytes += size
        total_records += records
        print(f"{path}: bytes={size} records={records}")
    print(f"Files: {len(files)}")
    print(f"Total bytes: {total_bytes}")
    print(f"Projected records: {total_records}")
    print(f"Projected compaction merges: ~{max(total_records - 1, 0)}")


def _finish_note_compaction(chat: Chat, budget: float) -> int:
    """Spend at most ``budget`` seconds completing queued note compactions."""
    deadline = time.monotonic() + budget
    built = 0
    next_progress = 25
    while True:
        with chat._engine():
            remaining = len(chat.compactor._queued)
        if not remaining or time.monotonic() >= deadline:
            break
        with chat._engine():
            pass_built = chat.compactor.run_pending(
                limit=chat.config.compact_concurrency,
                deadline=deadline,
            )
            remaining = len(chat.compactor._queued)
        built += pass_built
        if built >= next_progress:
            print(f"built={built} remaining={remaining}", flush=True)
            next_progress = ((built // 25) + 1) * 25
        if pass_built == 0 and remaining:
            pause = min(0.05, max(0.0, deadline - time.monotonic()))
            if pause:
                time.sleep(pause)
    return built


def _import_note_files(config: Config, files: list[Path], *, budget: float) -> None:
    loaded = [(path, *_read_note(path)) for path in files]
    chat = Chat.open(config)
    try:
        before = chat.log.count()
        for path, note_text, _size in loaded:
            try:
                with chat._engine():
                    notes.import_notes(
                        chat.log, chat.compactor, chat.view, [note_text])
            except Exception as exc:
                raise RuntimeError(f"Cannot import note file {path}: {exc}") from exc

        completion_built = _finish_note_compaction(chat, budget)
        with chat._engine():
            chat.tree.save()
            chat.view.save()
            chat.save()
            added = chat.log.count() - before
            nodes = Counter(level for level, _index in chat.tree.nodes())
            view_text = chat.view.render()
            view_lines = len(chat.view.lines())
            settled = chat.view.settled()
            remaining = len(chat.compactor._queued)

        levels = ", ".join(f"{level}={nodes[level]}" for level in sorted(nodes)) or "none"
        total_bytes = sum(size for _path, _text, size in loaded)
        print(f"Imported notes: files={len(files)} bytes={total_bytes} records_added={added}")
        print(f"Tree nodes by level: {levels}")
        print(f"View: bytes={len(view_text.encode('utf-8'))} lines={view_lines} "
              f"settled={'yes' if settled else 'no'}")
        print(f"Completion: built={completion_built} remaining={remaining}")
        print(f"Pending: {remaining} unbuilt nodes; any remaining work is resumable on "
              "the next run; already present? no dedup - a second import appends again")
    finally:
        chat.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="willia", description="One endless chat.",
                                     allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--new", action="store_true", help="archive the chat and start empty")
    mode.add_argument("--status", action="store_true", help="print chat state and exit")
    mode.add_argument("--restore-view", action="store_true",
                      help="validate and adopt the saved view publication")
    mode.add_argument("--usage", action="store_true",
                      help="print the usage meter and the account's plan windows")
    mode.add_argument("--tui", action="store_true",
                      help="run the modal terminal interface")
    mode.add_argument("--notes", nargs="*", metavar="PATH",
                      help="import markdown files as note records")
    parser.add_argument("--notes-recursive", action="store_true",
                        help="include markdown files in nested directories")
    parser.add_argument("--notes-preview", action="store_true",
                        help="show note import cost without writing")
    parser.add_argument("--notes-budget", type=float, default=None, metavar="SECONDS",
                        help="maximum completion time after importing notes (default: 900)")
    try:
        options = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    chat = None
    try:
        config = Config.load()
        note_option = (options.notes_recursive or options.notes_preview
                       or options.notes_budget is not None)
        if options.notes is None and note_option:
            raise ValueError("Note options require --notes PATH [PATH ...]")
        if options.notes is not None:
            if not options.notes:
                raise ValueError("--notes requires at least one PATH")
            budget = 900.0 if options.notes_budget is None else options.notes_budget
            if budget < 0:
                raise ValueError("--notes-budget must be nonnegative")
            files = _note_files(options.notes, recursive=options.notes_recursive)
            if options.notes_preview:
                _preview_notes(config, files)
            else:
                _import_note_files(config, files, budget=budget)
            return 0
        if options.restore_view:
            covered, records, roots_added = _restore_view(config)
            print(f"Restored view: covered_end={covered} records={records} "
                  f"roots_added={roots_added}")
            return 0
        if options.usage:
            _print_usage(config)
            return 0
        if options.tui and not sys.stdout.isatty():
            raise ValueError("--tui requires stdout to be a terminal")
        if options.new:
            _archive(config.root)
        chat = Chat.open(config)
        try:
            if options.status:
                print("\n".join(chat.status()))
            elif options.tui:
                tui.run(chat)
            else:
                repl.run(chat)
        finally:
            chat.close()
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"willia: {exc}", file=sys.stderr)
        return 1
