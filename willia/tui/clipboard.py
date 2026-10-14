"""Dependency-free terminal clipboard support with a bounded desktop fallback."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping


def osc52(text: str) -> str:
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"\x1b]52;c;{payload}\x07"


def copy_text(text: str, writer: Callable[[str], object], *,
              environ: Mapping[str, str] | None = None,
              which: Callable[[str], str | None] = shutil.which,
              runner: Callable[..., object] = subprocess.run) -> None:
    """Copy text without allowing either clipboard route to disrupt the TUI."""
    try:
        writer(osc52(text))
    except Exception:
        pass

    env = os.environ if environ is None else environ
    try:
        command = None
        if env.get("WAYLAND_DISPLAY"):
            executable = which("wl-copy")
            if executable:
                command = [executable]
        if command is None and env.get("DISPLAY"):
            executable = which("xclip")
            if executable:
                command = [executable, "-selection", "clipboard"]
        if command is None:
            return
        runner(
            command, input=text.encode("utf-8"), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=0.5, check=False,
        )
    except Exception:
        pass


__all__ = ["copy_text", "osc52"]
