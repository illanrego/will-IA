"""Classify conversation messages into the append-only log's record kinds.

Text is split at the node budget, tool results keep their head and tail, and
reasoning never becomes memory.
"""

from __future__ import annotations

import json

from .media import MEDIA_TYPES
from .text import split_for_kind


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part["text"] for part in content
                         if isinstance(part, dict)
                         and (not isinstance(part.get("type"), str)
                              or part["type"] not in MEDIA_TYPES)
                         and isinstance(part.get("text"), str))
    return "" if content is None else str(content)


def clip_tool_output(text: str, limit: int = 30_000) -> str:
    return text[:15_000] + text[-15_000:] if len(text) > limit else text


def delegate_name(payload_text: str) -> str:
    try:
        payload = json.loads(payload_text)
    except (ValueError, TypeError):
        return "subagent"
    if isinstance(payload, dict):
        for key in ("name", "agent", "task"):
            name = payload.get(key)
            if isinstance(name, str) and name:
                return name
    return "subagent"


def classify(msg: dict, node_bytes: int,
             tool_name: str | None = None) -> list[tuple[str, str]]:
    role = msg.get("role")
    content = _content_text(msg.get("content"))
    if role == "user":
        return [("user", chunk) for chunk in split_for_kind(content, node_bytes, "user")]
    if role == "tool":
        clipped = clip_tool_output(content)
        if tool_name in {"delegate_codex", "delegate_hermes"}:
            return [("work", f"[{delegate_name(content)}] {clipped}")]
        return [("echo", clipped)]
    if role == "assistant" and msg.get("tool_calls"):
        result = []
        for call in msg["tool_calls"]:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    pass
            payload = {"name": function.get("name"), "arguments": arguments}
            if content:
                payload["content"] = content
            result.append(("tool", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))))
        return result
    if role == "assistant" and content:
        return [("will", chunk) for chunk in split_for_kind(content, node_bytes, "will")]
    return []
