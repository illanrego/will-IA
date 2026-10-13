"""The usage meter: canonical buckets on disk, and the account's own windows.

Local per-call usage is appended to ``<root>/logs/usage.jsonl``, one compact JSON object per
call, using the canonical bucket names the route's usage object widens into
(`WIRE-FORMATS` section 9: `input_tokens | output_tokens | cache_read_tokens |
cache_write_tokens | reasoning_tokens`).  The bucket names are the host's own, not willia's.

The subscription windows come from the same route as the chat, and are percentages of the
account's plan, not token counts.  A window key that is absent simply does not apply.

Recording never raises into a turn: a meter that breaks a call is worse than a lost sample.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .config import Config, paths
from .envfile import opencode_go_key


_LOG = logging.getLogger(__name__)

BUCKETS: tuple[str, ...] = (
    "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    "reasoning_tokens",
)

USAGE_FILE = "usage.jsonl"
WINDOWS = ("rolling", "weekly", "monthly")
_LOCK = threading.Lock()


def _package_version() -> str:
    try:
        return version("willia")
    except PackageNotFoundError:
        return "0.0.1"


def usage_file(root: str | Path) -> Path:
    """The meter's own append-only file, beside the chat's other logs."""
    return paths(root).logs_dir / USAGE_FILE


def _first_int(*candidates: Any) -> int:
    for value in candidates:
        if type(value) is int:
            return value
    return 0


def canonical(usage: Any) -> dict[str, int]:
    """Widen one call's usage object into the five canonical buckets.

    A missing or malformed object widens to zeros rather than raising: the meter reads raw
    route output, which is not ours to trust.
    """
    if not isinstance(usage, dict):
        usage = {}
    prompt = usage.get("prompt_tokens_details")
    completion = usage.get("completion_tokens_details")
    prompt = prompt if isinstance(prompt, dict) else {}
    completion = completion if isinstance(completion, dict) else {}
    return {
        "input_tokens": _first_int(usage.get("prompt_tokens")),
        "output_tokens": _first_int(usage.get("completion_tokens")),
        "cache_read_tokens": _first_int(prompt.get("cached_tokens")),
        "cache_write_tokens": _first_int(
            prompt.get("cache_write_tokens"),
            prompt.get("cache_creation_input_tokens"),
        ),
        "reasoning_tokens": _first_int(completion.get("reasoning_tokens")),
    }


def record(root: str | Path, *, kind: str, model: str, usage: Any) -> dict | None:
    """Append one call's measured usage.  Returns the entry, or ``None`` when there was none.

    A call that reported no usage object is not a zero-token call, so it is not recorded.
    """
    if not isinstance(usage, dict) or not usage:
        return None
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "model": model,
        **canonical(usage),
    }
    path = usage_file(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with _LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
                stream.flush()
    except OSError as exc:
        _LOG.warning("Could not append to the usage meter at %s: %s", path, exc)
    return entry


def read(path: str | Path) -> list[dict]:
    """Every readable entry, oldest first; a torn or unreadable line is skipped."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        _LOG.warning("Could not read the usage meter at %s: %s", path, exc)
        return []
    entries: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def totals(entries: list[dict]) -> dict:
    """Bucket totals, the call count, and the same per call kind."""
    summary: dict = {"calls": 0, **{name: 0 for name in BUCKETS}, "by_kind": {}}
    for entry in entries:
        kind = entry.get("kind")
        if not isinstance(kind, str) or not kind:
            kind = "unknown"
        bucket = summary["by_kind"].setdefault(kind, {"calls": 0, **{name: 0 for name in BUCKETS}})
        summary["calls"] += 1
        bucket["calls"] += 1
        for name in BUCKETS:
            value = entry.get(name)
            if type(value) is int:
                summary[name] += value
                bucket[name] += value
    return summary


def subscription_windows(config: Config, *, timeout: float = 20.0,
                         key: str | None = None) -> dict:
    """The account's rolling / weekly / monthly windows, as percentages.

    Absent keys are not errors: a window that does not apply to the plan is simply missing.
    """
    request = urllib.request.Request(
        config.model.base_url.rstrip("/") + "/usage",
        headers={
            "Authorization": f"Bearer {key or opencode_go_key()}",
            "Accept": "application/json",
            "User-Agent": f"willia/{_package_version()}",
            "HTTP-Referer": config.model.referer,
            "X-Title": "will.I.A.",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", "replace"))
    windows = data.get("usage") if isinstance(data, dict) else None
    return windows if isinstance(windows, dict) else {}
