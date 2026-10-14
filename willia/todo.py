"""Append-only planning items stored as ordinary chat records."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class Item:
    id: int
    text: str
    done: bool = False
    dropped: bool = False


def _payload(record) -> dict[str, object] | None:
    if record is None or record.kind != "todo":
        return None
    try:
        value = json.loads(record.text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def items_from_log(log) -> dict[int, Item]:
    items: dict[int, Item] = {}
    for record in log.range(0, log.count() - 1):
        value = _payload(record)
        if value is None:
            continue
        operation = value.get("op")
        if operation == "add" and isinstance(value.get("text"), str) and value["text"]:
            items[record.i] = Item(record.i, value["text"])
        elif operation in {"done", "drop"}:
            target = value.get("id")
            if type(target) is not int or target not in items:
                continue
            if operation == "done":
                items[target].done = True
            else:
                items[target].dropped = True
    return items


def _append(chat, value: dict[str, object]) -> int:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    index = chat.log.append("todo", text)
    chat.compactor.seed(index, text, "todo")
    chat.view.add_root(index)
    return index


def tool(chat, action: object, *, text: object = None, id: object = None) -> str:
    try:
        if action == "add":
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be a nonempty string")
            value = text.strip()
            index = _append(chat, {"op": "add", "text": value})
            return json.dumps({"id": index, "text": value, "done": False},
                              ensure_ascii=False)
        if action == "list":
            current = [item for item in items_from_log(chat.log).values() if not item.dropped]
            current.sort(key=lambda item: (item.done, item.id))
            return json.dumps({
                "items": [
                    {"id": item.id, "text": item.text, "done": item.done}
                    for item in current
                ]
            }, ensure_ascii=False)
        if action in {"done", "drop"}:
            if type(id) is not int or id < 0:
                raise ValueError("id must be a nonnegative integer")
            item = items_from_log(chat.log).get(id)
            if item is None or item.dropped:
                raise ValueError(f"unknown todo item: {id}")
            if action == "done" and item.done:
                raise ValueError(f"todo item is already done: {id}")
            _append(chat, {"op": action, "id": id})
            return json.dumps({action: id})
        raise ValueError("action must be add, list, done or drop")
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
