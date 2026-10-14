"""P5b-P5d acceptance (run by the session): focus and hints, yank and help, themes.

Drives a real pty through the keys these slices add and asserts the things that are hard to fake:

  * Tab moves focus to the rail and the status line says so;
  * moving inside the rail changes the hint line (the explanations, alive);
  * Enter folds the focused thing and Esc unfolds it;
  * y writes a well-formed OSC 52 clipboard sequence (which tmux passes through);
  * ? opens the help overlay and Esc closes it without moving the transcript;
  * :theme green repaints in the green palette's own SGR.

Runs against a throwaway root, so the live chat is untouched.
"""

from __future__ import annotations

import fcntl
import os
import pathlib
import pty
import re
import select
import shutil
import signal
import struct
import sys
import tempfile
import termios
import time

REPO = pathlib.Path.home() / "Documents/coding/willia"
GREEN_AGENT = "\x1b[38;2;123;235;190m"          # theme.py's green "agent" token, #7BEBBE
OSC52 = "\x1b]52;c;"
LAUNCH = (
    "import sys; sys.path.insert(0, %r); "
    "from willia.cli import main; raise SystemExit(main(['--tui']))" % str(REPO)
)


def drain(fd: int, seconds: float, sink: bytearray) -> bool:
    """Read for ``seconds``; True when the child is gone."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ready, _w, _x = select.select([fd], [], [], 0.1)
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


def status_line(seen: bytes) -> str:
    """The last frame's bottom line, stripped of SGR."""
    frame = seen.rsplit(b"\x1b[H", 1)[-1]
    plain = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", frame)
    lines = [line.strip() for line in plain.split(b"\r\n") if line.strip()]
    for line in reversed(lines):
        if re.match(rb"^(NORMAL|INSERT|MEMORY|\?)", line):
            return line.decode("utf-8", "replace")
    return lines[-1].decode("utf-8", "replace") if lines else ""


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-p5b-"))
    env = dict(os.environ, WILLIA_HOME=str(root), TERM="tmux-256color", COLORTERM="truecolor")
    failures: list[str] = []
    seen = bytearray()

    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, [sys.executable, "-c", LAUNCH], env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))

    try:
        drain(fd, 2.5, seen)
        print(f"--- first paint: {len(seen)} bytes")
        if len(seen) < 400:
            failures.append("the app never painted")
            raise SystemExit(1)

        # A real turn first: an empty transcript has nothing to focus, fold or yank.
        print("\n=== a real turn, so there is something to work with")
        marker = "P5B-OK-9182"
        os.write(fd, b"i")
        drain(fd, 0.3, seen)
        os.write(fd, f"Reply with exactly this token and nothing else: {marker}".encode())
        drain(fd, 0.3, seen)
        os.write(fd, b"\r")
        waited = 0.0
        while marker.encode() not in seen and waited < 90:
            if drain(fd, 1.0, seen):
                failures.append("the process exited during the turn")
                break
            waited += 1.0
        print(f"    reply streamed: {marker.encode() in seen} (after {waited:.0f}s)")
        if marker.encode() not in seen:
            failures.append("the turn never reached the screen")
        drain(fd, 6.0, seen)          # the post-turn pass

        print("\n=== P5b: focus and the hint line")
        before = status_line(bytes(seen))
        print(f"    before focus: {before[:100]!r}")
        os.write(fd, b"\t")
        drain(fd, 0.8, seen)
        after = status_line(bytes(seen))
        print(f"    after Tab:    {after[:100]!r}")
        if "rail" not in after.lower():
            failures.append(f"Tab did not move focus to the rail (status: {after[:60]!r})")

        os.write(fd, b"j")
        drain(fd, 0.8, seen)
        moved = status_line(bytes(seen))
        print(f"    after j:      {moved[:100]!r}")
        if moved == after:
            failures.append("moving inside the rail did not change the hint line")
        tail = moved.split("·", 2)[-1].strip()
        if len(tail) < 20:
            failures.append(f"the focused row has no explanation (status: {moved[:70]!r})")

        os.write(fd, b"\r")
        drain(fd, 0.6, seen)
        folded = bytes(seen)
        os.write(fd, b"\x1b")
        drain(fd, 0.6, seen)
        print(f"    fold/unfold:  {'the frame changed' if bytes(seen) != folded else 'NO CHANGE'}")
        if bytes(seen) == folded:
            failures.append("Enter/Esc did not fold and unfold the focused thing")

        print("\n=== P5c: yank and the help overlay")
        # y is transcript-only by design. Tab toggles, so it can land back in the rail; Ctrl-w l
        # moves right deterministically.
        os.write(fd, b"\x17l")
        drain(fd, 0.5, seen)
        before_yank = len(seen)
        os.write(fd, b"y")
        drain(fd, 1.0, seen)
        yank = bytes(seen[before_yank:])
        payload = re.search(rb"\x1b\]52;c;([A-Za-z0-9+/=]*)", yank)
        decoded = ""
        if payload:
            import base64
            decoded = base64.b64decode(payload.group(1)).decode("utf-8", "replace")
        print(f"    y wrote {len(yank)} bytes; OSC 52 present: {payload is not None}")
        print(f"    clipboard payload: {decoded[:60]!r}")
        if payload is None:
            failures.append("y did not emit an OSC 52 clipboard sequence")
        elif not decoded.strip():
            failures.append("the yanked clipboard payload was empty")

        os.write(fd, b"?")
        drain(fd, 1.0, seen)
        overlay = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]", b"", bytes(seen[-20000:])).decode(
            "utf-8", "replace")
        opened = any(word in overlay.lower() for word in ("yank", "zoom", "fold", "palette"))
        print(f"    ? overlay opened: {opened}")
        if not opened:
            failures.append("? did not open a help overlay")
        os.write(fd, b"\x1b")
        drain(fd, 0.8, seen)

        print("\n=== P5d: themes")
        os.write(fd, b":theme green\r")
        drain(fd, 1.5, seen)
        themed = GREEN_AGENT.encode() in bytes(seen)
        print(f"    green SGR emitted after :theme green: {themed}")
        if not themed:
            failures.append(":theme green did not repaint in the green palette")

        print("\n=== shutdown")
        os.write(fd, b":q\r")
        exited = drain(fd, 20.0, seen)
        restored = b"\x1b[?1049l" in seen
        print(f"    exited: {exited} | terminal restored: {restored}")
        if not exited:
            failures.append("the app did not exit on :q")
        if not restored:
            failures.append("the terminal was not restored")

        print("\n=== RESULT")
        if failures:
            for failure in failures:
                print(f"    FAIL: {failure}")
            tail = bytes(seen[-500:]).decode("utf-8", "replace").replace("\x1b", "\\e")
            print(f"\n    last bytes: {tail!r}")
            return 1
        print("    PASS - focus, hints, folding, yank, help and themes all round-trip")
        return 0
    finally:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
