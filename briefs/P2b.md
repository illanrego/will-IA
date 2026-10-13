# P2b brief - the native tools: web_search, web_extract, vision

Read `docs/TOOLS.md` sections 5-7 (the contracts), `docs/ENV.md` (the config shape),
`docs/WIRE-FORMATS.md` section 1 (why a tool message is never list-type content), `docs/LOOP.md`
section 4 (how a result is logged), and the code you are extending: `willia/dispatch.py`,
`willia/client.py`, `willia/toolkit.py`, `willia/config.py`, `willia/envfile.py`,
`willia/media.py`. The docs are the contract. This brief cites them; it does not restate them.

## What is true today

- `willia/toolkit.py` already carries all seven schemas, including `web_search`, `web_extract` and
  `vision`. **The schemas do not change.** They are the cache anchor (`TOOLS.md` section 9,
  constraint 1) and `tests/test_toolkit.py` locks the code to `docs/TOOLS.md`. Do not edit a
  schema, a description, a property or the array's order.
- `willia/dispatch.py` answers these three with `{"error": "not implemented yet: <name>"}` from
  `_UNIMPLEMENTED`, after `zoom`/`date` and the delegates.
- `willia/config.py` already carries `WebConfig` (backend `ddgs`, `max_results` 5,
  `extract_char_limit` 15000) and `VisionConfig` (`model`, `max_chars` 4000).
- The `ddgs` package is the chosen backend (settled with the user 2026-10-13) and is already
  installed in the environment (`ddgs 9.16.0`).
- The loop already logs a web or vision result as one `echo` record (`TOOLS.md` section 8), so
  `willia/chat.py` needs no change for that.

## The vision route is already decided and measured - do not "correct" it back

The user settled it on 2026-10-13: `vision` runs on **the same OpenCode Go route as the turns**,
with the chat's own model (`deepseek-v4.1-flash`), not on OpenRouter. Measured live that day
(`probes/willia-probe-vision.py`): a multimodal **user** message (a `text` part and an
`image_url` part carrying a `data:` URL) returns **HTTP 200** in either part order and the model
answered the image correctly. The relay's list-content restriction applies to **tool** messages
(`WIRE-FORMATS` section 1); an ordinary multimodal user message is accepted. So:

- The vision call reuses the client's route, credential, session header and attribution headers.
  **There is no second credential and no OpenRouter call anywhere.**
- `VisionConfig.model` is an **override**: `None` (the default) means "use the chat's own model"
  (`config.model.model`).
- The answer stays **text**, so nothing image-shaped ever enters a tool message.

## Deliverables

1. **`willia/client.py`** - add a third call type beside `turn` and `summarize`:
   `vision(image_url, question, *, timeout=None) -> str`. It POSTs one multimodal user message
   (a `text` part with the question, an `image_url` part with the URL) to the same `/chat/completions`
   endpoint, **non-streaming**, and returns the answer text. Reuse `_headers()` (the
   `x-opencode-session` header and the attribution headers are required by the relay) and `_send()`
   so the call inherits the bounded timeout and retry discipline. Do **not** route it through
   `_validate_messages`: that validator encodes the conversation's string-content rule, and this
   message is deliberately a list. A malformed or empty response is a `ClientError`, exactly as
   `summarize` treats one.
2. **`willia/web.py`** (new) - `web_search` and `web_extract`, each returning the JSON string
   `docs/TOOLS.md` sections 5 and 6 specify.
   - `web_search` uses `ddgs`, **imported lazily inside the handler**, so `import willia` and the
     whole suite keep working when it is absent and a missing package is a named failure
     (`{"error": "web_search needs the ddgs package: <exc>"}`) rather than an ImportError out of
     the loop. Honour `limit` (default `WebConfig.max_results`, hard cap 10).
   - `web_extract` is stdlib only (`urllib.request`, `html.parser`). One entry per requested URL,
     **in the requested order**, with `error` set instead of `content` on failure. Reduce HTML to
     text/markdown. A page over `char_limit` (default `WebConfig.extract_char_limit`) is
     head+tail truncated and the content says so. One failing URL must never lose the others.
3. **`willia/vision.py`** (new) - the `vision` handler per `docs/TOOLS.md` section 7.
   - Resolve `image_url`: if it starts with `http://` or `https://` it is passed to the client
     as-is (we never fetch remote bytes); otherwise it is a local path - read it, send it as a
     `data:` URL, and archive it with `media.archive_media(root, message_id, [...])` so the chat
     keeps its own copy even if the file moves.
   - `message_id` is the id of the record carrying the call (`log.count() - 1` at handler time).
     When there is no such record (count 0) skip archiving rather than fail.
   - The answer is bounded by `VisionConfig.max_chars` (4000), and says so when it truncated.
   - Result `{"answer": <text>, "source": <the path or URL>}`; failure `{"error": "<reason>"}`.
4. **`willia/dispatch.py`** - route the three names to their handlers and remove `_UNIMPLEMENTED`.
   Routing only: no HTTP, no HTML, no image reading in `dispatch.py`. Every other name's behaviour
   stays byte-identical.
   - The web handlers must be exercisable through `dispatch` with `chat=None`, because the existing
     dispatch tests build their call from `log`/`tree`/`view`/`root` alone: take config from
     `chat.config` when an owner is present and from a plain `Config()` otherwise.
   - `vision` needs the route owner: use `chat.client`. With `chat is None` return an honest error
     (the same shape the delegate branch uses) rather than constructing a second client.
5. **`pyproject.toml`** - add `ddgs` to `[project].dependencies`. It becomes willia's only
   dependency. Change nothing else in that file.
6. **Tests** - `tests/test_web.py` (new) plus the `tests/test_dispatch.py` update. **All offline**:
   inject or monkeypatch the transport (a `ddgs` stand-in, a fake `urlopen`, and the client's
   injected `transport`) so no test touches the network. Cover: the exact result shapes of
   sections 5-7, the per-URL `error` entry with the other entries intact, the `char_limit`
   truncation and the note it leaves, `limit`'s cap, the missing-package path, a local file being
   archived under the calling record's id, a remote URL not being fetched, and `vision` returning
   an error without an owner. Replace `test_unimplemented`'s three web/vision cases with that real
   coverage; leave the delegate cases as they are if they still answer that way without an owner.
7. **`docs/TOOLS.md` section 7** - it currently says "native (OpenRouter, not the Go relay)" and
   names `OPENROUTER_API_KEY`; that is now wrong. Rewrite that section's route and credential
   sentences to the measured fact: the Go route, the chat's own model, `OPENCODE_GO_KEY`, a
   multimodal user message accepted by the relay (tool messages still must not be list content),
   `VisionConfig.model` as the optional override, and the answer bounded by `VisionConfig.max_chars`.
   Delete the `[VERIFY in P2: ...]` bracket - it is resolved. **`docs/ENV.md`** - only the `vision`
   example, to note that `"model": null` means the chat's own model. No other doc line changes.

## Constraints (every one, again)

- **No git commands of any kind.** Do not commit, stash, branch, restore, diff or reset.
- Edit only the files named above. In particular do not touch `willia/toolkit.py` or
  `willia/chat.py`.
- Do not add any dependency other than `ddgs`. Do not introduce an OpenRouter credential or route.
- A tool result is a JSON string and never list-type content in a tool message.
- A tool never raises into the loop: a failure is `{"error": ...}`.
- Python 3.11+, stdlib only besides `ddgs`.

## Proof

Run the whole suite (`uv run --no-project --with pytest python -m pytest -q`) and paste the tail.
Then paste the new `Client.vision` body, the three handler bodies, and the `dispatch.py` diff, and
say for each of the seven deliverables exactly what you changed.
