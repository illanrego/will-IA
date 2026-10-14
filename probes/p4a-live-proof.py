"""P4a acceptance (run by the session): the shell + files batch, for real.

Two parts:

  1. the five tools driven through ``dispatch`` with real files in a throwaway workspace, including
     one refusal (a binary read);
  2. a real model turn that uses ``terminal`` itself, so the round trip through the wire is proven,
     the result lands as an ``echo`` record, and the batch's own Green number can be measured: the
     prefix is rewritten once (turn 1) and then cached again (turn 2).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia import usage                    # noqa: E402
from willia.chat import Chat                # noqa: E402
from willia.config import Config            # noqa: E402
from willia.dispatch import dispatch        # noqa: E402


def records_of(chat, kind: str) -> list:
    return [
        record for record in chat.log.range(0, chat.log.count())
        if record is not None and record.kind == kind
    ]


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-p4a-root-"))
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="willia-p4a-work-"))
    os.environ["WILLIA_HOME"] = str(root)
    config = Config.load()
    chat = Chat.open(config)
    failures: list[str] = []
    print(f"throwaway root:    {root}")
    print(f"throwaway workdir: {workdir}")

    def call(name: str, arguments: dict) -> dict:
        return json.loads(dispatch(
            name, arguments, log=chat.log, tree=chat.tree, view=chat.view,
            root=chat.root, node_bytes=chat.config.node_bytes, chat=chat,
        ))

    try:
        print("\n=== the five tools, driven directly with real files")
        ran = call("terminal", {"command": "python3 -c \"print(6*7)\"", "workdir": str(workdir)})
        print(f"terminal       -> {ran}")
        if ran.get("exit_code") != 0 or ran.get("stdout") != "42\n":
            failures.append(f"terminal did not run: {ran}")

        target = workdir / "notes.txt"
        wrote = call("write_file", {"path": str(target), "content": "alpha\nbeta\n"})
        print(f"write_file     -> {wrote}")

        read = call("read_file", {"path": str(target)})
        print(f"read_file      -> {read}")
        if read.get("content") != "1: alpha\n2: beta":
            failures.append(f"read_file did not number the lines: {read}")

        patched = call("patch", {"path": str(target), "old_string": "beta", "new_string": "gamma"})
        print(f"patch          -> replacements={patched.get('replacements')} "
              f"diff={json.dumps(patched.get('diff'))[:80]}")
        if patched.get("replacements") != 1 or target.read_text() != "alpha\ngamma\n":
            failures.append(f"patch did not change the file: {patched}")

        found = call("search_files", {"pattern": "gamma", "path": str(workdir)})
        print(f"search_files   -> {found}")
        if not found.get("results"):
            failures.append(f"search_files found nothing: {found}")

        binary = workdir / "blob.bin"
        binary.write_bytes(b"text\x00more")
        refused = call("read_file", {"path": str(binary)})
        print(f"read_file(bin) -> {refused}")
        if "error" not in refused:
            failures.append("a binary read was not refused")

        print("\n=== a real turn, with the model calling terminal itself")
        chat.turn(["Use your terminal tool to run exactly this command: "
                   "python3 -c \"print(2026*2)\" -- then tell me in one short line what it printed."])
        tools = [record.text for record in records_of(chat, "tool")]
        echoes = [record.text for record in records_of(chat, "echo")]
        prose = [record.text for record in records_of(chat, "will")]
        print(f"    tool records: {json.dumps(tools)[:160]}")
        print(f"    echo records: {[text[:80] for text in echoes]}")
        print(f"    reply:        {prose[-1][:120] if prose else None!r}")
        if not any("terminal" in text for text in tools):
            failures.append("the model did not call terminal")
        if not any("4052" in text for text in echoes):
            failures.append("the terminal result never landed as an echo record")
        if not prose or "4052" not in prose[-1]:
            failures.append("the reply does not use the command's output")

        print("\n=== the batch's Green number: one prefix rewrite, then cached")
        chat.turn(["In one short line: what did you just compute for me?"])
        turns = [entry for entry in usage.read(usage.usage_file(root)) if entry["kind"] == "turn"]
        for number, entry in enumerate(turns, 1):
            prompt = entry["input_tokens"]
            cached = entry["cache_read_tokens"]
            share = (cached / prompt * 100) if prompt else 0.0
            print(f"    turn {number}: prompt_tokens={prompt} cache_read={cached} ({share:.1f}%) "
                  f"reasoning={entry['reasoning_tokens']}")
        if len(turns) < 2:
            failures.append(f"expected two metered turns, got {len(turns)}")
        elif turns[-1]["cache_read_tokens"] <= 0:
            failures.append("the second turn read nothing from the cache")

        print("\n=== RESULT")
        if failures:
            for failure in failures:
                print(f"    FAIL: {failure}")
            return 1
        print("    PASS - five tools ran for real, one round-tripped through the model")
        return 0
    finally:
        chat.close()
        print(f"\n(evidence kept: {root} and {workdir})")


if __name__ == "__main__":
    raise SystemExit(main())
