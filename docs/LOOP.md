# LOOP.md — the turn loop and the compaction pump

Specified from the recipe (`optchat.md`) §1–§4 and §6, plus the modules' real semantics
(`ENGINE.md`). Where the host build could not do something, the difference is marked **[standalone]**.

## 1. The loop (recipe §6)

```
on user input m:
    if a turn is running:      enqueue m into the running turn's inbox   # "hand m to it between tool calls"
    else:                      start_turn([m])

start_turn(messages):
    settle()                                  # §2 - wait until every message before m is summarized
    view_text = view.render()                 # RENDER BEFORE LOGGING; frozen for the whole turn
    for m in messages: log_user(m)            # append + seed + add_root, whole, after the render
    request = [system] + [assistant: view_text] + logged_turn_messages()
    loop:
        reply = client.chat(request, tools)   # streamed; §3 of WIRE-FORMATS
        if reply.content:  log_reply(reply.content)           # kind "will", split if long
        if reply.tool_calls: log_tool_calls(reply.tool_calls) # one "tool" record each
        request += [assistant message]
        if not reply.tool_calls: break
        for call in reply.tool_calls:
            result = dispatch(call)           # never raises; a failure is a JSON error string
            log_result(call, result)          # "echo", or "work" for a delegate, clipped
            request += [tool message]
        request += drained_inbox_as_user_messages()
    turn_end()
```

Rules taken literally:

- **The view is rendered before the new message is logged**, and the *same* rendered text is used
  for every API call inside the turn (a frozen snapshot — the prefix never moves mid-turn, so the
  cache holds across the turn's tool rounds). Messages logged during the turn enter the *live*
  view (`add_root`) but not the frozen text.
- **Nothing carries between turns.** Each turn's request is rebuilt from `[system][view][this turn]`.
- Per-turn state (if ever needed) goes **after** the view, never in the system prompt (§7.10).
- **Thoughts are shown but never logged** (§1). A reply with reasoning fields and no ordinary
  content logs nothing.
- Long user text is **never cut**: it is logged as several records in a row
  (`split_for_kind(text, node_bytes, "user")`). Tool output is the one exception: clipped head+tail
  to 30,000 characters (first 15,000 + last 15,000) before it is logged.
- `turn_end()`: `tree.save()`, `view.save()`, then **kick the background drain** and return the
  prompt to the user immediately — the drain never holds the prompt or a turn lease.

## 2. The settle rule (the wait the recipe names)

- The turn path calls `compactor.settle(max_nodes=64, timeout_s=20.0, model_calls=False)`: it
  builds every node that needs no model call and never starts one. The vendor's reason was
  host-specific (a synchronous hook a deadline could not interrupt); willia keeps the flag as a
  **budget** — a turn should not block on compaction model calls — not as a ban (`ENGINE.md`
  §8.12).
- **[standalone]** the turn may then join the in-flight background drain with the remaining
  deadline. Unlike the host (where the engine could not wait on the host's own request path), the
  drain here is our thread, so a turn can honestly wait a few seconds for the last summaries
  instead of starting with placeholders. Bounded by the same 20 s; on timeout the turn proceeds
  and the view may carry `(not summarized yet: zoom it)`.
- Model work is always left to the drain; the turn never calls a model for compaction.

## 3. The compaction pump

- One **drain thread** at a time (a lock), started after `turn_end()` and after `import_notes`.
- One pass: `compactor.run_pending(limit=8, model_calls=True)` — which merges the view batch first,
  then runs waves of at most 8 model jobs (`COMPACT_CONCURRENCY`) through the thread pool, applies
  results in queue order, then merges again. Then `tree.save()` and `view.save()`.
- The pass must have the turn's `system` and `tools` set on the compactor **before** it runs
  (`compactor.system`, `compactor.tools` — the compaction reuses the turn's `[system][tools]`
  prefix; FINDINGS #2: capture them unconditionally, on every route).
- Compactions bind to the same route, model and credentials as the turns. A different model for
  compactions forfeits the shared prefix and is refused at config time, not silently allowed.
- The pump is idempotent and resumable: unbuilt nodes stay queued; a failed call is deferred and
  re-queued in `finally`, never lost, never spun on.
- Compaction views stay at 16,000–32,000 bytes (`View.context_view`), pinned per target, so the
  same node always yields byte-identical bytes.
- The compaction's user message is the **task template alone**: the one fixed system prompt already
  carries the design's compaction instructions and rubric (`ENGINE.md` §5.1, `WIRE-FORMATS` §4).

## 4. Record classification (from `engine.py::_records`, made exact)

| Source | Records |
|---|---|
| user message | one `user` per `split_for_kind(text, node_bytes, "user")` chunk |
| assistant text | one `will` per `split_for_kind(content, node_bytes, "will")` chunk; with media and no text, one `will` per media part |
| assistant tool calls | one `tool` per call: `{"name": <name>, "arguments": <parsed or raw>, "content"?: <assistant text>}` as compact JSON, `ensure_ascii=False` |
| tool result | clipped head+tail at 30,000; a **delegate** result (tool name in the delegate set) whose payload names itself → one `work` record `"[{name}] {text}"`; anything else → one `echo` |
| reasoning / thoughts | **nothing** |
| delegate report (async) | one `work` record `"[{name}] {report}"` (§`DELEGATES.md` §4) |
| imported pre-chat text | one `note` per chunk (`notes.import_notes`) |

Assistant text that accompanies tool calls is kept **inside that call's `tool` record** (`content`),
not as an extra `will` record — the host build's shape; cheap to change, but it must be one shape.

## 5. Durability and recovery at startup

Order of writes, and what a crash between them means:

1. `log.append(...)` — fsynced; this is the source of truth, append-only.
2. `compactor.seed(id, text, kind)` — builds free nodes immediately, holds long sources in memory,
   queues model nodes.
3. `view.add_root(id)`.
4. `tree.save()` / `view.save()` — at `turn_end()` and after each drain pass.

Crash windows and the startup reconciliation (never a rebuild):

- **Log ahead of the view** (records appended, `view.json` not saved): at startup `view._end()`
  is behind `log.count()`. The gap ids were never in any pair selection, so appending roots for
  them is the normal `add_root` path, **not** a rebuild. Catch up `[view._end(), log.count())`,
  then merge and save.
- **Long sources stranded** (a record whose `node(0, id)` was never built, or was in memory when
  the process died): re-seed from the log record itself — `compactor.seed(id, record.text, record.kind)`.
  The source text is always recoverable because the log holds it. This is the standalone form of
  the host's "recover missing roots from raw records".
- **`view.json` missing on a chat that has records**: `View` raises `ViewStateUnavailable`
  (`ENGINE.md` §2). willia must **not** rebuild and must **not** silently start an empty chat:
  it stops, says so, and points at the backup. **[standalone]** so that state is recoverable, the
  harness keeps `~/.willia/backups/view.json` refreshed at every `turn_end()` (a plain file copy of
  the last good publication).
- **Mid-file corruption** in the log or tree: the vendored loaders raise. Loud, no repair.
- On clean exit: `tree.save()`, `view.save()`, close the log (releases the flock). A `--new` chat
  archives the whole root instead of overwriting anything.

**The design's position (recipe §1, §2, §3, §7.3, §7.12).** The recipe's entire durability
contract is: append and flush each write; one process owns a chat under a lock; never edit or
delete a line; build each node once and log it; save the view and load it at start; never rebuild
it. It has **no checkpoint, no identity ledger, no in-flight marker and no reconciliation
protocol** — because in the design the log *is* the primary artifact; nothing else produces it. The
host build needed a checkpoint only because there the log was *derived* from a transcript the host
owned (which it could replay, reorder, or hand over incomplete). Standalone that reason does not
exist, so the protocol is **not adopted** and its code is deleted (`ENGINE.md` §8.1).

The one case the recipe leaves unaddressed is a kill mid-multi-record message: its own long-text
rule ("logged as several messages in a row") sets no atomicity requirement, so a partial paste is
still a valid log — only semantically short. A marker for it would be an **extension beyond the
design**, and would be labelled as such, not as a restoration of fidelity.

## 6. Delegates are backgrounded (recipe §6)

- A delegate call returns **immediately** after spawning: the master logs the `tool` record and has
  nothing else to wait for. No sleep, no polling, ever.
- The report arrives later as a `work` record; if a turn is running it is handed to it between tool
  calls, otherwise it is there for the next turn (a new turn is started with it, so the model sees
  it as the message after the view).
- The master tells the user what is running and ends its turn.

## 7. Failure handling matrix

| Failure | Behaviour |
|---|---|
| chat API error (4xx/5xx/429) | bounded retry with backoff, then end the turn and print the error. Nothing is logged for the failed call; what was already logged stands (append-only). |
| compaction call fails | `RuntimeWarning`, node deferred, retried at the next pass (vendored behaviour). |
| the report is over 512 bytes | ruler retry (`OVER_LENGTH_NOTICE`), keep the shortest, ≤5 tries (vendored). |
| log append fails | the `Log` latches `_append_failed` and refuses further appends. The loop stops loudly and keeps the pending text in the terminal; it does not pretend the message was saved. |
| tool raises | the dispatcher converts it to `{"error": ...}` and logs it as an `echo`; the turn continues. |
| a tool result is a delegate report | never truncated below the 30,000 clip, and the *full* report file stays on disk next to the clipped record. |
| empty assistant reply | nothing logged; the loop asks again once, then ends the turn with a note to the user. |
| process killed mid-turn | startup reconciliation (§5). |

## 8. REPL contract (v1: plain line-based)

- Streaming display: `will` text prints as it arrives; a tool call prints one line
  (`→ zoom {"id": 40, "n": 8}`), its result one line (truncated on screen, whole in the log).
- **Long paste:** input is buffered; a line ending in a single `\` continues; a blank line submits
  the buffer. A pasted block is never echoed back whole.
- Commands (v1, minimal): `/quit` (also Ctrl-D), `/help`, `/status` (root path, record count, view
  bytes, unbuilt nodes, running delegates).
- `/quit`: save tree + view, join the drain with a short deadline, close the log.
- One process reads stdin on a small thread and feeds either the running turn's inbox or the
  command parser. The drain never blocks input.
- A TUI is explicitly later (P3+), and must reuse this loop, not reimplement it.

## 9. What the harness must not do (the recipe's §7, as code rules)

1. Never measure a pair's age from its first message — `view.due` is the only ordering.
2. Never merge at every message — `merge_batch` is the only merge entry point (batch semantics).
3. Never rebuild the view — not at startup, not on a missing file, not after a crash.
4. Never keep K lines per level.
5. Never put a whole message in the view, and never render the start of an unsummarized one.
6. Never send a compaction without the turn's `[system][tools]` prefix or with its own prompt.
7. Never trust the model to count bytes — the ruler, the cut and the retries do it.
8. Never log a line under 512 bytes as a node (the tree's own rule).
9. Never log thoughts.
10. Never put dates or state in the system prompt or tool schemas.
11. Never carry a conversation across turns.
12. Never write the log without `fsync`, and never with two writers.
13. Never scan the tree for work — the queues are the only source of jobs.
