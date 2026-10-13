"""P2b acceptance (run by the session): the three native tools, for real.

Goes through ``dispatch`` with a real ``Chat``, so it exercises the shipped routing and the
real route.  A throwaway ``WILLIA_HOME`` keeps ``~/.willia`` untouched.

  1. web_search returns real results (title / url / description) via ddgs
  2. web_extract returns one text entry per URL, in order
  3. vision answers a question about a real local image on the Go route, and the image is
     archived under the id of the record that carried the call
  4. a failure is a JSON error, never an exception
"""

from __future__ import annotations

import json
import os
import pathlib
import struct
import sys
import tempfile
import zlib

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia.chat import Chat                # noqa: E402
from willia.config import Config            # noqa: E402
from willia.dispatch import dispatch        # noqa: E402
from willia import media                    # noqa: E402

QUESTION = "What single solid colour fills this image? Answer with one word."


def png_solid(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main() -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="willia-p2b-root-"))
    image = root / "red.png"
    image.write_bytes(png_solid(64, 64, (255, 0, 0)))
    os.environ["WILLIA_HOME"] = str(root)
    chat = Chat.open(Config.load())
    failures: list[str] = []

    def call(name: str, arguments: dict) -> dict:
        return json.loads(dispatch(
            name, arguments, log=chat.log, tree=chat.tree, view=chat.view,
            root=chat.root, node_bytes=chat.config.node_bytes, chat=chat,
        ))

    print(f"throwaway root: {root}")
    try:
        print("\n=== web_search")
        found = call("web_search", {"query": "Taelin OptChat UniiChat design", "limit": 3})
        if "error" in found:
            failures.append(f"web_search: {found['error']}")
            print(f"    ERROR {found['error']}")
        else:
            results = found.get("results", [])
            print(f"    {len(results)} result(s)")
            for item in results[:3]:
                print(f"      {item.get('title')!r} {item.get('url')}")
            if not results:
                failures.append("web_search returned no results")
            elif not all(isinstance(item.get("url"), str) for item in results):
                failures.append("a search result has no url")

        print("\n=== web_extract")
        pages = call("web_extract", {"urls": ["https://example.com"]})
        if "error" in pages:
            failures.append(f"web_extract: {pages['error']}")
            print(f"    ERROR {pages['error']}")
        else:
            entries = pages.get("results", [])
            print(f"    {len(entries)} entry(ies)")
            for entry in entries:
                body = entry.get("content") or ""
                print(f"      url={entry.get('url')} error={entry.get('error')!r} "
                      f"chars={len(body)} head={body[:70]!r}")
            if len(entries) != 1:
                failures.append(f"web_extract returned {len(entries)} entries for 1 URL")
            elif not entries[0].get("content"):
                failures.append(f"web_extract returned no content: {entries[0].get('error')!r}")

        print("\n=== web_extract with one bad URL (the good one must survive)")
        mixed = call("web_extract", {"urls": ["https://example.com",
                                              "https://nonexistent.invalid/x"]})
        entries = mixed.get("results", [])
        for entry in entries:
            print(f"      url={entry.get('url')} error={entry.get('error')!r} "
                  f"chars={len(entry.get('content') or '')}")
        if len(entries) != 2:
            failures.append("the mixed extract did not return two entries")
        elif not entries[0].get("content") or not entries[1].get("error"):
            failures.append("the mixed extract dropped the good entry or the bad one's error")

        print("\n=== vision (a real local image, on the Go route)")
        # The call is made through a turn-sized path so the record carrying it exists.
        chat.log.append("tool", json.dumps(
            {"name": "vision", "arguments": {"image_url": str(image), "question": QUESTION}},
            ensure_ascii=False))
        carried = chat.log.count() - 1
        seen = call("vision", {"image_url": str(image), "question": QUESTION})
        print(f"    answer={seen.get('answer')!r} source={seen.get('source')!r} "
              f"error={seen.get('error')!r}")
        if "error" in seen:
            failures.append(f"vision: {seen['error']}")
        else:
            answer = (seen.get("answer") or "").lower()
            if "red" not in answer:
                failures.append(f"vision did not identify the colour: {seen.get('answer')!r}")
            if seen.get("source") != str(image):
                failures.append("vision did not echo its source")
            archived = media.media_for(chat.root, carried)
            print(f"    archived under id {carried}: {archived}")
            if not archived:
                failures.append("the local image was not archived under the calling record")

        print("\n=== a failure is a JSON error, never an exception")
        missing = call("vision", {"image_url": str(root / "absent.png"), "question": QUESTION})
        print(f"    {missing}")
        if "error" not in missing:
            failures.append("a missing image did not return a JSON error")

        print("\n=== RESULT")
        if failures:
            for failure in failures:
                print(f"    FAIL: {failure}")
            return 1
        print("    PASS - search, extract and vision all round-trip for real")
        return 0
    finally:
        chat.close()
        print(f"\n(evidence kept: {root})")


if __name__ == "__main__":
    raise SystemExit(main())
