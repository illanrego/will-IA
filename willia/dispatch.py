"""Route the fixed tool registry to navigation or background delegates.

Foreign chats are opened read-only, and tool failures remain JSON results so a
single failed navigation never interrupts the conversation.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import jobs, toolkit, tools
from .store import Log
from .tree import Tree


_UNIMPLEMENTED = {"web_search", "web_extract", "vision"}
_DELEGATES = {"delegate_codex": "codex", "delegate_hermes": "hermes"}


def _codex_models() -> frozenset[str]:
    for schema in toolkit.schemas():
        function = schema.get("function", {})
        if function.get("name") == "delegate_codex":
            values = function["parameters"]["properties"]["model"]["enum"]
            return frozenset(values)
    raise RuntimeError("delegate_codex schema is absent")


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def dispatch(name: str, arguments: object, *, log, tree, view, root,
             node_bytes: int, chat=None, command: list[str] | None = None) -> str:
    try:
        if name in _UNIMPLEMENTED:
            return _error(f"not implemented yet: {name}")
        # P1 callers can still exercise the frozen placeholder without an owning
        # Chat.  A live delegate needs that owner for publication and delivery.
        if name in _DELEGATES and chat is None:
            return _error(f"not implemented yet: {name}")
        if name not in {"zoom", "date", *_DELEGATES}:
            return _error(f"unknown tool: {name}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            return _error("arguments must be a JSON object")
        if name in _DELEGATES:
            task = arguments.get("task")
            if not isinstance(task, str) or not task.strip():
                return _error("task must be a nonempty string")
            allowed = {"task", "name"}
            if name == "delegate_codex":
                allowed.update(("dir", "model"))
            extras = set(arguments) - allowed
            if extras:
                return _error(f"unexpected argument: {sorted(extras)[0]}")
            requested = arguments.get("name", _DELEGATES[name])
            if tools.child_chat_dir(root, requested) is None:
                return _error("name must be a safe single path component")

            model = arguments.get("model")
            if name == "delegate_codex" and "model" in arguments:
                if not isinstance(model, str) or model not in _codex_models():
                    return _error(
                        "model must be one of: " + ", ".join(sorted(_codex_models())))
            directory = None
            if name == "delegate_codex":
                raw_directory = arguments.get("dir", chat.config.delegates.codex.dir)
                if not isinstance(raw_directory, str) or not raw_directory:
                    return _error("dir must be an absolute directory path")
                directory = Path(raw_directory).expanduser()
                if not directory.is_absolute():
                    return _error("dir must be an absolute directory path")
            elif command is not None:
                directory = Path(root).resolve()
            timeout_s = (
                chat.config.delegates.codex.timeout_minutes
                if name == "delegate_codex"
                else chat.config.delegates.hermes.timeout_minutes
            ) * 60
            job = jobs.spawn(
                chat=chat, name=requested, agent=_DELEGATES[name], brief=task,
                directory=directory, model=model, timeout_s=timeout_s,
                command=command,
            )
            return json.dumps({
                "status": "started", "name": job.label, "agent": job.agent,
                "report_path": str(job.report_path.resolve()),
            }, ensure_ascii=False)
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
