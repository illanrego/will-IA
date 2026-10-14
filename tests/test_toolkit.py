"""Check the fixed tool array against its documented contract."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import re

import pytest

from willia import Compactor, Tree, prompts


DOCS = Path(__file__).resolve().parents[1] / "docs"
NAMES = (
    "zoom", "date", "delegate_codex", "delegate_hermes", "web_search", "web_extract", "vision",
    "terminal", "read_file", "write_file", "patch", "search_files",
    "mcp", "skills", "todo",
)


def test_system_prompt_matches_canonical_block():
    source = (DOCS / "optchat-gist.md").read_text()
    section = source.split("## 5. The prompt\n", 1)[1].split("\n## 6.", 1)[0]
    block = section.split("```\n", 1)[1].split("\n```", 1)[0]
    computers = (
        "The user's computers that have unii open now are listed at the start of each\n"
        "message. Your shell, read, write and edit tools run on the one their `device`\n"
        'field names; computer tasks, on one marked "computer use". A task that needs a\n'
        "computer not listed can't be done now: tell the user.\n\n"
    )
    assert block.count(computers) == 1
    expected = block.replace(computers, "").replace("Unii", "WillIA").replace("unii", "will")
    assert prompts.SYSTEM_PROMPT.encode("utf-8") == expected.encode("utf-8")
    assert "unii" not in prompts.SYSTEM_PROMPT
    assert not hasattr(prompts, "COMPACTION_SYSTEM")
    assert not hasattr(prompts, "RUBRIC")


def documented_schemas():
    blocks = re.findall(r"```json\n(.*?)\n```", (DOCS / "TOOLS.md").read_text(), re.DOTALL)
    result = [json.loads(block) for block in blocks]
    # Section 4 defines this schema by reference, with just two fields removed.
    hermes = deepcopy(result[2])
    hermes["function"]["name"] = "delegate_hermes"
    for field in ("model", "dir"):
        del hermes["function"]["parameters"]["properties"][field]
    result.insert(3, hermes)
    return result


def test_schema_names_and_order():
    toolkit = importlib.import_module("willia.toolkit")
    assert toolkit.TOOL_NAMES == NAMES
    assert tuple(schema["function"]["name"] for schema in toolkit.schemas()) == NAMES


def test_all_tool_names_are_in_the_composed_prompt():
    toolkit = importlib.import_module("willia.toolkit")
    instructions = prompts.default_instructions()
    composed = prompts.build_system_prompt(instructions)
    assert all(name in composed for name in toolkit.TOOL_NAMES)
    assert all(name in prompts.SYSTEM_PROMPT for name in ("zoom", "date"))
    assert composed.startswith(prompts.SYSTEM_PROMPT)
    assert len(composed) > len(prompts.SYSTEM_PROMPT)
    assert instructions
    assert all(name in instructions for name in NAMES[2:7])
    assert all(name in prompts.TOOL_GROUPS for name in NAMES[7:])


def test_schemas_match_documented_contract():
    toolkit = importlib.import_module("willia.toolkit")
    assert toolkit.schemas() == documented_schemas()
    assert json.loads(json.dumps(toolkit.schemas())) == toolkit.schemas()


def test_schemas_return_fresh_deep_copies():
    toolkit = importlib.import_module("willia.toolkit")
    first = toolkit.schemas()
    second = toolkit.schemas()
    first[0]["function"]["parameters"]["properties"]["id"]["anyOf"][0]["type"] = "null"
    first[0]["function"]["parameters"]["required"].append("scope")
    first[0]["function"]["description"] = "Changed"
    first.pop()
    assert second == documented_schemas()
    assert toolkit.schemas() == second


@pytest.mark.parametrize(("name", "required"), [
    ("zoom", ["id"]),
    ("date", ["id"]),
    ("delegate_codex", ["task"]),
    ("delegate_hermes", ["task"]),
    ("web_search", ["query"]),
    ("web_extract", ["urls"]),
    ("vision", ["image_url", "question"]),
    ("terminal", ["command"]),
    ("read_file", ["path"]),
    ("write_file", ["path", "content"]),
    ("patch", ["path", "old_string", "new_string"]),
    ("search_files", ["pattern"]),
    ("mcp", ["action"]),
    ("skills", ["action"]),
    ("todo", ["action"]),
])
def test_function_schema_shape(name, required):
    toolkit = importlib.import_module("willia.toolkit")
    registry = dict(zip(toolkit.TOOL_NAMES, toolkit.schemas(), strict=True))
    schema = registry[name]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == name
    assert isinstance(schema["function"]["description"], str)
    assert schema["function"]["description"]
    parameters = schema["function"]["parameters"]
    assert parameters["type"] == "object"
    assert parameters["required"] == required
    assert set(required) <= parameters["properties"].keys()


def test_compaction_task_is_only_the_template(tmp_path):
    tree = Tree(tmp_path, node_bytes=16)
    compactor = Compactor(tree, lambda request: "summary", node_bytes=16)
    compactor.system = prompts.SYSTEM_PROMPT
    compactor.seed(0, "long source message", "user")
    request = compactor._request(0, 0)
    assert request.system == prompts.SYSTEM_PROMPT
    assert request.task == prompts.COMPACTION_TASK.format(
        id=0, node_bytes=16, ruler="-" * 16, input="user: long source message",
    )

    tree.put(0, 0, "user: first")
    tree.put(0, 1, "user: second")
    request = compactor._request(1, 0)
    assert request.system == prompts.SYSTEM_PROMPT
    assert request.task == prompts.COMPACTION_MERGE_TASK.format(
        a="0+1", b="1+1", id=0, end=1, node_bytes=16, ruler="-" * 16,
        input="user: first\nuser: second",
    )


def test_build_system_prompt_without_instructions():
    expected = prompts.SYSTEM_PROMPT + "\n\n" + prompts.TOOL_GROUPS + "\n\n"
    assert prompts.build_system_prompt() == expected
    assert prompts.build_system_prompt("") == expected


@pytest.mark.parametrize("instructions", ["My instructions", "  Keep the indent\n", "Line one\nLine two\n\n"])
def test_build_system_prompt_appends_only_startup_instructions(instructions):
    assert prompts.build_system_prompt(instructions) == (
        prompts.SYSTEM_PROMPT + "\n\n" + prompts.TOOL_GROUPS + "\n\n" + instructions
    )
