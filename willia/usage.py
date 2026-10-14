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
import math
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


class CodexUsageError(RuntimeError):
    """A safe-to-display failure while reading the Codex account's usage."""


class CodexAuthMissingError(CodexUsageError):
    """The read-only Codex credential file or one of its credentials is absent."""


class CodexTokenExpiredError(CodexUsageError):
    """The Codex service rejected the stored access token."""


class CodexNetworkError(CodexUsageError):
    """The Codex usage endpoint could not be reached."""


class CodexResponseError(CodexUsageError):
    """The Codex usage endpoint returned an unreadable response."""


def _package_version() -> str:
    try:
        return version("willia")
    except PackageNotFoundError:
        return "0.0.1"


def usage_file(root: str | Path) -> Path:
    """The meter's own append-only file, beside the chat's other logs."""
    return paths(root).logs_dir / USAGE_FILE


def countdown(seconds: Any) -> str:
    """Render a nonnegative duration using the usage surfaces' compact form."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return "?"
    if not math.isfinite(seconds):
        return "?"
    remaining = max(0, int(seconds))
    days, remaining = divmod(remaining, 86_400)
    hours, remaining = divmod(remaining, 3_600)
    minutes = remaining // 60
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


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


def _codex_window(raw: Any, label: str) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    percent = raw.get("used_percent")
    resets_in_s = raw.get("reset_after_seconds")
    return {
        "label": label,
        "percent": percent if isinstance(percent, (int, float)) and not isinstance(percent, bool)
        else None,
        "resets_in_s": (
            resets_in_s
            if isinstance(resets_in_s, (int, float)) and not isinstance(resets_in_s, bool)
            else None
        ),
    }


def codex_windows(*, base: str = "https://chatgpt.com/backend-api/codex",
                  auth_file: str | Path | None = None, timeout: float = 20.0) -> dict:
    """Read and normalize the Codex account's plan windows without changing its auth.

    The credential is read once from ``~/.codex/auth.json``.  This function never refreshes it,
    writes it, or includes credential or account data in an exception.
    """
    auth_path = Path(auth_file) if auth_file is not None else Path.home() / ".codex" / "auth.json"
    try:
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CodexAuthMissingError("Codex auth file is absent") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CodexAuthMissingError("Codex auth file is unavailable") from exc

    tokens = auth.get("tokens") if isinstance(auth, dict) else None
    access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
    account_id = tokens.get("account_id") if isinstance(tokens, dict) else None
    if not isinstance(access_token, str) or not access_token:
        raise CodexAuthMissingError("Codex auth file has no access token")
    if not isinstance(account_id, str) or not account_id:
        raise CodexAuthMissingError("Codex auth file has no account id")

    root = base.rstrip("/")
    if root.endswith("/codex"):
        root = root[:-len("/codex")]
    path = "/wham" if "/backend-api" in root else "/api/codex"
    request = urllib.request.Request(
        root + path + "/usage",
        headers={
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id,
            "Accept": "application/json",
            "User-Agent": f"willia/{_package_version()}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise CodexTokenExpiredError("Codex token expired (HTTP 401)") from exc
        raise CodexNetworkError(f"Codex usage network failure (HTTP {exc.code})") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CodexNetworkError("Codex usage network failure") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CodexResponseError("Codex usage response was invalid") from exc

    data = data if isinstance(data, dict) else {}
    rate_limit = data.get("rate_limit")
    rate_limit = rate_limit if isinstance(rate_limit, dict) else {}
    model_usage = data.get("model_usage")
    model_usage = model_usage if isinstance(model_usage, dict) else {}
    astra = model_usage.get("gpt-6-astra")
    astra = astra if isinstance(astra, dict) else {}
    reset_credits = data.get("rate_limit_reset_credits")
    reset_credits = reset_credits if isinstance(reset_credits, dict) else {}
    plan = data.get("plan_type")
    credits = reset_credits.get("available_count")
    available = astra.get("available")
    return {
        "plan": plan if isinstance(plan, str) else None,
        "primary": _codex_window(rate_limit.get("primary_window"), "5h"),
        "secondary": _codex_window(rate_limit.get("secondary_window"), "7d"),
        "reset_credits": credits if type(credits) is int else None,
        "astra_available": available if type(available) is bool else None,
    }
