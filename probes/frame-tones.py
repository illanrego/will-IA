"""Report the tone each part of the frame is drawn in, so 'too white' is measurable.

For every line of the frame, collect the style tokens it actually uses (from its spans, falling
back to the line's own style), resolve them to the palette's hex, and group by the block it belongs
to. Then report the field's brightness mix: what share of the lane is the brightest tokens.
"""

from __future__ import annotations

import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path.home() / "Documents/coding/willia"))

import importlib.util                                     # noqa: E402

from willia.tui import theme as theme_mod                 # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "frame_text", pathlib.Path(__file__).with_name("frame-text.py"))
harness = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(harness)


def luminance(hex_colour: str) -> float:
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def tokens_of(line) -> list[str]:
    found = [span.style for span in (getattr(line, "spans", None) or []) if span.style]
    return found or [line.style]


def describe(app, palette: dict[str, str]) -> None:
    lines = app._frame()
    seen: collections.Counter[str] = collections.Counter()
    for line in lines:
        for token in tokens_of(line):
            seen[token] += 1
    print(f"    tokens in use: {dict(seen)}")
    bg = luminance(palette["bg"])
    ranked = sorted((luminance(palette[t]) for t in seen if t in palette), reverse=True)
    if ranked:
        print(f"    brightest token in the lane: {ranked[0]:.4f} vs bg {bg:.4f}")


# The token *usage* is theme independent; each palette is measured on its own.
print("=== the lane's tones")
describe(harness.app, theme_mod.PALETTES["blue"])

for name in ("blue", "green", "mixed"):
    palette = theme_mod.PALETTES[name]
    bright = {t: round(luminance(palette[t]), 3) for t in ("you", "body", "data", "reason", "dim")}
    print(f"  {name:6} " + "  ".join(f"{t} {v:.3f}" for t, v in bright.items()))

print("\n=== the labels and the lane's tones (blue)")
palette = theme_mod.PALETTES["blue"]
for line in harness.app._frame():
    text = line.text.strip()
    if not text:
        continue
    marks = {token: palette.get(token, "?") for token in tokens_of(line)}
    if set(marks) - {"body"}:
        print(f"    {text[:34]!r:38} {marks}")
