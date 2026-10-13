"""Measure one thing: does the OpenCode Go relay accept a multimodal user message?

Illan's call (2026-10-13) is that `vision` runs on the Go route with `deepseek-v4.1-flash`
rather than OpenRouter.  The wire notes say the relay restricts **tool** message content and
400s on block-array content, so this is a fact to measure, not to reason about.

The image is built here with the stdlib alone (a solid red 64x64 PNG), so a correct answer is
unambiguous evidence that the bytes arrived at a model that could see them.
"""

from __future__ import annotations

import base64
import json
import pathlib
import struct
import sys
import urllib.error
import urllib.request
import zlib

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia.envfile import opencode_go_key      # noqa: E402
from willia.session import session_id           # noqa: E402

URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "deepseek-v4.1-flash"
QUESTION = "What single solid colour fills this image? Answer with one word."


def png_solid(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolour RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def post(payload: dict) -> tuple[int | None, str]:
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {opencode_go_key()}",
            "Content-Type": "application/json",
            "User-Agent": "willia/0.0.1",
            "HTTP-Referer": "https://github.com/illanrego/will-IA",
            "X-Title": "will.I.A.",
            "x-opencode-session": session_id(pathlib.Path.home() / ".willia"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - the measurement is the point
        return None, f"{type(exc).__name__}: {exc}"


def main() -> int:
    image = png_solid(64, 64, (255, 0, 0))
    data_url = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    print(f"built a {len(image)}-byte solid-red PNG; data URL {len(data_url)} chars")

    variants = {
        "text then image": [
            {"type": "text", "text": QUESTION},
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
        "image then text": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": QUESTION},
        ],
    }
    for label, content in variants.items():
        status, body = post({
            "model": MODEL, "stream": False,
            "messages": [{"role": "user", "content": content}],
        })
        print(f"\n=== {label}: HTTP {status}")
        print(f"    {body[:900]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
