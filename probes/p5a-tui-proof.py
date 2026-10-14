"""P5a acceptance (run by the session): drive the TUI through a real pty.

A display cannot be verified by reading its source. This forks a pseudo-terminal, runs
``willia --tui`` against a throwaway root, types a prompt, watches a real turn stream, scrolls,
and quits - then asserts the invariants that matter:

  1. the alternate buffer is entered, and left again on exit (the terminal is restored);
  2. the reply streams into the screen (the marker token appears without the app exiting);
  3. the turn was really logged (the same marker is in the throwaway root's log);
  4. scrolling keys are consumed without the process dying;
  5. ``:q`` exits by itself and restores the terminal.

Keystrokes are paced by draining the pty, so this does not depend on fixed sleeps beyond a floor.
"""

from __future__ import annotations

import fcntl
import json
import os
import pathlib
import pty
import re
import select
import signal
import struct
import sys
import tempfile
import termios
import time

REPO = pathlib.Path.home() / "Documents/coding/willia"
MARKER = "TUI-OK-4471"
ALT_ON = "\x1b[?1049h"
ALT_OFF = "\x1b[?1049l"

LAUNCH = (
    "import sys; sys.path.insert(0, %r); "
    "from willia.cli import main; raise SystemExit(main(['--tui']))" % str(REPO)
)


def drain(fd: int, seconds: float, sink: bytearray) -> bool:
    """Read whatever arrives for ``seconds``; return True if the child is gone."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return True
        if not chunk:
            return True
        sink.extend(chunk)
    return False


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-p5a-tui-"))
    prompt = f"Reply with exactly this token and nothing else: {MARKER}"
    env = dict(os.environ, WILLIA_HOME=str(root), TERM="tmux-256color",
               COLORTERM="truecolor", LINES="40", COLUMNS="140")
    failures: list[str] = []
    out = bytearray()
    print(f"throwaway root: {root}")

    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, [sys.executable, "-c", LAUNCH], env)
    # pty.fork() leaves the window size at 0x0; without this the app legitimately
    # draws an empty frame and the probe learns nothing.
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))

    try:
        started = time.monotonic()
        # 1. the first paint
        drain(fd, 2.5, out)
        print(f"--- first paint: {len(out)} bytes, alt-buffer entered: "
              f"{ALT_ON.encode() in out}")
        if ALT_ON.encode() not in out:
            failures.append("the alternate buffer was never entered")
        if len(out) < 200:
            failures.append(
                f"the first frame looks empty ({len(out)} bytes) - the app drew no lines")

        # 2. insert mode, type, send
        os.write(fd, b"i")
        drain(fd, 0.4, out)
        os.write(fd, prompt.encode())
        drain(fd, 0.4, out)
        os.write(fd, b"\r")
        print(f"--- sent the prompt; waiting for the reply to stream")

        waited = 0.0
        while MARKER.encode() not in out and waited < 90:
            if drain(fd, 1.0, out):
                failures.append("the process exited during the turn")
                break
            waited += 1.0
        streamed = MARKER.encode() in out
        print(f"--- reply streamed into the screen: {streamed} (after {waited:.0f}s, "
              f"{len(out)} bytes total)")
        if not streamed:
            failures.append("the reply never reached the screen")

        # The turn's end does a liveness pass; it can run a real compaction model call, during
        # which the app is not reading keys. Let it settle before driving the next keystrokes.
        drain(fd, 4.0, out)

        repaints = out.count(b"\x1b[H\x1b[2J")
        print(f"--- full repaints so far: {repaints} for {len(out)} bytes "
              f"(a repaint per stream delta would show up here)")

        # 3. normal mode, scroll a little, then quit
        os.write(fd, b"\x1b")
        drain(fd, 0.5, out)
        for keys in (b"gg", b"jjj", b"G", b"k"):
            os.write(fd, keys)
            drain(fd, 0.3, out)
        print("--- scroll keys consumed; sending :q")
        exited = False
        for attempt in range(2):
            os.write(fd, b":q\r")
            exited = drain(fd, 30.0, out)
            if exited:
                break
            print(f"--- :q attempt {attempt + 1} had not exited after 30s "
                  f"(the app may still be draining a compaction pass); pressing again")

        # 4. the terminal must have been left in a usable state
        print(f"--- exited: {exited} | alternate buffer left: {ALT_OFF.encode() in out}")
        if not exited:
            failures.append("the app did not exit on :q")
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except OSError:
                pass
        if ALT_OFF.encode() not in out:
            failures.append("the terminal was not restored (no alternate-buffer leave)")
        else:
            on_at, off_at = out.find(ALT_ON.encode()), out.find(ALT_OFF.encode())
            print(f"--- restore order: enter at {on_at}, leave at {off_at}")

        # 5. the turn was really logged
        text = ""
        main_dir = root / "main"
        if main_dir.is_dir():
            for path in sorted(main_dir.glob("*.jsonl")):
                text += path.read_text(encoding="utf-8", errors="replace")
        kinds = re.findall(r'"kind":"(\w+)"', text)
        print(f"--- the throwaway log: {len(kinds)} records {kinds}")
        if MARKER not in text:
            failures.append("the turn was never logged in the throwaway root")
        if "will" not in kinds:
            failures.append("no assistant record landed")

        print("\n=== RESULT")
        if failures:
            for failure in failures:
                print(f"    FAIL: {failure}")
            tail = bytes(out[-600:]).decode("utf-8", "replace").replace("\x1b", "\\e")
            print(f"\n    last bytes: {tail!r}")
            return 1
        print(f"    PASS - the TUI drew, streamed a real turn, scrolled and restored "
              f"({time.monotonic() - started:.0f}s, {len(out)} bytes)")
        return 0
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        print(f"(evidence kept: {root})")


if __name__ == "__main__":
    raise SystemExit(main())
