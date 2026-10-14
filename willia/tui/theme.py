"""The measured TUI palettes and their ANSI colour encodings."""

from __future__ import annotations

import os
from collections.abc import Mapping


TOKENS = (
    "bg", "panel", "rule", "rule_strong", "body", "dim", "reason",
    "agent", "data", "amber", "red", "ok", "you", "strong",
)

PALETTES: dict[str, dict[str, str]] = {
    "blue": {
        "bg": "#06090F", "panel": "#0A101B", "rule": "#1D2631",
        "rule_strong": "#374C5D", "body": "#C6D6EA", "dim": "#7E8DA6",
        "reason": "#8E9DB6", "agent": "#63CCFF", "data": "#63CCFF",
        "amber": "#FFB44D", "red": "#FF5A60", "ok": "#5FE8B8",
        "you": "#D8E6FA", "strong": "#E8F2FF",
    },
    "green": {
        "bg": "#050A09", "panel": "#081412", "rule": "#192C24",
        "rule_strong": "#305747", "body": "#C2E3D4", "dim": "#7B948B",
        "reason": "#8AA69C", "agent": "#4FE0A2", "data": "#4FE0A2",
        "amber": "#E8BE55", "red": "#FF5A60", "ok": "#9FD4FF",
        "you": "#DCF2E6", "strong": "#E6FBEF",
    },
    "mixed": {
        "bg": "#06090F", "panel": "#0A101B", "rule": "#1E2834",
        "rule_strong": "#374C5D", "body": "#C6D6EA", "dim": "#7E8DA6",
        "reason": "#8E9DB6", "agent": "#63CCFF", "data": "#4FE0A2",
        "amber": "#FFB44D", "red": "#FF5A60", "ok": "#4FE0A2",
        "you": "#D8E6FA", "strong": "#E8F2FF",
    },
}


def palette(value: str | Mapping[str, str]) -> Mapping[str, str]:
    if isinstance(value, str):
        return PALETTES[value]
    if set(value) != set(TOKENS):
        raise ValueError("A TUI palette must define exactly the 14 style tokens")
    return value


def colour_depth(environ: Mapping[str, str] | None = None) -> int:
    """Return 24, 256 or 8 for the terminal advertised by the environment."""
    env = os.environ if environ is None else environ
    colorterm = env.get("COLORTERM", "").lower()
    if "truecolor" in colorterm or "24bit" in colorterm:
        return 24
    if "256color" in env.get("TERM", "").lower():
        return 256
    return 8


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _xterm_palette() -> list[tuple[int, int, int]]:
    basic = [
        (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
        (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
        (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
        (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
    ]
    steps = (0, 95, 135, 175, 215, 255)
    cube = [(red, green, blue) for red in steps for green in steps for blue in steps]
    gray = [(8 + 10 * index,) * 3 for index in range(24)]
    return basic + cube + gray


_XTERM = _xterm_palette()
_BASIC = _XTERM[:8]


def _nearest(rgb: tuple[int, int, int], colours: list[tuple[int, int, int]]) -> int:
    return min(range(len(colours)), key=lambda index: sum(
        (rgb[channel] - colours[index][channel]) ** 2 for channel in range(3)
    ))


def ansi_colour(value: str, depth: int, *, background: bool = False) -> str:
    """Encode one exact hex colour for truecolour, xterm-256 or ANSI-8."""
    red, green, blue = _rgb(value)
    if depth == 24:
        return f"\x1b[{'48' if background else '38'};2;{red};{green};{blue}m"
    if depth == 256:
        index = _nearest((red, green, blue), _XTERM)
        return f"\x1b[{'48' if background else '38'};5;{index}m"
    if depth == 8:
        index = _nearest((red, green, blue), _BASIC)
        return f"\x1b[{40 + index if background else 30 + index}m"
    raise ValueError("Colour depth must be 24, 256 or 8")


def sgr(theme: str | Mapping[str, str], token: str, depth: int,
        *, background: bool = False) -> str:
    colours = palette(theme)
    return ansi_colour(colours[token], depth, background=background)
