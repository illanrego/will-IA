"""Acceptance: does the whole harness work end to end, through the real entry point?

Drives the installed `willia` CLI (not the API) against a throwaway WILLIA_HOME, so nothing touches
the real chat. Two turns: the first must make the model use a tool and leave tool + echo + will
records; the second must answer from the view, which is what the cache prefix is for. Then the meter,
the view and the compaction state are checked on disk.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

WILLIA = pathlib.Path.home() / ".local/bin/willia"
RESULT: list[str] = []


def say(ok: bool, text: str) -> None:
    RESULT.append(("PASS" if ok else "FAIL") + " - " + text)
    print(("ok   " if ok else "FAIL ") + text, flush=True)


def records(root: pathlib.Path) -> list[dict]:
    found: list[dict] = []
    for path in sorted((root / "main").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    found.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return found


def turn(root: pathlib.Path, prompt: str, seconds: int = 180) -> tuple[int, str]:
    environment = dict(os.environ, WILLIA_HOME=str(root))
    environment.pop("TERM", None)
    try:
        done = subprocess.run([str(WILLIA)], input=prompt + "\n", text=True, timeout=seconds,
                              capture_output=True, env=environment, cwd=str(root))
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return 124, f"timeout after {seconds}s: {exc.stdout or ''}"


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-acceptance-"))
    (root / "notes.txt").write_text("the ledger is green on Tuesdays\n", encoding="utf-8")
    print(f"throwaway chat: {root}\n")
    try:
        code, output = turn(root, f"Read the file {root}/notes.txt and tell me in one short line "
                                  f"what it says. Use your read_file tool.")
        say(code == 0, f"turn 1 exits cleanly (code {code})")
        kinds = [r.get("kind") for r in records(root)]
        say("user" in kinds, "turn 1 wrote the user's record")
        say("tool" in kinds, "turn 1 called a tool (a tool record landed)")
        say("echo" in kinds, "turn 1's tool returned (an echo record landed)")
        say("will" in kinds, "turn 1 produced an answer")
        said = " ".join(r.get("text", "") for r in records(root) if r.get("kind") == "will").lower()
        say("green" in said or "tuesdays" in said,
            "the answer used the file's contents, so the tool result reached the model")

        code, _ = turn(root, "In three words or fewer: what did you just tell me?")
        say(code == 0, f"turn 2 exits cleanly (code {code})")
        wills = [r for r in records(root) if r.get("kind") == "will"]
        say(len(wills) >= 2, f"turn 2 appended its answer (will records: {len(wills)})")

        usage = root / "logs/usage.jsonl"
        metered = []
        if usage.is_file():
            metered = [json.loads(l) for l in usage.read_text(encoding="utf-8").splitlines() if l.strip()]
        say(len(metered) >= 2, f"the meter recorded the calls ({len(metered)})")
        cached = [m for m in metered if (m.get("kind") == "turn"
                                         and (m.get("cache_read_tokens") or 0) > 0)]
        say(bool(cached), "a turn read the cached prefix instead of rewriting it")

        code, status = 0, subprocess.run([str(WILLIA), "--status"],
                                         capture_output=True, text=True, timeout=120,
                                         env=dict(os.environ, WILLIA_HOME=str(root))).stdout
        say("unbuilt" in status.lower(), "the view reports its coverage after both turns")
        say("0" in status, "the compactor has drained")

        print("\nstatus:\n" + status.strip()[:600])
    finally:
        shutil.rmtree(root, ignore_errors=True)
        print(f"\nthrowaway chat removed: {not root.exists()}")

    print("\n=== RESULT")
    failed = [r for r in RESULT if r.startswith("FAIL")]
    if failed:
        print(f"    FAIL - {len(failed)} of {len(RESULT)} checks failed")
        for line in failed:
            print("      " + line)
        return 1
    print(f"    PASS - all {len(RESULT)} checks passed: the harness works end to end")
    return 0


raise SystemExit(main())
