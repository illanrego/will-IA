"""OpenCode Go transport for turns and cache-shaped compactions.

The client owns wire validation, timeouts and bounded retries while retaining no
conversation state between calls.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from .compactor import CompactionRequest
from .config import Config
from .envfile import opencode_go_key


Transport = Callable[[str, dict, dict, float], Iterator[str]]
_BACKOFF_SECONDS = (1, 2, 4)
_BODY_EXCERPT_CHARS = 300


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict | str
    raw_arguments: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class Reply:
    content: str
    reasoning: str
    tool_calls: list[ToolCall]
    usage: dict
    finish_reason: str | None


class ClientError(Exception):
    """An HTTP or response error with only a bounded body excerpt attached."""

    def __init__(self, status: int | None, body: str):
        self.status = status
        self.body_excerpt = str(body)[:_BODY_EXCERPT_CHARS]
        self.body = self.body_excerpt
        label = f"HTTP {status}" if status is not None else "Client request failed"
        super().__init__(f"{label}: {self.body_excerpt}")


class ClientTimeout(ClientError):
    """A request exhausted the bounded timeout retries."""


def _package_version() -> str:
    try:
        return version("willia")
    except PackageNotFoundError:
        return "0.0.1"


def _default_transport(url: str, headers: dict, payload: dict,
                       timeout: float) -> Iterator[str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if payload.get("stream"):
                for line in response:
                    yield line.decode("utf-8")
            else:
                yield response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(_BODY_EXCERPT_CHARS).decode("utf-8", errors="replace")
        except Exception:
            body = str(exc.reason)
        raise ClientError(exc.code, body) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise socket.timeout(str(exc.reason)) from exc
        raise ClientError(None, str(exc.reason)) from exc


def _timeout_exception(exc: BaseException) -> bool:
    return isinstance(exc, (socket.timeout, TimeoutError, ClientTimeout))


class Client:
    def __init__(self, config: Config, session: str, *, transport: Transport | None = None):
        self.config = config
        self.session = session
        self._transport = transport or _default_transport
        self.last_usage: dict = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {opencode_go_key()}",
            "Content-Type": "application/json",
            "User-Agent": f"willia/{_package_version()}",
            "HTTP-Referer": self.config.model.referer,
            "X-Title": "will.I.A.",
            "x-opencode-session": self.session,
        }

    @property
    def _url(self) -> str:
        return self.config.model.base_url.rstrip("/") + "/chat/completions"

    @staticmethod
    def _validate_messages(messages: list[dict]) -> None:
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ValueError(f"messages[{index}].content must be a str")

    def _send(self, payload: dict, timeout: float) -> Iterator[str]:
        last_error: ClientError | None = None
        started = False
        for attempt in range(3):
            try:
                result = self._transport(self._url, self._headers(), payload, timeout)
                try:
                    for line in result:
                        started = True
                        yield line
                finally:
                    close = getattr(result, "close", None)
                    if close is not None:
                        close()
                return
            except Exception as exc:
                if _timeout_exception(exc):
                    error = exc if isinstance(exc, ClientTimeout) else ClientTimeout(
                        None, "Request timed out"
                    )
                    retryable = True
                elif isinstance(exc, ClientError):
                    error = exc
                    retryable = exc.status == 429 or (
                        exc.status is not None and 500 <= exc.status <= 599
                    )
                else:
                    raise
                last_error = error
                # Replaying a partially displayed stream would duplicate text and
                # splice two different sets of tool arguments together.
                if started or not retryable or attempt == 2:
                    raise error from exc
                time.sleep(_BACKOFF_SECONDS[attempt])
        assert last_error is not None
        raise last_error

    @staticmethod
    def _sse(lines: Iterable[str],
             on_delta: Callable[[str, str], None] | None = None) -> Reply:
        content: list[str] = []
        reasoning: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage: dict = {}
        finish_reason: str | None = None
        done = False
        for raw in lines:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    done = True
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise ClientError(None, "Malformed SSE JSON") from exc
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    if delta.get("content") is not None:
                        content.append(str(delta["content"]))
                        if on_delta is not None:
                            on_delta("content", content[-1])
                    if delta.get("reasoning_content") is not None:
                        reasoning.append(str(delta["reasoning_content"]))
                        if on_delta is not None:
                            on_delta("reasoning", reasoning[-1])
                    for fragment in delta.get("tool_calls") or []:
                        index = fragment.get("index")
                        if not isinstance(index, int):
                            continue
                        current = calls.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        if fragment.get("id") is not None:
                            current["id"] = str(fragment["id"])
                        function = fragment.get("function") or {}
                        if function.get("name") is not None:
                            current["name"] = str(function["name"])
                        if function.get("arguments") is not None:
                            current["arguments"] += str(function["arguments"])
                if done:
                    break
            if done:
                break

        tool_calls = []
        for index in sorted(calls):
            call = calls[index]
            raw_arguments = call["arguments"]
            try:
                parsed = json.loads(raw_arguments)
            except (json.JSONDecodeError, TypeError):
                arguments: dict | str = raw_arguments
            else:
                arguments = parsed if isinstance(parsed, dict) else raw_arguments
            tool_calls.append(ToolCall(
                id=call["id"], name=call["name"], arguments=arguments,
                raw_arguments=raw_arguments,
            ))
        return Reply(
            content="".join(content),
            reasoning="".join(reasoning),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
        )

    def turn(self, messages: list[dict], tools: list, *,
             on_delta: Callable[[str, str], None] | None = None,
             timeout: float | None = None) -> Reply:
        self.last_usage = {}
        self._validate_messages(messages)
        payload = {
            "model": self.config.model.model,
            "messages": messages,
            "tools": tools,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.config.model.turns.reasoning_effort is not None:
            payload["reasoning_effort"] = self.config.model.turns.reasoning_effort
        call_timeout = self.config.model.turn_timeout_s if timeout is None else timeout
        lines = self._send(payload, call_timeout)
        try:
            reply = self._sse(lines, on_delta)
        finally:
            lines.close()
        self.last_usage = reply.usage
        return reply

    def summarize(self, request: CompactionRequest) -> str:
        self.last_usage = {}
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        if request.context:
            messages.append({"role": "assistant", "content": request.context})
        messages.append({"role": "user", "content": request.task})
        self._validate_messages(messages)
        payload = {
            "model": self.config.model.model,
            "messages": messages,
            "tools": request.tools or None,
            "stream": False,
            "thinking": {"type": "disabled"},
            "max_tokens": self.config.model.compactions.max_tokens,
        }
        lines = self._send(payload, self.config.model.compaction_timeout_s)
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
            raise ClientError(None, "Compaction returned no ordinary content")
        return " ".join(content.splitlines()).strip()
