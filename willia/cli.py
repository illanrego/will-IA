"""Launch, inspect or archive the one durable chat.

Archiving moves the complete root while holding its writer lock; an invocation
never deletes history or replaces unavailable view state.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import repl
from .chat import Chat
from .config import Config
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="willia", description="One endless chat.",
                                     allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--new", action="store_true", help="archive the chat and start empty")
    mode.add_argument("--status", action="store_true", help="print chat state and exit")
    mode.add_argument("--restore-view", action="store_true",
                      help="validate and adopt the saved view publication")
    try:
        options = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    chat = None
    try:
        config = Config.load()
        if options.restore_view:
            covered, records, roots_added = _restore_view(config)
            print(f"Restored view: covered_end={covered} records={records} "
                  f"roots_added={roots_added}")
            return 0
        if options.new:
            _archive(config.root)
        chat = Chat.open(config)
        try:
            if options.status:
                print("\n".join(chat.status()))
            else:
                repl.run(chat)
        finally:
            chat.close()
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"willia: {exc}", file=sys.stderr)
        return 1
