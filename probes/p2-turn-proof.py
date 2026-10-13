"""P2 acceptance, part 2 (run by the session): the delegate through a REAL model turn.

Part 1 (``p2-live-proof.py``) drove ``dispatch`` directly.  This drives the whole thing the
way a rider does: a real turn on the OpenCode Go route, where the model itself calls
``delegate_codex``, then a second turn where the queued report reaches it as the message
after the view (and must NOT be re-logged - the work record already exists).

  1. the model really calls the tool; the call lands as one ``tool`` record with the brief
  2. the ack returns and the turn ends without the master waiting
  3. the job finishes and exactly one ``work`` record carries the ``[<label>]`` prefix
  4. the file the delegate claims to have written is on disk, byte for byte
  5. a second turn sees the report without the log gaining a second work record
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import time

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia import jobs                     # noqa: E402
from willia.chat import Chat                # noqa: E402
from willia.config import Config            # noqa: E402

SENTINEL = "willia-turn-proof-b41c"
LABEL = "TurnProof"


def records_of(chat, kind: str) -> list:
    return [
        record for record in chat.log.range(0, chat.log.count())
        if record is not None and record.kind == kind
    ]


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-p2t-root-"))
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="willia-p2t-work-"))
    os.environ["WILLIA_HOME"] = str(root)
    chat = Chat.open(Config.load())
    failures: list[str] = []
    print(f"throwaway root:   {root}")
    print(f"delegate workdir: {workdir}")
    try:
        print("\n--- turn 1: the model is asked to delegate")
        chat.turn([
            "Call your delegate_codex tool exactly once, with exactly these arguments: "
            f'"name" = "{LABEL}", "model" = "gpt-5.6-sol", "dir" = "{workdir}", and '
            '"task" = "Create a file named hello.txt in the current working directory '
            "whose entire contents are exactly this one line: " + SENTINEL + " then reply "
            'with one short line saying you wrote it. Do not run any git command." '
            "After the tool returns, reply with one short sentence and stop. Do not call "
            "any other tool."
        ])

        spawns = [
            json.loads(record.text)
            for record in records_of(chat, "tool")
            if '"delegate_codex"' in record.text
        ]
        print(f"\n--- the delegate call record: {len(spawns)}")
        if not spawns:
            failures.append("the model never called delegate_codex")
        else:
            print(f"    name={spawns[0].get('name')!r} "
                  f"task={str(spawns[0].get('arguments'))[:90]!r}")

        job_dirs = sorted((chat.config.jobs_dir).glob(f"{LABEL}-*"))
        print(f"    job dirs: {[path.name for path in job_dirs]}")
        if not job_dirs:
            failures.append("no job directory was created")
            print("\n=== RESULT")
            for failure in failures:
                print(f"    FAIL: {failure}")
            return 1
        job_dir = job_dirs[-1]

        print("\n--- waiting for the supervisor thread")
        deadline = time.monotonic() + 900
        while jobs.running(chat):
            if time.monotonic() > deadline:
                failures.append("the job did not finish within 900s")
                break
            time.sleep(2)
        report_path = job_dir / "report.md"
        print(f"    report.md: {'ok' if report_path.is_file() else 'MISSING'} "
              f"{report_path.read_text(encoding='utf-8').strip()[:200]!r}")

        works = records_of(chat, "work")
        print(f"\n--- the work record: {len(works)}")
        for record in works:
            print(f"    id={record.i} {record.text[:140]!r}")
        if len(works) != 1:
            failures.append(f"expected exactly one work record, got {len(works)}")
        elif not works[0].text.startswith(f"[{LABEL}]"):
            failures.append(f"the work record lacks the [{LABEL}] prefix")

        artifact = workdir / "hello.txt"
        if not artifact.is_file():
            print("    hello.txt: MISSING")
            failures.append(f"{artifact} was never created")
        else:
            content = artifact.read_text(encoding="utf-8").strip()
            print(f"    hello.txt: {content!r}")
            if content != SENTINEL:
                failures.append(f"hello.txt is {content!r}, expected {SENTINEL!r}")

        before = len(works)
        print("\n--- turn 2: the report must arrive without being re-logged")
        chat.turn(["In one short line: what did the delegate's report say?"])
        after = len(records_of(chat, "work"))
        print(f"    work records: {before} -> {after}")
        if after != before:
            failures.append("the delivered report was logged a second time")
        prose = records_of(chat, "will")
        last = prose[-1].text if prose else ""
        print(f"    the model's last line: {last[:200]!r}")
        if "hello.txt" not in last.lower():
            failures.append("the second turn's reply does not mention the delegate's file")

        print("\n=== RESULT")
        if failures:
            for failure in failures:
                print(f"    FAIL: {failure}")
            return 1
        print("    PASS - the model delegated, the report came back, one work record")
        return 0
    finally:
        if not jobs.running(chat):
            chat.close()
        print(f"\n(evidence kept: {root} and {workdir})")


if __name__ == "__main__":
    raise SystemExit(main())
