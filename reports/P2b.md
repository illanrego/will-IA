Implemented all seven deliverables without running any git commands.

1. [client.py](/home/illan/Documents/coding/willia/willia/client.py:298): added non-streaming `Client.vision()`, reusing the Go endpoint, headers, session, `_send()` retries/timeouts, chat model by default, and optional vision-model override.
2. [web.py](/home/illan/Documents/coding/willia/willia/web.py:1): added lazy-DDGS search and stdlib HTML extraction with ordered per-URL results, isolated failures, and bounded head/tail content.
3. [vision.py](/home/illan/Documents/coding/willia/willia/vision.py:1): added local data-URL conversion and archival, untouched remote URLs, bounded answers, and JSON errors.
4. [dispatch.py](/home/illan/Documents/coding/willia/willia/dispatch.py:34): routed all three tools; web works without an owner, while vision reports an owner error when unavailable.
5. [pyproject.toml](/home/illan/Documents/coding/willia/pyproject.toml:10): made `ddgs` the sole dependency.
6. [test_web.py](/home/illan/Documents/coding/willia/tests/test_web.py:1) and [test_dispatch.py](/home/illan/Documents/coding/willia/tests/test_dispatch.py:62): added entirely offline coverage for result shapes, caps, missing DDGS, extraction failures/truncation, client payloads, model selection, archival, no-record handling, remote references, and ownerless dispatch.
7. [TOOLS.md](/home/illan/Documents/coding/willia/docs/TOOLS.md:136) and [ENV.md](/home/illan/Documents/coding/willia/docs/ENV.md:91): documented the measured Go vision route, shared credential/session, multimodal user-message exception, model override, output bound, and `null` model meaning.

`toolkit.py` and `chat.py` were untouched.

### Full-suite proof

```text
........................................................................ [ 28%]
........................................................................ [ 57%]
........................................................................ [ 85%]
....................................                                     [100%]
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
252 passed, 3 warnings in 8.80s
```

The warnings are one delegate-thread close-timing warning and two intentional invalid-record warnings.

### `Client.vision`

```python
def vision(self, image_url: str, question: str, *,
           timeout: float | None = None) -> str:
    self.last_usage = {}
    payload = {
        "model": self.config.vision.model or self.config.model.model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
        "stream": False,
    }
    call_timeout = self.config.model.turn_timeout_s if timeout is None else timeout
    lines = self._send(payload, call_timeout)
    raw = "".join(
        line.decode("utf-8") if isinstance(line, bytes) else line for line in lines
    )
    try:
        response = json.loads(raw)
        if isinstance(response.get("usage"), dict):
            self.last_usage = response["usage"]
        choice = response["choices"][0]
        content = choice["message"].get("content")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ClientError(None, "Malformed completion response") from exc
    if not isinstance(content, str) or not content.strip():
        raise ClientError(None, "Vision returned no ordinary content")
    return content.strip()
```

### Handler bodies

```python
def web_search(query: object, limit: object = None,
               config: WebConfig | None = None) -> str:
    """Search with DDGS and return the fixed JSON tool-result shape."""
    settings = config or WebConfig()
    if not isinstance(query, str) or not query.strip():
        return _error("query must be a nonempty string")
    count = settings.max_results if limit is None else limit
    if type(count) is not int or count < 1:
        return _error("limit must be a positive integer")
    count = min(count, 10)
    try:
        from ddgs import DDGS
    except ImportError as exc:
        return _error(f"web_search needs the ddgs package: {exc}")
    try:
        found = DDGS().text(query, max_results=count)
        results = []
        for item in list(found)[:count]:
            if not isinstance(item, dict):
                continue
            results.append({
                "title": str(item.get("title") or ""),
                "url": str(item.get("href") or item.get("url") or ""),
                "description": str(item.get("body") or item.get("description") or ""),
            })
        return json.dumps({"results": results}, ensure_ascii=False)
    except ImportError as exc:
        return _error(f"web_search needs the ddgs package: {exc}")
    except Exception as exc:
        return _error(exc)
```

```python
def web_extract(urls: object, char_limit: object = None,
                config: WebConfig | None = None) -> str:
    """Fetch each requested page independently and reduce its HTML to text."""
    settings = config or WebConfig()
    if not isinstance(urls, list):
        return _error("urls must be an array")
    if len(urls) > 5:
        return _error("urls must contain at most 5 entries")
    budget = settings.extract_char_limit if char_limit is None else char_limit
    if type(budget) is not int or budget < 1:
        return _error("char_limit must be a positive integer")
    results: list[dict[str, object]] = []
    for url in urls:
        if not isinstance(url, str) or not url:
            results.append({
                "url": url, "title": "", "content": None,
                "error": "url must be a nonempty string",
            })
            continue
        try:
            results.append(_extract(url, budget))
        except Exception as exc:
            results.append({
                "url": url, "title": "", "content": None, "error": str(exc),
            })
    return json.dumps({"results": results}, ensure_ascii=False)
```

```python
def vision(image_url: object, question: object, *, client, config: VisionConfig,
           root: Path, log) -> str:
    """Resolve an image reference, ask the owner client, and return JSON text."""
    try:
        if not isinstance(image_url, str) or not image_url:
            raise ValueError("image_url must be a nonempty string")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a nonempty string")
        resolved = image_url
        if not image_url.startswith(("http://", "https://")):
            path = Path(image_url).expanduser()
            raw = path.read_bytes()
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            resolved = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            message_id = log.count() - 1
            if message_id >= 0:
                media.archive_media(
                    Path(root), message_id,
                    [{"type": "image_url", "image_url": {"url": resolved}}],
                )
        answer = client.vision(resolved, question)
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("vision returned no answer")
        return json.dumps({
            "answer": _bounded(answer.strip(), config.max_chars),
            "source": image_url,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
```

### `dispatch.py` diff

```diff
-from . import jobs, toolkit, tools
+from . import jobs, toolkit, tools, vision as vision_tool, web
+from .config import Config

-_UNIMPLEMENTED = {"web_search", "web_extract", "vision"}
 _DELEGATES = {"delegate_codex": "codex", "delegate_hermes": "hermes"}

 def dispatch(...):
     try:
-        if name in _UNIMPLEMENTED:
-            return _error(f"not implemented yet: {name}")
         if name in _DELEGATES and chat is None:
             return _error(f"not implemented yet: {name}")
-        if name not in {"zoom", "date", *_DELEGATES}:
+        if name == "vision" and chat is None:
+            return _error("vision needs an owning chat")
+        if name not in {
+            "zoom", "date", "web_search", "web_extract", "vision", *_DELEGATES,
+        }:
             return _error(f"unknown tool: {name}")
         if isinstance(arguments, str):
             arguments = json.loads(arguments)
         if not isinstance(arguments, dict):
             return _error("arguments must be a JSON object")
+        if name in {"web_search", "web_extract"}:
+            config = chat.config if chat is not None else Config()
+            if name == "web_search":
+                return web.web_search(
+                    arguments.get("query"), arguments.get("limit"), config.web
+                )
+            return web.web_extract(
+                arguments.get("urls"), arguments.get("char_limit"), config.web
+            )
+        if name == "vision":
+            return vision_tool.vision(
+                arguments.get("image_url"), arguments.get("question"),
+                client=chat.client, config=chat.config.vision,
+                root=Path(root), log=log,
+            )
         if name in _DELEGATES:
```