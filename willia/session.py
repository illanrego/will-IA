"""Durable identity for the one upstream chat route.

The stored opaque value pins every turn and compaction to the same backend, so
an existing identity is validated and reused rather than silently replaced.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path


_LOCK = threading.Lock()


def _read(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("session"), str):
        raise ValueError(f"Malformed session file: {path}")
    value = data["session"]
    if not value:
        raise ValueError(f"Malformed session file: {path}")
    return value


def session_id(root: str | os.PathLike[str]) -> str:
    """Read the chat's session id, or atomically create it exactly once."""
    directory = Path(root).expanduser()
    path = directory / "session.json"
    with _LOCK:
        if path.exists():
            return _read(path)
        value = uuid.uuid4().hex
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, prefix=".session.",
                suffix=".tmp", delete=False,
            ) as handle:
                temporary = handle.name
                json.dump({"session": value}, handle, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return value
