"""Read-only access to raw messages and built summary children."""

from __future__ import annotations

import json
from pathlib import Path

from .media import media_for
from .store import Log
from .tree import Tree
from .view import View


def _error(message: str) -> str:
    return json.dumps({"error": message})


def child_chat_dir(root: Path, name: object) -> Path | None:
    """The chat directory a child's name names, or ``None`` when the name is unsafe.

    A child is a directory under ``<root>/agents/`` whose name is the label the
    delegate was created with (the recipe's ``zoom("Name")``). The name must be a
    single safe path component: an empty name, a separator, an absolute path, or a
    dot segment is refused. Whether the chat exists is the caller's check.
    """
    if not isinstance(name, str) or not name or name in (".", ".."):
        return None
    if Path(name).name != name or "/" in name or "\\" in name:
        return None
    return Path(root) / "agents" / name


def zoom(log: Log, tree: Tree, view: View | None, id: int | str, n: int = 1,
         *, scope: str | None = None, master_root: Path | None = None) -> str:
    """Open a child chat, a named span, or a raw message.

    ``scope`` names the chat the ids belong to: ``None`` for the log this call was
    given (the view the caller is reading), or a child's name. The engine resolves
    and validates a scope before calling; here it only labels the payload, so the
    caller can open a line in the same scope again. ``view`` is unused by the
    span and message paths and may be ``None``.

    """
    if isinstance(id, str):
        root = Path(master_root) if master_root is not None else log.root
        child_root = child_chat_dir(root, id)
        if child_root is None:
            return _error("unknown subagent name")
        if not (child_root / "view.json").is_file():
            return _error("subagent chat does not exist")
        try:
            child_view = View(Tree(child_root, read_only=True))
            return json.dumps({"name": id, "scope": id, "chat": child_view.render()},
                              ensure_ascii=False)
        except (OSError, ValueError, TypeError):
            return _error("unknown subagent name")
    if type(id) is not int or type(n) is not int or id < 0 or n < 1:
        return _error("id must be a string or nonnegative integer; n must be a positive integer")
    if n & (n - 1):
        return _error("n must be a power of two")
    if id % n:
        return _error("id must be a multiple of n")
    if n == 1:
        record = log.get(id)
        if record is None:
            return _error("message does not exist")
        payload = {"id": id, "n": 1, "kind": record.kind, "scope": scope,
                   "text": record.text, "media": media_for(log.root, id)}
        return json.dumps(payload, ensure_ascii=False)

    # A named node covers [id, id+n). Both children must have been built.
    if id + n > log.count():
        return _error("span does not exist")
    level = n.bit_length() - 2
    if tree.get(level + 1, id // n) is None:
        return _error("span is not summarized yet")
    children = [tree.get(level, id // (n // 2)),
                tree.get(level, id // (n // 2) + 1)]
    if any(line is None for line in children):
        return _error("span is not summarized yet")
    halves = [{"id": id + offset, "n": n // 2, "text": line.text}
              for offset, line in zip((0, n // 2), children)]
    return json.dumps({"id": id, "n": n, "scope": scope, "halves": halves}, ensure_ascii=False)


def date(log: Log, id: int, *, scope: str | None = None) -> str:
    """Return the stored ISO timestamp for a raw message in the named scope."""
    if type(id) is not int or id < 0:
        return _error("id must be a nonnegative integer")
    record = log.get(id)
    if record is None:
        return _error("message does not exist")
    return json.dumps({"id": id, "date": record.date, "scope": scope})
