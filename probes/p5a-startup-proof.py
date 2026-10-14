"""P5a startup acceptance (run by the session): the TUI must come up promptly, always.

The TUI failed to load once, and the cause was a startup path that waited: a usage HTTP fetch and
then the rail's engine lock, which queues behind a whole compaction drain wave. On a two-record
throwaway chat both are instant, which is why the other probe passed while the real chat hung.

So this runs against a **copy of the live chat** (193 records with pending compaction work) and
asserts the first frame arrives within a couple of seconds. Nothing on the startup path may wait.
"""

from __future__ import annotations

import fcntl
import os
import pathlib
import pty
import select
import shutil
import struct
import sys
import tempfile
import termios
import time

REPO = pathlib.Path.home() / "Documents/coding/willia"
LAUNCH = (
    "import sys; sys.path.insert(0, %r); "
    "from willia.cli import main; raise SystemExit(main(['--tui']))" % str(REPO)
)
BUDGET_S = 20.0
PROMPT_S = 3.0


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-startup-"))
    shutil.copytree(pathlib.Path.home() / ".willia", root / "chat")
    records = sum(1 for path in (root / "chat" / "main").glob("*.jsonl")
                  for line in path.read_text().splitlines() if line.strip())
    print(f"copy of the live chat: {records} records")

    env = dict(os.environ, WILLIA_HOME=str(root / "chat"), TERM="tmux-256color",
               COLORTERM="truecolor")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, [sys.executable, "-c", LAUNCH], env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))

    started = time.monotonic()
    alt_on = None
    first_frame = None
    seen = bytearray()
    while time.monotonic() - started < BUDGET_S:
        ready, _w, _x = select.select([fd], [], [], 0.2)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        seen.extend(chunk)
        if alt_on is None and b"\x1b[?1049h" in seen:
            alt_on = time.monotonic() - started
        painted = (b"\x1b[H\x1b[J" in seen or b"\x1b[H\x1b[2J" in seen)
        if first_frame is None and len(seen) > 400 and painted:
            first_frame = time.monotonic() - started
        if first_frame is not None:
            break

    # (The idle-silence check lives in p5a-tui-proof.py, on a chat that has settled: a copy of
    # the live chat is still compacting, so its rail changes for real.)
    failures = []
    if alt_on is None:
        failures.append("the alternate buffer was never entered")
    if first_frame is None:
        failures.append(f"no frame within {BUDGET_S:.0f}s")
    elif first_frame > PROMPT_S:
        failures.append(f"the first frame took {first_frame:.1f}s (budget {PROMPT_S:.0f}s)")

    print(f"  alternate buffer after {alt_on if alt_on is None else f'{alt_on:.2f}s'}")
    print(f"  first frame after      {first_frame if first_frame is None else f'{first_frame:.2f}s'}")
    print(f"  bytes: {len(seen)}")

    try:
        os.killpg(os.getpgid(pid), 9)
    except OSError:
        pass
    os.close(fd)
    shutil.rmtree(root, ignore_errors=True)

    print("\n=== RESULT")
    if failures:
        for failure in failures:
            print(f"    FAIL: {failure}")
        return 1
    print("    PASS - nothing on the startup path waited")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
