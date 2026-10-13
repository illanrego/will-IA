"""Probe the OpenCode Go relay's reasoning contract, and its cache reporting.

Read-only experiment: a handful of tiny chat-completions calls. Prints structure only
(never the key, never the Authorization header).
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request

BASE = "https://opencode.ai/zen/go/v1"
MODEL = "deepseek-v4.1-flash"
SESSION = "willia-probe-0001"   # x-opencode-session: opaque, stable per conversation


def key() -> str:
    for line in (pathlib.Path.home() / ".hermes" / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENCODE_GO_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no OPENCODE_GO_API_KEY in ~/.hermes/.env")


TOKEN = key()


def call(payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://willia.local", "X-Title": "will.I.A. probe",
                 "User-Agent": "willia/0.0.1", "x-opencode-session": SESSION},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(body)
        except ValueError:
            return error.code, {"raw": body[:400]}


def report(label: str, status: int, body: dict) -> None:
    print(f"\n=== {label} — HTTP {status}")
    if status != 200:
        print("   error:", json.dumps(body)[:400])
        return
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    print("   keys in message:", sorted(message))
    print("   reasoning_content present:", "reasoning_content" in message,
          "| length:", len(message.get("reasoning_content") or ""))
    print("   content:", repr((message.get("content") or "")[:60]))
    print("   finish_reason:", choice.get("finish_reason"))
    print("   usage:", json.dumps(body.get("usage") or {}))


ASK = [{"role": "user", "content": "Reply with exactly: OK"}]

report("A. no reasoning fields at all", *call({"model": MODEL, "messages": ASK}))
report("B. reasoning_effort=medium, no thinking toggle",
       *call({"model": MODEL, "messages": ASK, "reasoning_effort": "medium"}))
report("C. thinking disabled", *call({"model": MODEL, "messages": ASK,
                                      "thinking": {"type": "disabled"}}))
report("D. thinking enabled", *call({"model": MODEL, "messages": ASK,
                                     "thinking": {"type": "enabled"}}))
report("E. reasoning_effort=medium + max_tokens=16",
       *call({"model": MODEL, "messages": ASK, "reasoning_effort": "medium", "max_tokens": 16}))

# The echo question: turn 1 with thinking on, then turn 2 with and without the
# assistant's reasoning_content carried back.
status, first = call({"model": MODEL, "messages": ASK, "reasoning_effort": "high"})
report("F1. thinking on (reasoning_effort=high)", status, first)
if status == 200:
    assistant = (first.get("choices") or [{}])[0].get("message") or {}
    bare = {"role": "assistant", "content": assistant.get("content") or ""}
    echoed = dict(bare, reasoning_content=assistant.get("reasoning_content") or "")
    follow = [*ASK, bare, {"role": "user", "content": "Reply with exactly: OK again"}]
    report("F2. turn 2 WITHOUT echoing reasoning_content",
           *call({"model": MODEL, "messages": follow, "reasoning_effort": "high"}))
    follow_echo = [*ASK, echoed, {"role": "user", "content": "Reply with exactly: OK again"}]
    report("F3. turn 2 WITH reasoning_content echoed",
           *call({"model": MODEL, "messages": follow_echo, "reasoning_effort": "high"}))

# Cache reporting: the same large prefix twice, looking for cached-token accounting.
filler = ("The compaction rubric says the user's words matter most, keep them close to verbatim; "
          "then anything with lasting effect and what failed and why; then findings and open "
          "questions; then tool steps. Copy names, numbers, ids, paths and errors exactly. ") * 60
big = [{"role": "system", "content": "You write the memory. " + filler},
       {"role": "assistant", "content": "<chat>\n0+1024|" + filler[:2000] + "\n</chat>"},
       {"role": "user", "content": "Compaction: compress message 0 into one line."}]
status, one = call({"model": MODEL, "messages": big, "reasoning_effort": "medium", "max_tokens": 400})
report("G1. large prefix, first call", status, one)
status, two = call({"model": MODEL, "messages": big, "reasoning_effort": "medium", "max_tokens": 400})
report("G2. identical large prefix, second call (cache?)", status, two)
print("\n   prompt chars:", sum(len(m["content"]) for m in big))
