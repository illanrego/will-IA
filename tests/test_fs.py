"""Offline coverage for the native shell and filesystem tool batch."""

from dataclasses import replace
import json
import time

import pytest

from willia.config import Config, DEFAULT_WORKSPACE
from willia.dispatch import dispatch
from willia.fs import patch, read_file, search_files, terminal, write_file


def result(payload):
    assert isinstance(payload, str)
    return json.loads(payload)


def settings(tmp_path, **changes):
    return replace(Config(workspace=str(tmp_path)), **changes)


def test_terminal_runs_real_command_and_captures_both_streams(tmp_path):
    payload = result(terminal(
        'python3 -c "import sys; print(\'out\'); print(\'err\', file=sys.stderr)"',
        config=settings(tmp_path),
    ))

    assert payload == {
        "exit_code": 0,
        "stdout": "out\n",
        "stderr": "err\n",
        "workdir": str(tmp_path),
        "timed_out": False,
    }


def test_terminal_timeout_kills_the_sleeping_process_group(tmp_path):
    started = time.monotonic()
    payload = result(terminal(
        'python3 -c "import subprocess,sys,time; '
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        'time.sleep(30)"',
        timeout_s=1,
        config=settings(tmp_path),
    ))

    assert time.monotonic() - started < 5
    assert payload["timed_out"] is True
    assert payload["exit_code"] != 0


def test_terminal_clips_head_and_tail_and_validates_workdir(tmp_path):
    clipped = result(terminal(
        'python3 -c "print(\'abcdefghij\', end=\'\')"',
        config=settings(tmp_path, tool_clip_chars=6),
    ))
    missing = result(terminal("true", workdir=str(tmp_path / "absent")))

    assert clipped["stdout"] == "abchij"
    assert "does not exist" in missing["error"]


def test_read_file_paginates_numbers_and_counts_replaced_bytes(tmp_path):
    source = tmp_path / "legacy.txt"
    source.write_bytes(b"one\ncaf\xe9\nthree\n")

    payload = result(read_file("legacy.txt", offset=2, limit=2, config=settings(tmp_path)))

    assert payload == {
        "path": str(source),
        "content": "2: caf\ufffd\n3: three",
        "total_lines": 3,
        "offset": 2,
        "replaced_bytes": 1,
    }


def test_read_file_refuses_nul_binary_and_directory(tmp_path):
    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"text\x00more")

    assert "binary" in result(read_file(str(binary)))["error"]
    assert "not a file" in result(read_file(str(tmp_path)))["error"]
    assert "does not exist" in result(read_file(str(tmp_path / "missing")))["error"]


def test_read_file_stops_at_the_bounded_head(tmp_path, monkeypatch):
    source = tmp_path / "long.txt"
    source.write_bytes(b"one\ntwo\nthree\n")
    monkeypatch.setattr("willia.fs._MAX_READ_BYTES", 8)

    payload = result(read_file(str(source)))

    assert payload["content"] == "1: one\n2: two"
    assert payload["total_lines"] == 2
    assert "three" not in payload["content"]


def test_write_file_accepts_absolute_path_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = tmp_path / "new" / "elsewhere.txt"

    payload = result(write_file(str(destination), "olá", settings(workspace)))

    assert payload == {"path": str(destination), "bytes_written": 4}
    assert destination.read_text() == "olá"


def test_patch_requires_one_match_unless_replace_all(tmp_path):
    source = tmp_path / "words.txt"
    source.write_text("old\nold\n")

    repeated = result(patch(str(source), "old", "new"))
    changed = result(patch(str(source), "old", "new", replace_all=True))
    absent = result(patch(str(source), "missing", "new"))

    assert "more than once" in repeated["error"]
    assert changed["path"] == str(source)
    assert changed["replacements"] == 2
    assert "-old" in changed["diff"]
    assert "+new" in changed["diff"]
    assert source.read_text() == "new\nnew\n"
    assert "not found" in absent["error"]


def test_search_files_content_names_filters_and_truncation(tmp_path):
    (tmp_path / "a.py").write_text("needle one\nneedle two\n")
    (tmp_path / "b.txt").write_text("needle ignored by glob\n")
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "hidden.py").write_text("needle hidden\n")

    content = result(search_files(
        "needle", path=str(tmp_path), file_glob="*.py", limit=1,
    ))
    names = result(search_files("*.txt", target="files", path=str(tmp_path)))

    assert content == {
        "results": [{"path": str(tmp_path / "a.py"), "line": 1, "text": "needle one"}],
        "truncated": True,
    }
    assert names == {"results": [{"path": str(tmp_path / "b.txt")}], "truncated": False}


def test_search_files_skips_binary_and_files_over_five_megabytes(tmp_path):
    (tmp_path / "binary.txt").write_bytes(b"needle\x00")
    (tmp_path / "large.txt").write_bytes(b"needle" + b"x" * (5 * 1024 * 1024))

    assert result(search_files("needle", path=str(tmp_path)))["results"] == []


def test_config_workspace_is_shared_with_unset_codex_dir(tmp_path):
    config_file = tmp_path / "config.json"
    workspace = tmp_path / "work"
    config_file.write_text(json.dumps({"workspace": str(workspace)}))

    configured = Config.load(config_file)

    assert Config().workspace == DEFAULT_WORKSPACE
    assert Config().delegates.codex.dir == DEFAULT_WORKSPACE
    assert configured.workspace == str(workspace)
    assert configured.delegates.codex.dir == str(workspace)


def test_explicit_codex_dir_overrides_workspace(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "workspace": str(tmp_path / "work"),
        "delegates": {"codex": {"dir": str(tmp_path / "delegate")}},
    }))

    configured = Config.load(config_file)

    assert configured.delegates.codex.dir == str(tmp_path / "delegate")


@pytest.mark.parametrize("name,arguments", [
    ("terminal", {"command": "python3 -c \"print('ok')\""}),
    ("read_file", {"path": "source.txt"}),
    ("write_file", {"path": "written.txt", "content": "made"}),
    ("patch", {"path": "source.txt", "old_string": "source", "new_string": "changed"}),
    ("search_files", {"pattern": "changed", "path": "source.txt"}),
])
def test_dispatch_routes_each_tool_without_an_owning_chat(tmp_path, monkeypatch, name, arguments):
    monkeypatch.setattr("willia.dispatch.Config", lambda: settings(tmp_path))
    (tmp_path / "source.txt").write_text("source\n")

    payload = result(dispatch(
        name, arguments, log=None, tree=None, view=None, root=tmp_path,
        node_bytes=512, chat=None,
    ))

    assert "error" not in payload
