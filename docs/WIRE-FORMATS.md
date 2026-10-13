# WIRE-FORMATS.md — every shape that crosses a boundary

Nine boundaries exist; each has exactly one shape here. Anything not in this file is not a
boundary. `[VERIFY in P1]` marks a field that must be confirmed against a live call before the
code that depends on it is trusted.

## 1. OpenCode Go — the chat route

Verified from the live host profile
(`plugins/model-providers/opencode-zen/__init__.py`, `class OpenCodeGoProfile`) and
`~/.hermes/config.yaml`:

| Item | Value |
|---|---|
| base URL | `https://opencode.ai/zen/go/v1` |
| API mode | `chat_completions` (OpenAI-compatible JSON) |
| credential | `OPENCODE_GO_API_KEY` (read from `~/.hermes/.env`) |
| default model | `deepseek-v4.1-flash` (also listed: `deepseek-v4-flash`, `deepseek-v4-flash-vision-exp`, `deepseek-flash`, `deepseek-v4-pro`) |
| chat endpoint | `POST {base}/chat/completions` |
| model listing | `GET {base}/models` |
| usage windows | `GET https://opencode.ai/zen/go/v1/usage` (literal `/v1`, not the runtime base) |
| headers | `Authorization: Bearer $OPENCODE_GO_API_KEY`, `Content-Type: application/json`, plus attribution: `HTTP-Referer: https://hermes-agent.nousresearch.com`, `X-Title: <app name>`, `User-Agent: <app>/<version>` |

**Request body (turns and compactions):**

```json
{
  "model": "deepseek-v4.1-flash",
  "messages": [ {"role": "system", "content": "..."},
                {"role": "assistant", "content": "<chat>\n...</chat>"},
                {"role": "user", "content": "..."} ],
  "tools": [ {"type": "function", "function": {"name": "...", "description": "...",
                                                "parameters": {...}}} ],
  "stream": true,
  "stream_options": {"include_usage": true}
}
```

- `messages[].content` is a **plain string** on this route. Never a list of parts: the Go relay
  rejects list-type content in tool messages and 400/422s (`supports_vision_tool_messages=False`
  on the profile; the rejected row stays in history and poisons every later call). This is also
  why v1 adds no cache breakpoints (`ENGINE.md` §5.4).
- **Every request carries a timeout** (turn ≈120 s, compaction ≈60 s): the client owns it, because
  the vendored compactor has none and a hung call would park a drain thread indefinitely
  (`LOOP.md` §7).
- **Reasoning knobs (DeepSeek v4 family on Go).** Copied from
  `agent/reasoning_effort.thinking_toggle_extras(reasoning_config, DEEPSEEK_V4_EFFORTS, DEEPSEEK_V4_OVERRIDES)`:
  `DEEPSEEK_V4_EFFORTS = ("low","medium","high","max")`, `DEEPSEEK_V4_OVERRIDES = {"xhigh":"max"}`.
  - a mapped effort → top-level `"reasoning_effort": "<low|medium|high|max>"`
  - `enabled: false` → body `"thinking": {"type": "disabled"}`
  - anything unmappable → body `"thinking": {"type": "enabled"}`
  The host comment adds that DeepSeek wants the toggle on **every** request (omitting it defaults
  thinking on and then demands `reasoning_content` echoes). willia pins **one** form once,
  verifies it live in P1, and never varies it per turn (a varying knob is a varying prefix — the
  cache rule, §3.3). `[VERIFY in P1]`
- `max_tokens` is **not** sent unless a budget is chosen; the relay's own default is 262,144, and
  a per-model cap exists for one model only. `[VERIFY in P1]`

**Response (non-streaming):** standard chat completion —
`choices[0].message.{role, content, tool_calls[], reasoning_content?}`,
`choices[0].finish_reason` (`stop` / `tool_calls` / `length`),
`usage.{prompt_tokens, completion_tokens, total_tokens, prompt_tokens_details.*}`.
`[VERIFY in P1]` the exact `prompt_tokens_details` keys the Go relay returns for DeepSeek cache
hits; the usage meter depends on it, so P1 captures one raw response and this doc is corrected
with the real keys.

**Streaming:** SSE, `data: {json}` lines, `data: [DONE]`. Deltas carry
`choices[0].delta.{content?, reasoning_content?}` and, for tool calls, indexed fragments
`choices[0].delta.tool_calls[{index, id?, function:{name?, arguments?}}]` that must be
concatenated by index. `include_usage` makes a **final chunk carry `usage`** (and `choices: []`),
which is the provider's own "finished" signal.

**Tool calls (the loop's rules):** the model may emit several calls in one assistant message; each
call is logged as one `tool` record (`{name, arguments}` JSON) and each result as one `echo`
record. `role: "tool"` messages carry `tool_call_id` and a **string** content. A tool result longer
than 30,000 characters is clipped head+tail (§4 of the recipe; `TOOL_CLIP_CHARS`).

## 2. The turn request (assembled shape)

```
[ system: <fixed willia system prompt> ]
[ assistant: <chat>\n…\n</chat> ]          <- the view, rendered BEFORE logging the message
[ user:  <this turn's message(s), whole> ]
```

- The view message is **`assistant`**, never `user`: the recipe's §3.3 economics need a stable
  prefix that never merges with the current turn. (In the host build a `user` view would be
  concatenated into the turn and could never be a cache prefix. The standalone harness has no such
  merge step, but the same rule is kept — it is also the shape compactions reuse.)
- Nothing else is sent. No dates, no session id, no device list, no model name — the recipe's
  §7.10. Per-turn metadata, if ever needed, goes **after** the view, never in the system prompt.
- Tools are sent on every turn and every compaction, byte-identical (same array, same order).
- Multi-message turns append as they happen: a message that arrives while a call is running joins
  the running conversation, and each is logged as it arrives (recipe §6).

## 3. The view (`View.render`)

```
<chat>
0+1024|text of the first line
1024+512|…
9627+1|…
</chat>
```

- One line per node: `{offset}+{count}|{text}`, where `offset = i << l` and `count = 1 << l`.
- Newlines and carriage returns inside a line become spaces; a line is at most 512 bytes.
- Oldest first; contiguous; covers every message up to the view's end.
- An unbuilt line renders exactly `(not summarized yet: zoom it)` (`view.PLACEHOLDER`).
- No dates in the view — the model calls `date(id)`.
- Sizes: `VIEW_MIN_BYTES = 64_000`, `VIEW_MAX_BYTES = 128_000` (sawtooth, batch-merged).

## 4. The compaction envelope (`Compactor._request` / the new client)

The compaction must be a turn-shaped call, so it reads the turns' `[system][tools]` prefix from the
cache. Exact order:

```
messages[0]  role=system     content = the ONE fixed system prompt (identical to a turn's)
messages[1]  role=assistant  content = CompactionRequest.context   (its own <chat> view, 16–32 KB)
messages[2]  role=user       content = the task template ALONE (COMPACTION_TASK or COMPACTION_MERGE_TASK)
tools                            = the SAME tool schemas a turn sends
```

- The task template is the recipe §4 text verbatim (`COMPACTION_TASK` for a leaf,
  `COMPACTION_MERGE_TASK` for a merge — quoted in `ENGINE.md` §2). **The compaction instructions and
  the rubric are NOT repeated here**: they live in the one fixed system prompt (recipe §5), which
  every turn and every compaction sends byte-identically. The vendor put
  `COMPACTION_SYSTEM.format(rubric=RUBRIC) + "\n\n"` here because its own prompt was a
  condensation — that prefix is the one-line deviation willia drops (`ENGINE.md` §5.1).
- `context` comes from `View.context_view(target=(l, i))` — pinned per target, so the same node
  always yields byte-identical bytes.
- The model is told to call no tools and to output only the line, without an `id+n|` head.
- Reply handling: flatten to one line, keep the shortest, retry with `OVER_LENGTH_NOTICE` when
  over 512 bytes (max 5 tries).
- The compaction sends **no** `reasoning_effort` change and **no** different model — a different
  model forfeits the shared prefix (FINDINGS #3). `[VERIFY in P1]` the measured turn→compaction
  cache read on this route.

## 5. The log record

`main/YYYY-MM-DD.jsonl`, one compact JSON object per line, `ensure_ascii=False`,
`separators=(",", ":")`, key order `i, kind, text, size, date` (dataclass field order):

```json
{"i":0,"kind":"user","text":"hello","size":5,"date":"2026-10-13T05:45:12.345678+00:00"}
```

- `i`: dense, permanent, never reused. The field is the recipe's own `{i, kind, text, size, date}`,
  and it matches the tree line's `{l, i, text, size}`. The **tool** payloads keep `id` / `n` —
  `zoom(id, n)`, `date(id)` is the design's own vocabulary (`ENGINE.md` §6, §8.11).
- `kind` ∈ `user | will | tool | echo | work | note` (the agent's kind was `unii`; `ENGINE.md` §6).
- `size` = `len(text.encode("utf-8"))`; `date` = UTC ISO-8601, and `date[:10]` **must** equal the
  file's day. The file is `main/{date[:10]}.jsonl`.
- Appends are `flush` + `fsync`; a torn tail is repaired before the next append.
- The tree's lines are a parallel format: `tree/YYYY-MM-DD.jsonl`, key order `l, i, text, size`:

```json
{"l":0,"i":0,"text":"user: hello","size":12}
```

- `view.json` (the third durable artifact) is described in `ENGINE.md` §2 (`version: 2`). The recipe
  calls it "the view, as `[l, i]` pairs"; v2 adds the batch state and the maintained compaction
  views that recipe §4 requires — neither is derivable from the log or the tree, which is why a
  missing `view.json` is an explicit unavailable state rather than a rebuild.

## 6. The native tool faces

Each native tool is a normal OpenAI function schema; the result crosses back as a `role: "tool"`
message whose content is a **JSON string**. Shapes are in `TOOLS.md` §3; the delegate and `work`
shapes are in `DELEGATES.md`.

## 7. The `work` record (a delegate's report)

A delegate's report arrives as one append to the log with `kind = "work"` and text starting
`"[Name]"` (recipe §1, §6). Its id is then addressable by `zoom("Name")`. The exact composition is
in `DELEGATES.md` §4.

## 8. Config and env

See `ENV.md`. Nothing in config may change the system prompt or the tool array per turn.

## 9. The usage surface (P3 meter)

`GET https://opencode.ai/zen/go/v1/usage` with `Authorization: Bearer $OPENCODE_GO_API_KEY`,
`Accept: application/json` returns percent-based subscription windows:

```json
{"usage": {"rolling": {"percent": 12.5, "resetsAt": "2026-10-13T08:00:00Z"},
           "weekly":  {"percent": 3.1,  "resetsAt": "…"},
           "monthly": {"percent": 0.4,  "resetsAt": "…"}}}
```

Keys are absent when a window does not apply. Local per-call usage comes from the API `usage`
object (§1) and widens into the canonical buckets
`input_tokens | output_tokens | cache_read_tokens | cache_write_tokens | reasoning_tokens`
(the names the host normalizes to; the meter must not invent its own).
