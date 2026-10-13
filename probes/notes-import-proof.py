"""Import Illan's pre-chat text as `note` records into a throwaway root, and show the result.

This is the design's own mechanism (kind `note`: "memories imported from before the chat"),
exercised against the real file PLAN.md designates, with the real 512-byte node budget.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia.chat import Chat                     # noqa: E402
from willia.config import Config                 # noqa: E402
from willia.notes import import_notes            # noqa: E402

TEXT = pathlib.Path.home() / "Documents/coding/markdowns/OPTCHAT_HELLO.md"


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-notes-"))
    os.environ["WILLIA_HOME"] = str(root)
    try:
        chat = Chat.open(Config.load())
        source = TEXT.read_text(encoding="utf-8")
        print(f"source: {TEXT.name}  {len(source.encode())} bytes\n")

        with chat._engine():
            appended = import_notes(chat.log, chat.compactor, chat.view, [source])
        chat.save()

        kinds: dict[str, int] = {}
        sizes = []
        for i in range(chat.log.count()):
            record = chat.log.get(i)
            kinds[record.kind] = kinds.get(record.kind, 0) + 1
            sizes.append(record.size)
        nodes = chat.tree.nodes()
        levels: dict[int, int] = {}
        for (level, _), _line in nodes.items():
            levels[level] = levels.get(level, 0) + 1
        details = (chat.client.last_usage.get("prompt_tokens_details") or {})
        print(f"records      {chat.log.count()} {kinds}  (sizes {min(sizes)}..{max(sizes)} bytes)")
        print(f"tree nodes   {sum(levels.values())} by level: "
              f"{dict(sorted(levels.items()))}")
        print(f"view         {len(chat.view.render().encode())} bytes, "
              f"{len(chat.view._pairs)} lines, settled={chat.view.settled()}")
        print(f"last compaction usage: prompt={chat.client.last_usage.get('prompt_tokens')} "
              f"cached={details.get('cached_tokens')}")
        print(f"\n--- the last four lines the model would read in its view")
        for line in chat.view.render().splitlines()[-4:]:
            print("    " + line[:150])
        print(f"\n--- a note record as stored (id 3)")
        print("    " + (chat.log.get(3).text[:160] if chat.log.count() > 3 else "n/a"))
        chat.close()
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
