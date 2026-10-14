"""Small, dependency-free terminal ownership layer."""

from __future__ import annotations

import os
import select
import signal
import sys
import termios
import tty
from collections.abc import Mapping

from .clipboard import copy_text
from .theme import colour_depth, sgr


ALT_ON = "\x1b[?1049h"
ALT_OFF = "\x1b[?1049l"
CURSOR_HIDE = "\x1b[?25l"
CURSOR_SHOW = "\x1b[?25h"
SYNC_ON = "\x1b[?2026h"
SYNC_OFF = "\x1b[?2026l"
CLEAR = "\x1b[H\x1b[2J"
HOME = "\x1b[H"
ERASE_BELOW = "\x1b[J"
RESET = "\x1b[0m"

_CSI = {
    b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1b[C": "RIGHT",
    b"\x1b[D": "LEFT", b"\x1b[H": "HOME", b"\x1b[F": "END",
    b"\x1b[1~": "HOME", b"\x1b[4~": "END", b"\x1b[7~": "HOME",
    b"\x1b[8~": "END", b"\x1b[5~": "PGUP", b"\x1b[6~": "PGDN",
}


def decode_key(data: bytes) -> str:
    if data in _CSI:
        return _CSI[data]
    if data == b"\r":
        return "ENTER"
    if data == b"\n":
        return "CTRL_J"
    if data == b"\x1b":
        return "ESC"
    if data == b"\t":
        return "TAB"
    if data == b"\x7f":
        return "BACKSPACE"
    if len(data) == 1 and 1 <= data[0] <= 26:
        return "CTRL_" + chr(ord("A") + data[0] - 1)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "UNKNOWN"
    return text if text.isprintable() else "UNKNOWN"


class Screen:
    def __init__(self, *, input_fd: int = 0, output_fd: int = 1, writer=None,
                 environ: Mapping[str, str] | None = None, depth: int | None = None):
        self.input_fd = input_fd
        self.output_fd = output_fd
        self.writer = writer if writer is not None else sys.stdout.write
        self.depth = colour_depth(environ) if depth is None else depth
        self.resized = False
        self.on_resize = None
        self._saved_termios = None
        self._signals: dict[int, object] = {}
        self._active = False

    def _write(self, value: str) -> None:
        target = self.writer
        if callable(target):
            target(value)
        else:
            target.write(value)
        flush = getattr(target, "flush", None)
        if flush is not None:
            flush()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def start(self) -> None:
        if self._active:
            return
        try:
            if os.isatty(self.input_fd):
                self._saved_termios = termios.tcgetattr(self.input_fd)
                tty.setraw(self.input_fd)
            self._install_signals()
            self._active = True
            self._write(ALT_ON + CURSOR_HIDE)
        except BaseException:
            try:
                if self._active:
                    self._write(ALT_OFF + CURSOR_SHOW + RESET)
            except Exception:
                pass
            finally:
                self._restore_termios()
                self._restore_signals()
                self._active = False
            raise

    def close(self) -> None:
        if not self._active and self._saved_termios is None and not self._signals:
            return
        try:
            self._write(ALT_OFF + CURSOR_SHOW + RESET)
        finally:
            self._restore_termios()
            self._restore_signals()
            self._active = False

    def _restore_termios(self) -> None:
        saved, self._saved_termios = self._saved_termios, None
        if saved is not None:
            termios.tcsetattr(self.input_fd, termios.TCSADRAIN, saved)

    def _install_signals(self) -> None:
        try:
            for number, handler in (
                (signal.SIGWINCH, self._on_winch),
                (signal.SIGTERM, self._on_term),
            ):
                self._signals[number] = signal.getsignal(number)
                signal.signal(number, handler)
        except ValueError:
            self._restore_signals()

    def _restore_signals(self) -> None:
        saved, self._signals = self._signals, {}
        for number, handler in saved.items():
            signal.signal(number, handler)

    def _on_winch(self, _signum, _frame) -> None:
        self.resized = True
        if self.on_resize is not None:
            try:
                self.on_resize()
            except Exception:
                pass

    def _on_term(self, _signum, _frame) -> None:
        self.close()
        raise SystemExit(143)

    def size(self) -> tuple[int, int]:
        size = os.get_terminal_size(self.output_fd)
        return size.columns, size.lines

    def read_key(self) -> str:
        first = os.read(self.input_fd, 1)
        if not first:
            return "EOF"
        data = first
        if first == b"\x1b":
            while select.select([self.input_fd], [], [], 0.015)[0]:
                data += os.read(self.input_fd, 1)
                if data in _CSI or (data.startswith(b"\x1b[") and data[-1:] == b"~"):
                    break
        elif first[0] >= 0xC0:
            length = 2 if first[0] < 0xE0 else 3 if first[0] < 0xF0 else 4
            while len(data) < length:
                data += os.read(self.input_fd, length - len(data))
        return decode_key(data)

    def poll_key(self, timeout: float | None = None) -> str | None:
        """Return a key if one is ready within ``timeout``, else None, so the loop can tick."""
        ready, _w, _x = select.select([self.input_fd], [], [], timeout)
        if not ready:
            return None
        return self.read_key()

    def draw(self, lines, theme="blue") -> None:
        lines = tuple(lines)
        if not lines:
            return
        # Home + erase-below, never a full clear: a clear-then-repaint flashes on some
        # terminals even when it arrives in one write, and rows are padded to the width so
        # nothing stale survives underneath. Synchronized updates keep the erase and rewrite
        # from becoming separately visible; terminals that do not implement 2026 ignore it.
        output = [SYNC_ON, HOME, ERASE_BELOW, sgr(theme, "bg", self.depth, background=True)]
        for index, line in enumerate(lines):
            if index:
                output.append("\r\n")
            spans = getattr(line, "spans", ())
            if spans:
                for span in spans:
                    output.append(sgr(
                        theme, span.background or "bg", self.depth, background=True))
                    output.extend((sgr(theme, span.style, self.depth), span.text))
            else:
                token = getattr(line, "style", "body")
                output.extend((sgr(theme, token, self.depth), getattr(line, "text", str(line))))
        output.extend((RESET, SYNC_OFF))
        self._write("".join(output))

    def copy(self, text: str) -> None:
        copy_text(text, self._write)
