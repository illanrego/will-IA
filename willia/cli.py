"""Launch, inspect or archive the one durable chat.

Archiving moves the complete root while holding its writer lock; an invocation
never deletes history or replaces unavailable view state.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import repl
from .chat import Chat
from .config import Config
from .store import Log


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="willia", description="One endless chat.",
                                     allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--new", action="store_true", help="archive the chat and start empty")
    mode.add_argument("--status", action="store_true", help="print chat state and exit")
    try:
        options = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    chat = None
    try:
        config = Config.load()
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
