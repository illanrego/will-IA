"""Line input and terminal commands for the single chat.

The reader only enqueues lines. Buffering, inbox delivery and every memory
operation stay on the main thread, including while a tool round is running.
"""

from __future__ import annotations

import queue
import sys
import threading
from collections import deque


_HELP = "/help: show commands; /status: show chat state; /quit: save and exit.\nBlank line: submit; trailing \\: continue the message."
_COMMANDS = {"/quit", "/help", "/status"}


class _Inbox(queue.Queue):
    def __init__(self):
        super().__init__()
        self.buffer: list[str] = []
        self.events: deque[tuple[str, str]] = deque()
        self.ended = False

    def _submit(self) -> None:
        if self.buffer:
            self.events.append(("message", "\n".join(self.buffer)))
            self.buffer.clear()

    def _line(self, line: str | None) -> None:
        if line is None:
            self._submit()
            self.events.append(("command", "/quit"))
            self.ended = True
            return
        line = line.rstrip("\r\n")
        if not self.buffer and line in _COMMANDS:
            self.events.append(("command", line))
            if line == "/quit":
                self.ended = True
        elif not line:
            self._submit()
        else:
            if line.endswith("\\") and not line.endswith("\\\\"):
                line = line[:-1]
            self.buffer.append(line)

    def next_event(self) -> tuple[str, str]:
        while not self.events:
            self._line(self.get())
        return self.events.popleft()

    def drain_messages(self) -> list[str]:
        while not self.ended:
            try:
                self._line(self.get_nowait())
            except queue.Empty:
                break
        messages = [text for kind, text in self.events if kind == "message"]
        self.events = deque(event for event in self.events if event[0] != "message")
        return messages


def _read(stream, inbox: _Inbox) -> None:
    try:
        for line in stream:
            inbox.put(line)
    finally:
        inbox.put(None)


def run(chat) -> None:
    inbox = _Inbox()
    chat.inbox = inbox
    reader = threading.Thread(target=_read, args=(sys.stdin, inbox), daemon=True,
                              name="willia-input")
    reader.start()
    print("will.I.A. — blank line to submit; /help for commands.", flush=True)
    try:
        while True:
            kind, text = inbox.next_event()
            if kind == "message":
                chat.turn([text])
            elif text == "/quit":
                break
            elif text == "/help":
                print(_HELP, flush=True)
            elif text == "/status":
                print("\n".join(chat.status()), flush=True)
    except KeyboardInterrupt:
        print(flush=True)
    finally:
        chat.close()
        print("Goodbye. Chat saved.", flush=True)
