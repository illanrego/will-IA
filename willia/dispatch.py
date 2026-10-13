"""Route the fixed tool registry to memory navigation or explicit placeholders.

Foreign chats are opened read-only, and tool failures remain JSON results so a
single failed navigation never interrupts the conversation.
"""

from __future__ import annotations

import json

from . import tools
from .store import Log
from .tree import Tree


_UNIMPLEMENTED = {"delegate_codex", "delegate_hermes", "web_search", "web_extract", "vision"}


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def dispatch(name: str, arguments: object, *, log, tree, view, root,
             node_bytes: int) -> str:
    try:
        if name in _UNIMPLEMENTED:
            return _error(f"not implemented yet: {name}")
        if name not in {"zoom", "date"}:
            return _error(f"unknown tool: {name}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            return _error("arguments must be a JSON object")
        scope = arguments.get("scope")
        if "scope" in arguments and (not isinstance(scope, str) or not scope):
            return _error("scope must be a nonempty subagent name")
        id = arguments.get("id")
        n = arguments.get("n", 1)
        if name == "zoom" and isinstance(id, str) and scope is not None:
            return _error("a string id opens its own chat; do not pass scope with it")
        if scope is not None:
            child_root = tools.child_chat_dir(root, scope)
            if child_root is None:
                return _error(f"unknown scope: '{scope}'")
            if not (child_root / "view.json").is_file():
                return _error(f"scope '{scope}' has no chat")
            try:
                with Log(child_root, read_only=True) as child_log:
                    if name == "date":
                        return tools.date(child_log, id, scope=scope)
                    child_tree = Tree(child_root, node_bytes, read_only=True)
                    return tools.zoom(child_log, child_tree, None, id, n, scope=scope)
            except Exception as exc:
                return _error(f"scope '{scope}' cannot be read: {exc}")
        if name == "zoom":
            return tools.zoom(log, tree, view, id, n, master_root=root)
        return tools.date(log, id)
    except Exception as exc:
        return _error(str(exc))
