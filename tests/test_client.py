import json
import socket

import pytest

from willia import prompts, toolkit
from willia.client import Client, ClientError, ClientTimeout
from willia.compactor import CompactionRequest
from willia.config import Config


def sse(chunk):
    return "data: " + json.dumps(chunk)


def nonstream(content=None, *, reasoning=None):
    return json.dumps({
        "choices": [{
            "message": {"content": content, "reasoning_content": reasoning},
            "finish_reason": "stop",
        }],
        "usage": {"total_tokens": 3},
    })


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return iter(response)


@pytest.fixture
def config(tmp_path):
    return Config.load(tmp_path / "missing.json")


@pytest.fixture(autouse=True)
def credential(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key-never-logged")


def test_headers_include_session_user_agent_and_attribution(config):
    transport = FakeTransport([sse({"choices": [{"delta": {"content": "ok"},
                                                   "finish_reason": "stop"}]}),
                               "data: [DONE]"])
    client = Client(config, "stable-session", transport=transport)

    client.turn([{"role": "user", "content": "hello"}], [])

    url, headers, payload, timeout = transport.calls[0]
    assert url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert headers["x-opencode-session"] == "stable-session"
    assert headers["User-Agent"].startswith("willia/")
    assert headers["User-Agent"] != "Python-urllib"
    assert headers["HTTP-Referer"]
    assert headers["X-Title"] == "will.I.A."
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"].startswith("Bearer ")
    assert payload["stream"] is True
    assert timeout == 120


def test_sse_accumulates_content_reasoning_tools_and_final_usage(config):
    usage = {
        "prompt_tokens": 100,
        "prompt_tokens_details": {"cached_tokens": 88},
    }
    transport = FakeTransport([
        sse({"choices": [{"delta": {"content": "hel", "reasoning_content": "think "}}]}),
        sse({"choices": [{"delta": {"content": "lo", "tool_calls": [
            {"index": 0, "id": "call-a", "function": {"name": "zoom", "arguments": '{"id":'}},
            {"index": 1, "function": {"arguments": '{"id":"Agent"'}},
        ]}}]}),
        sse({"choices": [{"delta": {"reasoning_content": "again", "tool_calls": [
            {"index": 0, "function": {"arguments": "7}"}},
            {"index": 1, "id": "call-b", "function": {"name": "date", "arguments": "}"}},
        ]}, "finish_reason": "tool_calls"}]}),
        sse({"choices": [], "usage": usage}),
        "data: [DONE]",
    ])

    reply = Client(config, "session", transport=transport).turn(
        [{"role": "user", "content": "hello"}], toolkit.schemas()
    )

    assert reply.content == "hello"
    assert reply.reasoning == "think again"
    assert [(call.id, call.name, call.arguments) for call in reply.tool_calls] == [
        ("call-a", "zoom", {"id": 7}),
        ("call-b", "date", {"id": "Agent"}),
    ]
    assert reply.usage == usage
    assert reply.usage["prompt_tokens_details"]["cached_tokens"] == 88
    assert reply.finish_reason == "tool_calls"


def test_summarize_returns_only_flattened_ordinary_content(config):
    transport = FakeTransport([nonstream(" first\nsecond ", reasoning="private")])
    request = CompactionRequest(system="system", context="context", task="task", tools=[])

    result = Client(config, "session", transport=transport).summarize(request)

    assert result == "first second"
    payload = transport.calls[0][2]
    assert payload["stream"] is False
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 700


def test_summarize_rejects_reasoning_only_reply(config):
    transport = FakeTransport([nonstream(None, reasoning="only reasoning")])

    with pytest.raises(ClientError):
        Client(config, "session", transport=transport).summarize(
            CompactionRequest(system="", context="", task="task", tools=[])
        )


def test_retryable_server_error_then_success(config, monkeypatch):
    transport = FakeTransport(
        ClientError(500, "temporary"),
        [sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}),
         "data: [DONE]"],
    )
    sleeps = []
    monkeypatch.setattr("willia.client.time.sleep", sleeps.append)

    reply = Client(config, "session", transport=transport).turn(
        [{"role": "user", "content": "hello"}], []
    )

    assert reply.content == "ok"
    assert len(transport.calls) == 2
    assert sleeps == [1]


def test_three_server_errors_raise(config, monkeypatch):
    transport = FakeTransport(*(ClientError(500, "temporary") for _ in range(3)))
    monkeypatch.setattr("willia.client.time.sleep", lambda _seconds: None)

    with pytest.raises(ClientError) as caught:
        Client(config, "session", transport=transport).turn(
            [{"role": "user", "content": "hello"}], []
        )

    assert caught.value.status == 500
    assert len(transport.calls) == 3


def test_socket_timeout_raises_client_timeout(config, monkeypatch):
    transport = FakeTransport(*(socket.timeout("slow") for _ in range(3)))
    monkeypatch.setattr("willia.client.time.sleep", lambda _seconds: None)

    with pytest.raises(ClientTimeout):
        Client(config, "session", transport=transport).turn(
            [{"role": "user", "content": "hello"}], []
        )


def test_compaction_envelope_reuses_exact_system_task_and_tools(config):
    system = prompts.build_system_prompt(prompts.default_instructions())
    task = prompts.COMPACTION_TASK.format(
        id=3, node_bytes=512, ruler="-" * 512, input="user: remember this",
    )
    tools = toolkit.schemas()
    transport = FakeTransport([nonstream("summary")])

    Client(config, "session", transport=transport).summarize(
        CompactionRequest(system=system, context="<chat>\ncontext\n</chat>",
                          task=task, tools=tools)
    )

    payload = transport.calls[0][2]
    assert payload["messages"] == [
        {"role": "system", "content": system},
        {"role": "assistant", "content": "<chat>\ncontext\n</chat>"},
        {"role": "user", "content": task},
    ]
    assert payload["messages"][0]["content"].encode() == system.encode()
    assert payload["messages"][-1]["content"].encode() == task.encode()
    assert payload["tools"] is tools


def test_successive_turns_preserve_messages_anchor_and_tools(config):
    system_message = {"role": "system", "content": "fixed anchor"}
    messages = [system_message, {"role": "user", "content": "hello"}]
    tools = toolkit.schemas()
    ok = [sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}),
          "data: [DONE]"]
    transport = FakeTransport(ok, ok)
    client = Client(config, "session", transport=transport)

    client.turn(messages, tools)
    client.turn(messages, tools)

    first = transport.calls[0][2]
    second = transport.calls[1][2]
    assert first["tools"] is second["tools"] is tools
    assert first["messages"][0] is second["messages"][0] is system_message
    assert json.dumps(first["tools"], separators=(",", ":")) == json.dumps(
        second["tools"], separators=(",", ":")
    )
    assert first["messages"][0] == second["messages"][0]


def test_list_message_content_is_rejected_before_transport(config):
    transport = FakeTransport([])

    with pytest.raises(ValueError, match=r"messages\[0\]\.content"):
        Client(config, "session", transport=transport).turn(
            [{"role": "tool", "content": [{"type": "text", "text": "bad"}]}], []
        )

    assert transport.calls == []
