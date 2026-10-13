import json

import pytest

from willia.records import classify, clip_tool_output, delegate_name
from willia.text import split_for_kind


@pytest.mark.parametrize("role,kind", [("user", "user"), ("assistant", "will")])
def test_plain_text_is_split_without_loss(role, kind):
    text = "hello é " * 100
    assert classify({"role": role, "content": text}, 64) == [
        (kind, chunk) for chunk in split_for_kind(text, 64, kind)
    ]


def test_media_list_keeps_only_nonmedia_text():
    content = [{"type": "text", "text": "a"},
               {"type": "image_url", "text": "hidden"},
               {"type": "input_audio", "text": "hidden"},
               {"type": "file", "text": "hidden"},
               {"text": "b"}, {"type": None, "text": "c"},
               {"text": 1}, "ignored"]
    assert classify({"role": "user", "content": content}, 512) == [("user", "a\nb\nc")]


@pytest.mark.parametrize("message", [
    {"role": "assistant", "content": ""},
    {"role": "assistant", "content": None, "reasoning_content": "secret"},
    {"role": "assistant", "content": [{"type": "image", "text": "hidden"}]},
    {"role": "system", "content": "ignored"}, {},
])
def test_messages_without_records(message):
    assert classify(message, 512) == []


def test_two_calls_have_exact_compact_records():
    message = {"role": "assistant", "content": "é", "tool_calls": [
        {"function": {"name": "zoom", "arguments": '{ "id": 3 }'}},
        {"function": {"name": "date", "arguments": "broken"}},
    ]}
    assert classify(message, 512) == [
        ("tool", '{"name":"zoom","arguments":{"id":3},"content":"é"}'),
        ("tool", '{"name":"date","arguments":"broken","content":"é"}'),
    ]
    message["content"] = None
    assert "content" not in json.loads(classify(message, 512)[0][1])


def test_tool_output_is_head_and_tail():
    text = "a" * 15_000 + "X" + "b" * 15_000
    assert clip_tool_output(text) == "a" * 15_000 + "b" * 15_000
    assert classify({"role": "tool", "content": text}, 512) == [("echo", clip_tool_output(text))]
    assert clip_tool_output(text[:30_000]) == text[:30_000]


@pytest.mark.parametrize("tool", ["delegate_codex", "delegate_hermes"])
def test_delegate_record_names_original_payload_before_clipping(tool):
    payload = json.dumps({"name": "Name", "report": "x" * 31_000})
    assert classify({"role": "tool", "content": payload}, 512, tool) == [
        ("work", "[Name] " + clip_tool_output(payload))
    ]
    assert classify({"role": "tool", "content": "bad"}, 512, tool) == [("work", "[subagent] bad")]


@pytest.mark.parametrize("payload,expected", [
    ('{"name":"N","agent":"A","task":"T"}', "N"),
    ('{"name":"","agent":"A"}', "A"), ('{"agent":3,"task":"T"}', "T"),
    ('[]', "subagent"), ('null', "subagent"), ('bad', "subagent"), ('{}', "subagent"),
])
def test_delegate_name(payload, expected):
    assert delegate_name(payload) == expected
