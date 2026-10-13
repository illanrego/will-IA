"""Prove a notes import is exactly once, whole, and settled.

Compares the log against the projection computed the same way the importer does, checks
each file's first and last chunk appears exactly once, and refuses on any duplicate text.
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia.chat import Chat                 # noqa: E402
from willia.config import Config             # noqa: E402
from willia.text import split_for_kind       # noqa: E402

FILES = [pathlib.Path(p) for p in sys.argv[1:]]


def main() -> int:
    if not FILES:
        print("usage: verify-notes-import.py FILE [FILE ...]")
        return 2
    chat = Chat.open(Config.load())
    node_bytes = chat.config.node_bytes
    try:
        projected = 0
        print(f"log holds {chat.log.count()} records; view covers "
              f"{chat.view._end()} of {chat.log.count()}, settled={chat.view.settled()}\n")
        texts = []
        for path in FILES:
            chunks = split_for_kind(path.read_text(encoding="utf-8"), node_bytes, "note")
            projected += len(chunks)
            log_texts = [chat.log.get(i).text for i in range(chat.log.count())
                         if chat.log.get(i) is not None]
            first = log_texts.count(chunks[0])
            last = log_texts.count(chunks[-1])
            mark = "OK " if (first == 1 and last == 1) else "FAIL"
            print(f"  {mark} {path.name:34} {len(chunks):3} chunks | first x{first} last x{last}")
            texts.append(chunks)

        flat = [chat.log.get(i).text for i in range(chat.log.count())]
        duplicates = {t for t in flat if flat.count(t) > 1}
        notes = sum(1 for i in range(chat.log.count()) if chat.log.get(i).kind == "note")
        print(f"\nprojected records {projected} | note records in the log {notes} | "
              f"records where both are not the same: {'FAIL' if projected != notes else 'OK'}")
        print(f"duplicate texts: {len(duplicates)} "
              f"({'OK' if not duplicates else 'FAIL: ' + str(list(duplicates)[:2])[:120]})")
        unbuilt = [i for i in range(chat.log.count()) if chat.tree.get(0, i) is None]
        print(f"unbuilt level-0 nodes: {len(unbuilt)}")
        print(f"view settled: {chat.view.settled()} | view {len(chat.view.render().encode())} bytes, "
              f"{len(chat.view._pairs)} lines")
        ok = projected == notes and not duplicates and not unbuilt
        print("\nVERDICT:", "import is exactly once and complete" if ok else "PROBLEM - do not ride")
        return 0 if ok else 1
    finally:
        chat.close()


if __name__ == "__main__":
    raise SystemExit(main())
