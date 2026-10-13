"""P1b acceptance (run by the session): a real conversation, a real tool call, a clean restart.

Uses a throwaway root, so ~/.willia (the real chat) stays untouched until Illan rides it.

  1. three real turns: a trivial one, one that should call zoom, one long paste
  2. the log, the tree and the view after the turns - and the compaction wave they caused
  3. close and reopen: the view loads (never rebuilds) and covers the whole log
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia.chat import Chat                 # noqa: E402
from willia.config import Config             # noqa: E402


def report(chat, label: str) -> None:
    log = chat.log
    kinds: dict[str, int] = {}
    for i in range(log.count()):
        record = log.get(i)
        kinds[record.kind] = kinds.get(record.kind, 0) + 1
    nodes = chat.tree.nodes()
    built = sum(1 for line in nodes.values() if line.l > 0)
    usage = chat.client.last_usage or {}
    details = usage.get("prompt_tokens_details") or {}
    print(f"\n--- {label}")
    print(f"    records {log.count()} {kinds}")
    print(f"    tree: {len(nodes)} nodes ({built} above level 0) | view "
          f"{len(chat.view.render().encode())} bytes, {len(chat.view._pairs)} lines, "
          f"settled={chat.view.settled()}")
    print(f"    usage: prompt={usage.get('prompt_tokens')} cached={details.get('cached_tokens')} "
          f"reasoning={((usage.get('completion_tokens_details') or {}).get('reasoning_tokens'))}")


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-p1b-"))
    print(f"throwaway root: {root}")
    os.environ["WILLIA_HOME"] = str(root)          # Config resolves the root from this
    config = Config.load()
    try:
        chat = Chat.open(config)
        print(f"session {chat.session[:8]}... | prompt.md seeded: {(root / 'prompt.md').exists()}")

        chat.turn(["Reply with exactly: OK"])
        report(chat, "after a trivial turn")

        chat.turn(["Use your zoom tool to open message 0 with n=1, then tell me in one line "
                   "what that message says."])
        report(chat, "after a turn that should have called zoom")

        paste = ("This is a long paste that must be logged as several messages in a row rather than "
                 "cut, because the design says any long text other than tool output is never cut. ") * 8
        chat.turn([paste])
        report(chat, "after a long paste")

        # Nothing may have been lost: the paste's text must be recoverable from the log whole.
        joined = "".join(
            chat.log.get(i).text for i in range(chat.log.count())
            if chat.log.get(i).kind == "user"
        )
        print(f"    long paste recorded: {paste.strip()[:40]!r}... present={paste.strip() in joined}")

        count_before = chat.log.count()
        chat.close()

        reopened = Chat.open(config)
        print(f"\n--- after a restart (no rebuild)")
        print(f"    records {reopened.log.count()} (was {count_before})")
        print(f"    view pairs {len(reopened.view._pairs)} | covers "
              f"{reopened.view._end()} of {reopened.log.count()} | settled={reopened.view.settled()}")
        print(f"    startup reconciliation added nothing: "
              f"{reopened.view._end() == reopened.log.count()}")
        reopened.close()
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
