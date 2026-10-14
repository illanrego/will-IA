"""Public TUI entry point and the rail's live data sources."""

from __future__ import annotations

import threading
import time
from collections import Counter
from datetime import datetime, timezone

from .. import jobs, usage
from .app import App
from .screen import Screen


def _seconds_until(value, now: datetime) -> float | None:
    if isinstance(value, (int, float)):
        target = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, str):
        try:
            target = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return (target - now).total_seconds()


def _wait_free(chat, seconds: float) -> bool:
    """Wait at most ``seconds`` for the engine; never for a whole compaction wave."""
    free = getattr(chat, "engine_free", None)
    if not callable(free):
        return True
    deadline = time.monotonic() + seconds
    while not free():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def build_rail_facts(chat, windows=None, codex_windows=None, *, now=None, blocking=True):
    """Build the layout-neutral ``(label, value, style)`` rail facts.

    With ``blocking=False`` this returns ``None`` instead of waiting while the engine is busy, so
    a frame keeps the numbers it already has rather than stalling.
    """
    now = now or datetime.now(timezone.utc)
    windows = windows or {}
    codex_windows = codex_windows or {}
    if not _wait_free(chat, 0.4 if blocking else 0.0):
        return None
    engine = getattr(chat, "engine_try", None)
    with (engine() if callable(engine) else chat._engine()) as taken:
        if taken is False:
            return None
        levels = Counter(level for level, _index in chat.tree.nodes())
        view_bytes = len(chat.view.render().encode("utf-8"))
        settled = chat.view.settled()
        unbuilt = sum(
            chat.tree.get(line.l, line.i) is None for line in chat.view.lines()
        )
        queue_depth = len(chat.compactor._pending)
    total = sum(levels.values())
    biggest = max(levels.values(), default=0)
    count_width = max((len(str(count)) for count in levels.values()), default=1)

    def level_value(count: int) -> str:
        filled = max(1, round(12 * count / biggest)) if count and biggest else 0
        bar = "█" * filled + " " * (12 - filled)
        return f"{bar} {count:>{count_width}}"

    low, high = chat.config.view_min_bytes, chat.config.view_max_bytes
    position = 0.0 if high == low else (view_bytes - low) / (high - low)
    position = max(0.0, min(1.0, position))
    marker = min(12, int(round(position * 12)))
    gauge = "─" * marker + "●" + "─" * (12 - marker)

    entries = usage.read(usage.usage_file(chat.root))
    turns = [entry for entry in entries if entry.get("kind") == "turn"]
    latest = turns[-1] if turns else {}
    input_tokens = latest.get("input_tokens", 0)
    cached_tokens = latest.get("cache_read_tokens", 0)
    cache = (f"{cached_tokens / input_tokens * 100:.1f}%"
             if type(input_tokens) is int and input_tokens > 0
             and type(cached_tokens) is int else "n/a")

    percents = []
    resets = []
    for name in usage.WINDOWS:
        window = windows.get(name)
        if isinstance(window, dict):
            percent = window.get("percent")
            percents.append(f"{percent:g}%" if isinstance(percent, (int, float)) else "?")
            resets.append(usage.countdown(_seconds_until(window.get("resetsAt"), now)))
    go = " / ".join(percents) if percents else "unavailable"
    go_reset = " / ".join(resets) if resets else "unavailable"

    codex_percents = []
    codex_resets = []
    for name in ("primary", "secondary"):
        window = codex_windows.get(name)
        if isinstance(window, dict):
            percent = window.get("percent")
            codex_percents.append(
                f"{percent:g}%" if isinstance(percent, (int, float)) else "?"
            )
            codex_resets.append(usage.countdown(window.get("resets_in_s")))
    codex = " / ".join(codex_percents) if codex_percents else "unavailable"
    codex_reset = " / ".join(codex_resets) if codex_resets else "unavailable"

    sources = {
        "#memory": ("", "dim"),
        **{f"l{level}": (level_value(levels[level]), "data")
           for level in sorted(levels)},
        "nodes": (str(total), "data"),
        "#view": ("", "dim"),
        "bytes": (f"{view_bytes:,} B", "data"),
        "64K-128K": (gauge, "data"),
        "state": (("settled" if settled else "building") + f" · {unbuilt} unbuilt",
                  "ok" if settled and not unbuilt else "amber"),
        "queue": (str(queue_depth), "data"),
        "here": (str(chat.log.count() - 1) if chat.log.count() else "none", "body"),
        "#facts": ("", "dim"),
        "session": (chat.session[:8], "body"),
        "cache": (cache, "data"),
        "jobs": (str(len(jobs.running(chat))), "body"),
        "go": (go, "data"),
        "go ↺": (go_reset, "body"),
        "codex": (codex, "data"),
        "codex ↺": (codex_reset, "body"),
        "model": (chat.config.model.model, "body"),
    }
    facts = [(label, value, style) for label, (value, style) in sources.items()]
    return facts


def run(chat) -> None:
    """Start the TUI. Nothing here may wait: a network fetch or a drain wave on the startup path
    leaves the terminal blank for as long as it takes, which is exactly how it failed once."""
    windows: dict = {}
    codex_windows: dict = {}

    def fetch_windows() -> None:
        try:
            windows.update(usage.subscription_windows(chat.config))
        except Exception:
            pass

    def fetch_codex_windows() -> None:
        try:
            codex_windows.update(usage.codex_windows())
        except Exception:
            pass

    threading.Thread(target=fetch_windows, name="willia-tui-go-usage", daemon=True).start()
    threading.Thread(
        target=fetch_codex_windows, name="willia-tui-codex-usage", daemon=True,
    ).start()
    source = lambda blocking=False: build_rail_facts(
        chat, windows, codex_windows, blocking=blocking,
    )
    App(chat, Screen(), rail_source=source, theme=chat.config.tui.theme).run()


__all__ = ["build_rail_facts", "run"]
