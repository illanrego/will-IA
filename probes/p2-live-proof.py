"""P2 acceptance (run by the session): one REAL delegated coding task, end to end.

Everything P2a proved used local processes; this is the piece it never did - a real Codex
job driven through the shipped dispatch path.  It calls ``dispatch("delegate_codex", ...)``
directly rather than through a model turn, because the turn would cost a chat call on top
of the job itself.  A throwaway ``WILLIA_HOME`` keeps ``~/.willia`` untouched.

  1. the call returns immediately (the master must not block)
  2. the job directory holds ``brief.md`` / ``run.log`` / ``report.md``
  3. exactly one ``work`` record, prefixed ``[<label>]``
  4. a real child chat under ``agents/<label>/`` that ``zoom("<label>")`` opens
  5. the file the delegate claims to have written - read by us, never taken on faith
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
from willia.dispatch import dispatch        # noqa: E402

MODEL = "gpt-5.6-sol"
LABEL = "Proof"
SENTINEL = "willia-delegate-proof-7f3a"
BRIEF = (
    "Create a file named hello.txt in the current working directory whose entire contents "
    f"are exactly this one line:\n{SENTINEL}\n"
    "Then reply with one short line saying you wrote it. Do not run any git command."
)


def work_records(chat) -> list:
    return [
        record for record in chat.log.range(0, chat.log.count())
        if record is not None and record.kind == "work"
    ]


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-p2-root-"))
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="willia-p2-work-"))
    os.environ["WILLIA_HOME"] = str(root)
    config = Config.load()
    chat = Chat.open(config)
    failures: list[str] = []
    print(f"throwaway root:   {root}")
    print(f"delegate workdir: {workdir}")
    try:
        started = time.monotonic()
        raw = dispatch(
            "delegate_codex",
            {"task": BRIEF, "model": MODEL, "name": LABEL, "dir": str(workdir)},
            log=chat.log, tree=chat.tree, view=chat.view, root=chat.root,
            node_bytes=chat.config.node_bytes, chat=chat,
        )
        elapsed = time.monotonic() - started
        result = json.loads(raw)
        print(f"\n--- the call")
        print(f"    returned in {elapsed:.2f}s: {result}")
        if elapsed > 2:
            failures.append("the call blocked instead of returning immediately")
        if result.get("status") != "started":
            failures.append(f"status is {result.get('status')!r}, not 'started'")

        label = result.get("name") or LABEL
        job_dir = pathlib.Path(result["report_path"]).parent
        print(f"\n--- waiting for the supervisor thread (label {label!r})")
        deadline = time.monotonic() + 900
        while jobs.running(chat):
            if time.monotonic() > deadline:
                failures.append("the job did not finish within 900s")
                break
            time.sleep(2)

        print("\n--- the job directory")
        for name in ("brief.md", "run.log", "report.md"):
            path = job_dir / name
            exists = path.is_file()
            print(f"    {name}: {'ok' if exists else 'MISSING'} "
                  f"({path.stat().st_size if exists else 0} bytes)")
            if not exists:
                failures.append(f"{job_dir.name}/{name} is missing")
        report_path = job_dir / "report.md"
        report = report_path.read_text(encoding="utf-8").strip() if report_path.is_file() else ""
        print(f"    report: {report[:400]!r}")
        if not report:
            failures.append("the delegate produced no report")

        print("\n--- the work record")
        works = work_records(chat)
        print(f"    {len(works)} work record(s)")
        for record in works:
            print(f"      id={record.i} {record.text[:120]!r}")
        if len(works) != 1:
            failures.append(f"expected exactly one work record, got {len(works)}")
        elif not works[0].text.startswith(f"[{label}]"):
            failures.append(f"the work record lacks the [{label}] prefix")

        print("\n--- the child chat")
        child = pathlib.Path(chat.root) / "agents" / label
        child_ok = (child / "view.json").is_file()
        print(f"    {child}: view.json={'ok' if child_ok else 'MISSING'}")
        if not child_ok:
            failures.append(f"no child chat at {child}")
        else:
            child_kinds: dict[str, int] = {}
            for name in sorted((child / "main").glob("*.jsonl")):
                for line in name.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        kind = json.loads(line).get("kind", "?")
                        child_kinds[kind] = child_kinds.get(kind, 0) + 1
            print(f"    child records by kind: {child_kinds}")
        opened = dispatch(
            "zoom", {"id": label},
            log=chat.log, tree=chat.tree, view=chat.view, root=chat.root,
            node_bytes=chat.config.node_bytes, chat=chat,
        )
        zoomed = json.loads(opened)
        print(f"    zoom({label!r}) -> {json.dumps(zoomed)[:300]}")
        if "error" in zoomed:
            failures.append(f"zoom({label!r}) failed: {zoomed['error']}")
        elif SENTINEL not in json.dumps(zoomed):
            failures.append("zoom returned no child memory (the brief text is absent)")

        print("\n--- the file the delegate claims to have written")
        artifact = workdir / "hello.txt"
        if not artifact.is_file():
            print("    hello.txt: MISSING")
            failures.append(f"{artifact} was never created")
        else:
            content = artifact.read_text(encoding="utf-8").strip()
            print(f"    hello.txt: {content!r}")
            if content != SENTINEL:
                failures.append(f"hello.txt is {content!r}, expected {SENTINEL!r}")

        print("\n=== RESULT")
        if failures:
            for failure in failures:
                print(f"    FAIL: {failure}")
            return 1
        print("    PASS - the delegate ran, its file exists, the memory recorded it once")
        return 0
    finally:
        if not jobs.running(chat):
            chat.close()
        # Evidence is the point: the job directory and process log must outlive
        # the run so a verdict can be re-derived from raw output, never a summary.
        print(f"\n(evidence kept: {root} and {workdir})")


if __name__ == "__main__":
    raise SystemExit(main())
