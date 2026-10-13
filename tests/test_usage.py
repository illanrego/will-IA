"""The usage meter: canonical buckets, the append-only log, and the plan windows."""

from __future__ import annotations

import json

import pytest

from willia import usage
from willia.client import Client
from willia.compactor import CompactionRequest
from willia.config import Config
from willia.envfile import MissingCredential


# The exact object the route returned for a real compaction (WIRE-FORMATS section 1).
MEASURED = {
    "prompt_tokens": 2406, "completion_tokens": 92, "total_tokens": 2498,
    "prompt_tokens_details": {"audio_tokens": 0, "cached_tokens": 2304,
                              "cache_creation_input_tokens": 0, "cache_write_tokens": 0},
    "completion_tokens_details": {"accepted_prediction_tokens": 0, "audio_tokens": 0,
                                  "reasoning_tokens": 0, "rejected_prediction_tokens": 0},
}

CALL = {"prompt_tokens": 100, "completion_tokens": 7,
        "prompt_tokens_details": {"cached_tokens": 90},
        "completion_tokens_details": {"reasoning_tokens": 3}}


class _Response:
    def __init__(self, body):
        self.body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


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


def sse(chunk):
    return "data: " + json.dumps(chunk)


def test_canonical_widens_the_measured_object():
    assert usage.canonical(MEASURED) == {
        "input_tokens": 2406, "output_tokens": 92, "cache_read_tokens": 2304,
        "cache_write_tokens": 0, "reasoning_tokens": 0,
    }


@pytest.mark.parametrize("raw", [None, {}, "nope", {"prompt_tokens": "many"},
                                 {"prompt_tokens_details": 5},
                                 {"completion_tokens_details": None}])
def test_canonical_widens_junk_to_zeros_without_raising(raw):
    assert usage.canonical(raw) == {name: 0 for name in usage.BUCKETS}


def test_record_appends_one_line_per_call_and_totals_by_kind(tmp_path):
    assert usage.record(tmp_path, kind="turn", model="m", usage=MEASURED) is not None
    assert usage.record(tmp_path, kind="turn", model="m", usage=MEASURED) is not None
    assert usage.record(tmp_path, kind="compaction", model="m", usage=CALL) is not None

    path = usage.usage_file(tmp_path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    entry = json.loads(lines[0])
    assert entry["kind"] == "turn" and entry["model"] == "m"
    assert entry["input_tokens"] == 2406 and entry["cache_read_tokens"] == 2304
    assert entry["at"].endswith("+00:00")

    summary = usage.totals(usage.read(path))
    assert summary["calls"] == 3
    assert summary["input_tokens"] == 2406 * 2 + 100
    assert summary["by_kind"]["turn"]["calls"] == 2
    assert summary["by_kind"]["compaction"]["cache_read_tokens"] == 90
    assert summary["by_kind"]["compaction"]["reasoning_tokens"] == 3


def test_a_call_without_usage_is_not_recorded(tmp_path):
    assert usage.record(tmp_path, kind="turn", model="m", usage={}) is None
    assert usage.record(tmp_path, kind="turn", model="m", usage=None) is None
    assert not usage.usage_file(tmp_path).exists()


def test_a_meter_failure_never_raises_and_reads_as_empty(tmp_path):
    (tmp_path / "logs").write_text("not a directory")      # mkdir under it will fail
    assert usage.record(tmp_path, kind="turn", model="m", usage=MEASURED) is not None
    assert usage.read(usage.usage_file(tmp_path)) == []


def test_read_skips_a_torn_or_foreign_line(tmp_path):
    path = usage.usage_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"kind":"turn","input_tokens":1}\nnot json\n[1,2]\n\n', encoding="utf-8")
    entries = usage.read(path)
    assert entries == [{"kind": "turn", "input_tokens": 1}]
    assert usage.totals(entries)["input_tokens"] == 1
    assert usage.totals(entries)["by_kind"]["turn"]["calls"] == 1


def test_subscription_windows_reads_the_measured_shape(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.headers)
        return _Response(json.dumps({"usage": {
            "rolling": {"percent": 12.5, "resetsAt": "2026-10-13T08:00:00Z"},
            "monthly": {"percent": 0.4, "resetsAt": "2026-11-01T00:00:00Z"},
        }}))

    monkeypatch.setattr("willia.usage.urllib.request.urlopen", urlopen)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "meter-key")
    windows = usage.subscription_windows(Config())

    assert seen["url"] == "https://opencode.ai/zen/go/v1/usage"
    assert seen["headers"]["Authorization"] == "Bearer meter-key"
    assert seen["headers"]["Accept"] == "application/json"
    assert windows["rolling"]["percent"] == 12.5
    assert windows["monthly"]["resetsAt"] == "2026-11-01T00:00:00Z"
    # An absent window does not apply to the plan; it is not an error and not a zero.
    assert "weekly" not in windows


@pytest.mark.parametrize("body", ["{}", '{"usage": null}', '{"usage": []}'])
def test_subscription_windows_tolerates_a_missing_block(monkeypatch, body):
    monkeypatch.setattr("willia.usage.urllib.request.urlopen",
                        lambda request, timeout: _Response(body))
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "meter-key")
    assert usage.subscription_windows(Config()) == {}


def test_subscription_windows_needs_the_credential(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.setenv("WILLIA_ENV_FILE", str(tmp_path / "absent.env"))
    with pytest.raises(MissingCredential):
        usage.subscription_windows(Config())


def test_a_turn_is_metered(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    transport = FakeTransport(
        [sse({"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}),
         "data: " + json.dumps({"choices": [], "usage": CALL}),
         "data: [DONE]"],
    )
    client = Client(Config(root=tmp_path), "session", transport=transport)
    client.turn([{"role": "user", "content": "x"}], [])

    entries = usage.read(usage.usage_file(tmp_path))
    assert [entry["kind"] for entry in entries] == ["turn"]
    assert entries[0]["input_tokens"] == 100
    assert entries[0]["cache_read_tokens"] == 90
    assert entries[0]["reasoning_tokens"] == 3


def test_a_compaction_is_metered(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    transport = FakeTransport(json.dumps({
        "choices": [{"message": {"content": "a line"}, "finish_reason": "stop"}],
        "usage": CALL,
    }))
    client = Client(Config(root=tmp_path), "session", transport=transport)
    client.summarize(CompactionRequest(system="s", context="c", task="t", tools=[]))

    assert [entry["kind"] for entry in usage.read(usage.usage_file(tmp_path))] == ["compaction"]


def test_a_vision_call_is_metered(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    transport = FakeTransport(json.dumps({
        "choices": [{"message": {"content": "Red"}, "finish_reason": "stop"}],
        "usage": CALL,
    }))
    client = Client(Config(root=tmp_path), "session", transport=transport)
    client.vision("data:image/png;base64,YWJj", "What colour?")

    assert [entry["kind"] for entry in usage.read(usage.usage_file(tmp_path))] == ["vision"]


def test_a_failed_call_meters_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "k")
    transport = FakeTransport(ValueError("boom"))
    client = Client(Config(root=tmp_path), "session", transport=transport)
    with pytest.raises(ValueError):
        client.vision("data:image/png;base64,YWJj", "What colour?")

    assert usage.read(usage.usage_file(tmp_path)) == []
