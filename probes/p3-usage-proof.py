"""P3 acceptance (run by the session): the meter records real calls; the windows read real.

Two real turns on a throwaway root, so the numbers are the route's own.  Then the read-only
report script is run against the same root as an operator would run it.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia import usage                    # noqa: E402
from willia.chat import Chat                # noqa: E402
from willia.config import Config            # noqa: E402


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-p3-root-"))
    os.environ["WILLIA_HOME"] = str(root)
    config = Config.load()
    chat = Chat.open(config)
    failures: list[str] = []
    print(f"throwaway root: {root}")
    try:
        for round_number in (1, 2):
            chat.turn([f"Reply with exactly: OK{round_number}"])
        print("(two real turns done)")

        path = usage.usage_file(root)
        entries = usage.read(path)
        print(f"\n--- the meter at {path}")
        for entry in entries:
            print(f"    {json.dumps(entry)}")
        summary = usage.totals(entries)
        print(f"    totals: calls={summary['calls']} kinds={sorted(summary['by_kind'])}")
        if len(entries) != 2:
            failures.append(f"expected 2 metered calls, got {len(entries)}")
        elif [entry["kind"] for entry in entries] != ["turn", "turn"]:
            failures.append(f"kinds are {[entry['kind'] for entry in entries]}")
        else:
            if not all(entry["input_tokens"] > 0 for entry in entries):
                failures.append("a turn reported no input tokens")
            if entries[1]["cache_read_tokens"] <= 0:
                failures.append("the second turn reported nothing read from the cache")

        print("\n--- the account's own windows (GET /usage)")
        try:
            windows = usage.subscription_windows(config)
            for name in usage.WINDOWS:
                print(f"    {name}: {windows.get(name)}")
            if not any(isinstance(windows.get(name), dict) for name in usage.WINDOWS):
                failures.append("the account reported no window at all")
        except Exception as exc:  # noqa: BLE001 - the measurement is the point
            failures.append(f"windows: {type(exc).__name__}: {exc}")
            print(f"    ERROR {type(exc).__name__}: {exc}")

        print("\n--- scripts/session-report.py, read-only, against this root")
        report = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "session-report.py"), "--root", str(root)],
            capture_output=True, text=True, timeout=180,
        )
        print("\n".join("    " + line for line in report.stdout.strip().splitlines()))
        if report.returncode != 0:
            failures.append(f"the report exited {report.returncode}: {report.stderr.strip()}")
        for needed in ("Records:", "Tree nodes:", "View:", "Usage:", "Jobs:", "Children:"):
            if needed not in report.stdout:
                failures.append(f"the report is missing {needed!r}")

        print("\n=== RESULT")
        if failures:
            for failure in failures:
                print(f"    FAIL: {failure}")
            return 1
        print("    PASS - real calls metered, real windows read, report ran read-only")
        return 0
    finally:
        chat.close()
        print(f"\n(evidence kept: {root})")


if __name__ == "__main__":
    raise SystemExit(main())
