"""The usage meter: canonical buckets, the append-only log, and the plan windows."""

from __future__ import annotations

import json
import urllib.error

import pytest

from willia import cli, usage
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

CODEX_MEASURED = {
    "plan_type": "plus",
    "rate_limit": {
        "allowed": True,
        "limit_reached": False,
        "primary_window": {
            "used_percent": 12, "limit_window_seconds": 18_000,
            "reset_after_seconds": 14_900, "reset_at": 1_791_975_321,
        },
        "secondary_window": {
            "used_percent": 18, "limit_window_seconds": 604_800,
            "reset_after_seconds": 551_849, "reset_at": 1_792_512_270,
        },
    },
    "model_usage": {
        "gpt-6-astra": {
            "available": True, "available_at": None, "credits_would_enable": False,
        },
    },
    "rate_limit_reset_credits": {"available_count": 3, "applicable_available_count": 0},
    "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
    "user_id": "must-not-escape",
    "account_id": "must-not-escape",
    "email": "must-not-escape@example.com",
}


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


@pytest.mark.parametrize(("seconds", "rendered"), [
    (720, "12m"),
    (13_860, "3h51m"),
    (407_400, "4d17h"),
    (-1, "0m"),
    (None, "?"),
])
def test_countdown_has_one_compact_duration_format(seconds, rendered):
    assert usage.countdown(seconds) == rendered


def test_codex_windows_reads_the_measured_shape_without_exposing_identity(monkeypatch, tmp_path):
    auth_file = tmp_path / "auth.json"
    auth_text = json.dumps({
        "tokens": {"access_token": "secret-token", "account_id": "secret-account"},
    })
    auth_file.write_text(auth_text, encoding="utf-8")
    seen = {}

    def urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = {key.lower(): value for key, value in request.header_items()}
        seen["timeout"] = timeout
        return _Response(json.dumps(CODEX_MEASURED))

    monkeypatch.setattr("willia.usage.urllib.request.urlopen", urlopen)
    windows = usage.codex_windows(auth_file=auth_file, timeout=4.5)

    assert seen["url"] == "https://chatgpt.com/backend-api/wham/usage"
    assert seen["headers"]["authorization"] == "Bearer secret-token"
    assert seen["headers"]["chatgpt-account-id"] == "secret-account"
    assert seen["headers"]["accept"] == "application/json"
    assert seen["headers"]["user-agent"].startswith("willia/")
    assert seen["timeout"] == 4.5
    assert windows == {
        "plan": "plus",
        "primary": {"label": "5h", "percent": 12, "resets_in_s": 14_900},
        "secondary": {"label": "7d", "percent": 18, "resets_in_s": 551_849},
        "reset_credits": 3,
        "astra_available": True,
    }
    assert "must-not-escape" not in json.dumps(windows)
    assert auth_file.read_text(encoding="utf-8") == auth_text


def test_codex_windows_uses_the_non_backend_path_style(monkeypatch, tmp_path):
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({
        "tokens": {"access_token": "token", "account_id": "account"},
    }), encoding="utf-8")
    seen = {}

    def urlopen(request, timeout):
        seen["url"] = request.full_url
        return _Response("{}")

    monkeypatch.setattr("willia.usage.urllib.request.urlopen", urlopen)
    windows = usage.codex_windows(base="https://example.test", auth_file=auth_file)

    assert seen["url"] == "https://example.test/api/codex/usage"
    assert windows == {
        "plan": None,
        "primary": {"label": "5h", "percent": None, "resets_in_s": None},
        "secondary": {"label": "7d", "percent": None, "resets_in_s": None},
        "reset_credits": None,
        "astra_available": None,
    }


def test_codex_windows_names_an_absent_auth_file(tmp_path):
    with pytest.raises(usage.CodexAuthMissingError, match="auth file is absent") as caught:
        usage.codex_windows(auth_file=tmp_path / "absent.json")
    assert "token" not in str(caught.value).lower()


@pytest.mark.parametrize(("failure", "error", "message"), [
    (urllib.error.HTTPError("safe", 401, "no", {}, None),
     usage.CodexTokenExpiredError, "token expired"),
    (urllib.error.URLError("offline"), usage.CodexNetworkError, "network failure"),
])
def test_codex_windows_names_remote_failures_without_credentials(
        monkeypatch, tmp_path, failure, error, message):
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({
        "tokens": {"access_token": "secret-token", "account_id": "secret-account"},
    }), encoding="utf-8")
    monkeypatch.setattr(
        "willia.usage.urllib.request.urlopen",
        lambda request, timeout: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(error, match=message) as caught:
        usage.codex_windows(auth_file=auth_file)
    rendered = str(caught.value)
    assert "secret-token" not in rendered
    assert "secret-account" not in rendered


def test_usage_cli_keeps_go_when_codex_is_unavailable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(usage, "subscription_windows", lambda _config: {
        "rolling": {"percent": 4, "resetsAt": "2099-01-01T00:00:00Z"},
    })
    monkeypatch.setattr(
        usage, "codex_windows",
        lambda: (_ for _ in ()).throw(usage.CodexNetworkError("Codex usage network failure")),
    )

    cli._print_usage(Config(root=tmp_path))
    output = capsys.readouterr().out

    assert "Calls: 0" in output
    assert "go:\nrolling: 4% resets 2099-01-01T00:00:00Z (" in output
    assert "codex: unavailable (Codex usage network failure)" in output


def test_usage_cli_keeps_codex_when_go_is_unavailable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        usage, "subscription_windows",
        lambda _config: (_ for _ in ()).throw(MissingCredential("missing Go credential")),
    )
    monkeypatch.setattr(usage, "codex_windows", lambda: {
        "plan": "plus",
        "primary": {"label": "5h", "percent": 12, "resets_in_s": 14_900},
        "secondary": {"label": "7d", "percent": 18, "resets_in_s": 551_849},
        "reset_credits": 3,
        "astra_available": True,
    })

    cli._print_usage(Config(root=tmp_path))
    output = capsys.readouterr().out

    assert "Windows: unavailable (missing Go credential)" in output
    assert "codex: plan=plus" in output
    assert "5h: 12% resets 4h8m" in output
    assert "7d: 18% resets 6d9h" in output
    assert "reset credits: 3" in output


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
