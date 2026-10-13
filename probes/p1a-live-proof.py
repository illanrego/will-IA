"""P1a acceptance (run by the session, not the delegate): real calls through our client.

1. one live turn, with the fixed prefix, and the usage keys the meter will read
2. the same prefix again, to see cached_tokens move
3. one live compaction, driven by the vendored Compactor with the client as its summarizer -
   a real node built by a real model call, through the envelope the design specifies
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path.home() / "Documents/coding/willia"
sys.path.insert(0, str(REPO))

from willia import prompts, toolkit                      # noqa: E402
from willia.client import Client                         # noqa: E402
from willia.compactor import Compactor                   # noqa: E402
from willia.config import Config                         # noqa: E402
from willia.session import session_id                    # noqa: E402
from willia.tree import Tree                             # noqa: E402
from willia.view import View                             # noqa: E402

def cached(reply) -> object:
    return (reply.usage.get("prompt_tokens_details") or {}).get("cached_tokens")

def main() -> int:
    config = Config.load()
    root = pathlib.Path(config.root)
    root.mkdir(parents=True, exist_ok=True)
    session = session_id(root)
    real = Client(config, session)
    seen: list[dict] = []

    def recording(url, headers, payload, timeout):
        # The compaction is non-streaming, so its usage rides the single body we capture here.
        lines = list(real._transport(url, headers, payload, timeout))
        try:
            body = json.loads("".join(
                line.decode("utf-8") if isinstance(line, bytes) else line for line in lines))
            seen.append({"usage": body.get("usage") or {}, "stream": bool(payload.get("stream")),
                         "thinking": payload.get("thinking")})
        except (ValueError, TypeError):
            pass
        return iter(lines)

    client = Client(config, session, transport=recording)
    system = prompts.build_system_prompt(prompts.default_instructions())
    tools = toolkit.schemas()
    print(f"session       {session[:8]}...  (stored at {config.session_file})")
    print(f"fixed prefix  {len(system.encode())} bytes of prompt + "
          f"{len(str(tools).encode())} bytes of schemas\n")

    ask = [{"role": "system", "content": system},
           {"role": "user", "content": "Reply with exactly: OK"}]
    first = client.turn(ask, tools)
    print(f"turn 1  content={first.content[:20]!r} finish={first.finish_reason}")
    print(f"        usage={first.usage}")
    print(f"        reasoning captured but never logged: {len(first.reasoning)} chars")

    second = client.turn(ask, tools)
    print(f"turn 2  cached_tokens={cached(second)} of {second.usage.get('prompt_tokens')}"
          f"  (the same pinned session id, the same prefix)\n")

    # The compaction through the design's own path: Compactor -> client.summarize.
    work = pathlib.Path(tempfile.mkdtemp(prefix="willia-p1a-"))
    try:
        node_tree = Tree(work, node_bytes=512)
        view = View(node_tree)
        compactor = Compactor(node_tree, client.summarize, node_bytes=512, view=view)
        compactor.system = system          # the turn's system prompt, byte-identical
        compactor.tools = tools            # the turn's schemas, byte-identical
        source = (
            "The recipe says the view is a sawtooth: each new message appends its line and "
            "nothing else changes, until the view passes 128,000 bytes, when one batch merges "
            "the most due pairs down to 64,000 bytes. A pair's age is measured from its last "
            "message: due = (T - last) / 2^l. Measuring from the first message is the classic "
            "mistake: it matched the reference push at only 481 of 20,001 steps. The view is "
            "saved to view.json and loaded at start, never rebuilt, because a rebuilt view is a "
            "different state and every cache entry dies with it."
        )
        index = 0
        compactor.seed(index, source, "user")
        view.add_root(index)
        built = compactor.run_pending(limit=1)
        line = node_tree.get(0, 0)
        print(f"compaction  built={built} node(0,0)={None if line is None else str(len(line.text.encode())) + ' bytes'}")
        if line is not None:
            print(f"        line: {line.text[:220]}")
            print(f"        over 512 bytes: {len(line.text.encode()) > 512}")
        node_tree.save()
        view.save()
        if seen:
            last = seen[-1]
            details = (last["usage"].get("prompt_tokens_details") or {})
            print(f"        compaction usage: prompt={last['usage'].get('prompt_tokens')} "
                  f"cached={details.get('cached_tokens')} "
                  f"reasoning={((last['usage'].get('completion_tokens_details') or {}).get('reasoning_tokens'))} "
                  f"stream={last['stream']} thinking={last['thinking']}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
