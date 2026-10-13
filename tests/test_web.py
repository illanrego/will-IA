import builtins
import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from willia import media
from willia.client import Client, ClientError
from willia.config import Config, VisionConfig, WebConfig
from willia.store import Log
from willia.vision import vision
from willia.web import web_extract, web_search


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode()
        self.headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload, timeout))
        return iter([self.response])


def completion(content):
    return json.dumps({
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 4},
    })


def test_web_search_shape_default_and_hard_cap(monkeypatch):
    calls = []

    class DDGS:
        def text(self, query, *, max_results):
            calls.append((query, max_results))
            return [
                {"title": f"Title {i}", "href": f"https://example.test/{i}",
                 "body": f"Description {i}"}
                for i in range(12)
            ]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=DDGS))

    default = json.loads(web_search("query", config=WebConfig(max_results=2)))
    capped = json.loads(web_search("query", 99))

    assert default == {"results": [
        {"title": "Title 0", "url": "https://example.test/0",
         "description": "Description 0"},
        {"title": "Title 1", "url": "https://example.test/1",
         "description": "Description 1"},
    ]}
    assert len(capped["results"]) == 10
    assert calls == [("query", 2), ("query", 10)]


def test_web_search_names_missing_ddgs(monkeypatch):
    real_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "ddgs":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    assert json.loads(web_search("query")) == {
        "error": "web_search needs the ddgs package: not installed"
    }


def test_web_extract_keeps_order_shape_and_per_url_error(monkeypatch):
    pages = {
        "https://one.test": "<html><head><title>One</title></head>"
                            "<body><h1>Hello</h1><p>First page.</p></body></html>",
        "https://three.test": "<html><head><title>Three</title></head>"
                              "<body><p>Last page.</p></body></html>",
    }

    def urlopen(request, timeout):
        assert timeout == 20
        if request.full_url == "https://two.test":
            raise OSError("page unavailable")
        return FakeResponse(pages[request.full_url])

    monkeypatch.setattr("willia.web.urllib.request.urlopen", urlopen)
    result = json.loads(web_extract([
        "https://one.test", "https://two.test", "https://three.test",
    ]))["results"]

    assert result == [
        {"url": "https://one.test", "title": "One",
         "content": "Hello\n\nFirst page.", "error": None},
        {"url": "https://two.test", "title": "", "content": None,
         "error": "page unavailable"},
        {"url": "https://three.test", "title": "Three",
         "content": "Last page.", "error": None},
    ]


def test_web_extract_truncates_head_and_tail_with_note(monkeypatch):
    body = "HEAD-" + "x" * 200 + "-TAIL"
    monkeypatch.setattr(
        "willia.web.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(f"<title>Long</title><p>{body}</p>"),
    )

    result = json.loads(web_extract(["https://long.test"], 80))["results"][0]

    assert len(result["content"]) == 80
    assert result["content"].startswith("HEAD-")
    assert result["content"].endswith("-TAIL")
    assert "[truncated: head and tail preserved]" in result["content"]


def test_client_vision_uses_multimodal_user_message_and_same_route(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    config = Config()
    transport = FakeTransport(completion("A blue square."))
    client = Client(config, "stable-session", transport=transport)

    answer = client.vision("data:image/png;base64,YWJj", "What is shown?", timeout=9)

    assert answer == "A blue square."
    url, headers, payload, timeout = transport.calls[0]
    assert url == "https://opencode.ai/zen/go/v1/chat/completions"
    assert headers["x-opencode-session"] == "stable-session"
    assert headers["HTTP-Referer"] == config.model.referer
    assert payload == {
        "model": config.model.model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "What is shown?"},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,YWJj"}},
        ]}],
        "stream": False,
    }
    assert timeout == 9
    assert client.last_usage == {"total_tokens": 4}


def test_client_vision_honours_model_override(monkeypatch):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    config = replace(Config(), vision=VisionConfig(model="vision-override"))
    transport = FakeTransport(completion("answer"))

    Client(config, "session", transport=transport).vision(
        "https://example.test/image.png", "What?"
    )

    assert transport.calls[0][2]["model"] == "vision-override"


@pytest.mark.parametrize("response", ["not json", completion(None), completion("  ")])
def test_client_vision_rejects_malformed_or_empty_response(monkeypatch, response):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")
    with pytest.raises(ClientError):
        Client(Config(), "session", transport=FakeTransport(response)).vision(
            "https://example.test/image.png", "What?"
        )


def test_local_vision_file_is_data_url_and_archived_for_call_record(tmp_path):
    image = tmp_path / "source.png"
    image.write_bytes(b"image bytes")
    seen = []
    client = SimpleNamespace(vision=lambda url, question: seen.append((url, question)) or "answer")

    with Log(tmp_path) as log:
        log.append("user", "before")
        call_id = log.append("tool", "vision call")
        result = json.loads(vision(
            str(image), "Describe it", client=client, config=VisionConfig(),
            root=tmp_path, log=log,
        ))

    assert result == {"answer": "answer", "source": str(image)}
    assert seen[0][0].startswith("data:image/png;base64,")
    assert seen[0][1] == "Describe it"
    archived = media.media_for(tmp_path, call_id)
    assert archived == [{"path": f"assets/{call_id}-0.png", "type": "image"}]
    assert (tmp_path / archived[0]["path"]).read_bytes() == b"image bytes"


def test_local_vision_without_call_record_skips_archive(tmp_path):
    image = tmp_path / "source.png"
    image.write_bytes(b"image bytes")
    client = SimpleNamespace(vision=lambda _url, _question: "answer")

    with Log(tmp_path) as log:
        result = json.loads(vision(
            str(image), "Describe it", client=client, config=VisionConfig(),
            root=tmp_path, log=log,
        ))

    assert result["answer"] == "answer"
    assert not (tmp_path / "assets").exists()


def test_remote_vision_url_is_not_fetched_and_answer_is_bounded(tmp_path, monkeypatch):
    remote = "https://example.test/image.png"
    seen = []
    client = SimpleNamespace(vision=lambda url, question: seen.append((url, question)) or "x" * 100)

    def no_read(*_args, **_kwargs):
        pytest.fail("remote vision URL was read as a local file")

    monkeypatch.setattr("willia.vision.Path.read_bytes", no_read)
    with Log(tmp_path) as log:
        result = json.loads(vision(
            remote, "Describe it", client=client, config=VisionConfig(max_chars=70),
            root=tmp_path, log=log,
        ))

    assert seen == [(remote, "Describe it")]
    assert result["source"] == remote
    assert len(result["answer"]) == 70
    assert result["answer"].endswith("[truncated to the configured vision answer limit]")
    assert not (tmp_path / "assets").exists()
